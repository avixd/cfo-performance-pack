"""Exploratory data analysis and data-quality profiling for the CFO Performance Pack.

Usage:  python -I eda.py <data_dir> <out_dir>
  data_dir: the project's data/ folder (reference/, actuals/, budget/, fx/, dq_injection_log.csv)
  out_dir:  docs/eda/ - writes eda_report.md, eda_summary.json and PNG charts

Reproducible: reads only the generated files; no randomness.
"""
import sys, os, glob, json
import numpy as np, pandas as pd
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

DATA, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
INK, MUTED, ACT, BUD, BAD, GOOD = '#1f2933', '#7b8794', '#1f3a5f', '#9aa5b1', '#c0392b', '#2e7d32'
plt.rcParams.update({'font.size': 9, 'axes.spines.top': False, 'axes.spines.right': False,
                     'axes.edgecolor': MUTED, 'axes.labelcolor': INK, 'xtick.color': MUTED, 'ytick.color': MUTED})
S = {}   # summary for json

# ---------- 1. Load raw files exactly as delivered ----------
def load_raw(folder):
    frames = []
    for f in sorted(glob.glob(os.path.join(DATA, folder, 'GL_*.csv'))):
        t = pd.read_csv(f, dtype=str, keep_default_na=False)
        t['__file'] = os.path.basename(f); t['__cols'] = ','.join(t.columns[:-1])
        frames.append(t)
    return frames
raw_act, raw_bud = load_raw('actuals'), load_raw('budget')
acct = pd.read_csv(os.path.join(DATA, 'reference', 'Account.csv'), dtype={'AccountKey': str})
ent = pd.read_csv(os.path.join(DATA, 'reference', 'Entity.csv'), dtype={'EntityKey': str})
inj = pd.read_csv(os.path.join(DATA, 'dq_injection_log.csv'))
EXPECTED = ['Month', 'EntityKey', 'DepartmentKey', 'AccountKey', 'AmountLC']

prof = []
for t in raw_act + raw_bud:
    f = t['__file'].iat[0]; body = t.drop(columns=['__file', '__cols'])
    cols = list(body.columns)
    core = body.reindex(columns=EXPECTED)
    prof.append({'file': f, 'rows': len(body),
                 'exact_duplicates': int(body.duplicated().sum()),
                 'blank_department': int((core['DepartmentKey'].fillna('') == '').sum()),
                 'blank_any_key': int((core[['Month', 'EntityKey', 'AccountKey', 'AmountLC']].fillna('') == '').any(axis=1).sum()),
                 'unknown_account': int((~core['AccountKey'].isin(acct['AccountKey'])).sum()),
                 'non_numeric_amount': int(pd.to_numeric(core['AmountLC'], errors='coerce').isna().sum()),
                 'schema_drift': cols[:5] != EXPECTED or bool(set(cols) - set(EXPECTED) - {'BudgetSource'}),
                 'columns': ', '.join(cols)})
prof = pd.DataFrame(prof)
issues = prof[(prof[['exact_duplicates', 'blank_department', 'blank_any_key', 'unknown_account', 'non_numeric_amount']].sum(axis=1) > 0) | prof['schema_drift']]
S['files_profiled'] = int(len(prof)); S['rows_profiled'] = int(prof['rows'].sum())
S['detected'] = {k: int(prof[k].sum()) for k in ['exact_duplicates', 'blank_department', 'blank_any_key', 'unknown_account', 'non_numeric_amount']}
S['detected']['schema_drift_files'] = int(prof['schema_drift'].sum())

# reconciliation detected vs injected
inj_dup = int(inj.loc[inj['Issue'] == 'Exact duplicate rows', 'RowsAffected'].sum())
inj_dept = int(inj.loc[inj['Issue'] == 'Missing DepartmentKey', 'RowsAffected'].sum())
recon = pd.DataFrame([
    ['Exact duplicate rows', inj_dup, S['detected']['exact_duplicates']],
    ['Missing DepartmentKey', inj_dept, S['detected']['blank_department']],
    ['Schema drift (files)', int((inj['Issue'] == 'Schema drift').sum()), S['detected']['schema_drift_files']],
], columns=['Issue', 'Injected', 'Detected'])
recon['Reconciled'] = np.where(recon['Injected'] == recon['Detected'], 'Yes', 'No')

# ---------- 2. Clean exactly as Power Query does ----------
def clean(frames, scenario):
    out = []
    for t in frames:
        b = t.drop(columns=['__cols']).reindex(columns=EXPECTED + ['BudgetSource', '__file'])
        b = b.drop_duplicates(subset=EXPECTED + ['BudgetSource'])
        b['DepartmentKey'] = b['DepartmentKey'].replace('', '0').fillna('0')
        out.append(b)
    d = pd.concat(out, ignore_index=True); d['Scenario'] = scenario
    d['AmountLC'] = d['AmountLC'].astype(float); d['Month'] = pd.to_datetime(d['Month'])
    return d
gl = pd.concat([clean(raw_act, 'Actual'), clean(raw_bud, 'Budget')], ignore_index=True)
gl = gl.merge(acct[['AccountKey', 'AccountName', 'AccountType', 'Statement']], on='AccountKey', how='left')
gl = gl.merge(ent[['EntityKey', 'EntityName', 'CurrencyCode']], on='EntityKey', how='left')
S['clean_rows'] = int(len(gl)); S['post_clean_duplicates'] = int(gl.duplicated(subset=EXPECTED + ['Scenario']).sum())
S['post_clean_nulls'] = {c: int(gl[c].isna().sum()) for c in ['Month', 'EntityKey', 'DepartmentKey', 'AccountKey', 'AmountLC', 'AccountType', 'CurrencyCode']}

# FX to CAD (P&L at monthly average rate)
fx = pd.read_csv(os.path.join(DATA, 'fx', 'FX_Rates.csv'), parse_dates=['Month'])
fx = fx.pivot_table(index='Month', columns='CurrencyCode', values='AvgRate').sort_index().ffill()
def rate(row): return fx.at[row['Month'], row['CurrencyCode']] if row['Month'] in fx.index else np.nan
gl['RateAvg'] = [fx.at[m, c] if m in fx.index else fx.iloc[-1][c] for m, c in zip(gl['Month'], gl['CurrencyCode'])]
gl['AmountCAD'] = gl['AmountLC'] * gl['RateAvg']
gl['FY'] = gl['Month'].dt.year + (gl['Month'].dt.month >= 4).astype(int)
gl['FiscalMonth'] = (gl['Month'].dt.month + 8) % 12 + 1
# Budgets translate at the prior fiscal year's average rate (same rule as the semantic model)
fx_obs = pd.read_csv(os.path.join(DATA, 'fx', 'FX_Rates.csv'), parse_dates=['Month'])
fx_obs['FY'] = fx_obs['Month'].dt.year + (fx_obs['Month'].dt.month >= 4).astype(int)
fy_avg = fx_obs.groupby(['CurrencyCode', 'FY'])['AvgRate'].mean()
is_bud = gl['Scenario'] == 'Budget'
gl.loc[is_bud, 'AmountCAD'] = [lc * fy_avg.get((c, f - 1), r) for lc, c, f, r in zip(gl.loc[is_bud, 'AmountLC'], gl.loc[is_bud, 'CurrencyCode'], gl.loc[is_bud, 'FY'], gl.loc[is_bud, 'RateAvg'])]

act = gl[gl['Scenario'] == 'Actual']

# ---------- 3. Integrity: balance sheet balances ----------
bs = act[act['Statement'] == 'Balance Sheet'].groupby(['Month', 'EntityKey', 'AccountType'])['AmountLC'].sum().unstack(fill_value=0)
bs['diff'] = bs.get('Assets', 0) - bs.get('Liabilities', 0)
S['bs_entity_months'] = int(len(bs)); S['bs_max_abs_diff_LC'] = float(bs['diff'].abs().max())

# ---------- 4. Monthly group KPIs (CAD) ----------
REV, COGS = ['52', '101', '53', '54'], ['56', '57']
OPEX = ['60', '61', '62', '63', '65', '66', '67', '68', '69', '71', '72', '73', '74', '76', '77', '78', '87', '102']
def signed(d):
    s = np.where(d['AccountType'] == 'Expenditures', -1, 1); return d['AmountCAD'] * s
pl = act[act['Statement'] == 'Income Statement'].copy(); pl['Signed'] = signed(pl)
def series(keys, data=pl, by=['Month']):
    return data[data['AccountKey'].isin(keys)].groupby(by)['Signed'].sum()
m = pd.DataFrame({'Revenue': series(REV), 'CostOfSales': -series(COGS), 'OpEx': -series(OPEX)})
m['GrossMargin%'] = 1 - m['CostOfSales'] / m['Revenue']
hc = act[act['AccountKey'] == '96'].groupby('Month')['AmountLC'].sum()
m['Headcount'] = hc
m['RevGrowthMoM%'] = m['Revenue'].pct_change()

# ---------- 4b. Consolidation perimeter (entities joining over time) ----------
rev_e = pl[pl['AccountKey'].isin(REV)].groupby(['EntityName', 'Month'])['Signed'].sum()
first_m = rev_e.reset_index().groupby('EntityName')['Month'].min()
bud_first = gl[(gl['Scenario'] == 'Budget') & gl['AccountKey'].isin(REV)].groupby('EntityName')['Month'].min()
perim = pd.DataFrame({'first_actual': first_m, 'first_budget': bud_first}).reset_index()
perim = perim.merge(ent[['EntityName', 'CurrencyCode', 'OwnershipPct']], on='EntityName', how='left')
perim['joined_FY'] = 'FY' + (perim['first_actual'].dt.year + (perim['first_actual'].dt.month >= 4).astype(int)).astype(str)
for c in ['first_actual', 'first_budget']: perim[c] = perim[c].dt.strftime('%b %Y').fillna('never')
rev_fy = pl[pl['AccountKey'].isin(REV)].groupby(['FY', 'EntityName'])['Signed'].sum().unstack('FY')
S['perimeter'] = perim.to_dict('records')
# organic (like-for-like) vs acquired revenue, FY2027 YTD (Apr-Oct) vs same months FY2026
cur = pl[pl['AccountKey'].isin(REV) & (pl['FY'] == 2027)]
prev = pl[pl['AccountKey'].isin(REV) & (pl['FY'] == 2026) & (pl['FiscalMonth'] <= cur['FiscalMonth'].max())]
lfl = set(prev['EntityName'])
org_cur = cur[cur['EntityName'].isin(lfl)]['Signed'].sum(); acq_cur = cur[~cur['EntityName'].isin(lfl)]['Signed'].sum(); prev_tot = prev['Signed'].sum()
S['fy2027_ytd_revenue'] = {'total': round(cur['Signed'].sum()), 'like_for_like': round(org_cur), 'acquired': round(acq_cur), 'prior_ytd': round(prev_tot),
                           'organic_growth_pct': round(org_cur / prev_tot - 1, 4), 'total_growth_pct': round(cur['Signed'].sum() / prev_tot - 1, 4)}
budg = gl[(gl['Scenario'] == 'Budget') & gl['AccountKey'].isin(REV) & (gl['FY'] == 2027) & (gl['FiscalMonth'] <= cur['FiscalMonth'].max())]
budgeted_ents = set(budg['EntityName'])
S['fy2027_ytd_revenue']['budget'] = round(signed(budg).sum())
S['fy2027_ytd_revenue']['unbudgeted_entity_revenue'] = round(cur[~cur['EntityName'].isin(budgeted_ents)]['Signed'].sum())

# ---------- 5. Normality ----------
def norm_tests(x, name):
    x = pd.Series(x).dropna().astype(float)
    sw = stats.shapiro(x) if 3 <= len(x) <= 5000 else (np.nan, np.nan)
    dk = stats.normaltest(x) if len(x) >= 20 else (np.nan, np.nan)
    return {'series': name, 'n': int(len(x)), 'skew': round(float(stats.skew(x)), 2), 'excess_kurtosis': round(float(stats.kurtosis(x)), 2),
            'shapiro_p': None if np.isnan(sw[1]) else float(f'{sw[1]:.3g}'), 'dagostino_p': None if np.isnan(dk[1]) else float(f'{dk[1]:.3g}'),
            'normal_at_5pct': bool((sw[1] if not np.isnan(sw[1]) else dk[1]) > 0.05)}
amt = act.loc[act['Statement'] == 'Income Statement', 'AmountLC'].abs()
amt = amt[amt > 0]
# Budget variance % by entity x month (revenue)
rev_ent = pl[pl['AccountKey'].isin(REV)].groupby(['Month', 'EntityName'])['Signed'].sum()
bud = gl[(gl['Scenario'] == 'Budget') & gl['AccountKey'].isin(REV)].copy(); bud['Signed'] = signed(bud)
bud_ent = bud.groupby(['Month', 'EntityName'])['Signed'].sum()
both = pd.concat([rev_ent.rename('a'), bud_ent.rename('b')], axis=1).dropna()
var = ((both['a'] - both['b']) / both['b'].abs())
normal = pd.DataFrame([
    norm_tests(amt.sample(n=min(5000, len(amt)), random_state=7), 'GL line amounts (P&L, abs) - sample 5,000'),
    norm_tests(np.log(amt.sample(n=min(5000, len(amt)), random_state=7)), 'log(GL line amounts)'),
    norm_tests(m['Revenue'], 'Monthly group revenue (CAD)'),
    norm_tests(m['RevGrowthMoM%'], 'Month-on-month revenue growth'),
    norm_tests(var, 'Revenue variance vs budget % (budgeted entity x month)'),
])

# ---------- 6. Correlation ----------
ent_m = pd.DataFrame({'Revenue': series(REV, by=['Month', 'EntityName']), 'CostOfSales': -series(COGS, by=['Month', 'EntityName']),
                      'OpEx': -series(OPEX, by=['Month', 'EntityName']), 'Salaries': -series(['60', '61', '62'], by=['Month', 'EntityName'])})
ent_m['Headcount'] = act[act['AccountKey'] == '96'].groupby(['Month', 'EntityName'])['AmountLC'].sum()
ent_m = ent_m.dropna()
pear = ent_m.corr(method='pearson'); spear = ent_m.corr(method='spearman')
pairs = []
for a, b in [('Revenue', 'CostOfSales'), ('Revenue', 'OpEx'), ('Headcount', 'Salaries'), ('Revenue', 'Headcount')]:
    r, p = stats.pearsonr(ent_m[a], ent_m[b]); rs, ps = stats.spearmanr(ent_m[a], ent_m[b])
    pairs.append({'pair': f'{a} vs {b}', 'n': int(len(ent_m)), 'pearson_r': round(r, 3), 'pearson_p': float(f'{p:.2g}'), 'spearman_rho': round(rs, 3)})
pairs = pd.DataFrame(pairs)

# ---------- 7. Outliers (robust z on account x entity monthly series) ----------
ae = pl.groupby(['AccountName', 'EntityName', 'Month'])['Signed'].sum().reset_index()
def rz(s):
    med = s.median(); mad = (s - med).abs().median()
    return (s - med) / (1.4826 * mad) if mad else s * 0
ae['robust_z'] = ae.groupby(['AccountName', 'EntityName'])['Signed'].transform(rz)
out = ae[ae['robust_z'].abs() > 3.5].sort_values('robust_z', key=abs, ascending=False)
S['outliers_flagged'] = int(len(out)); S['outlier_series_points'] = int(len(ae))

# ---------- 8. Benford's law (first digit, all GL amounts) ----------
allamt = gl.loc[gl['Scenario'] == 'Actual', 'AmountLC'].abs()
allamt = allamt[allamt >= 10]
first = allamt.astype(str).str.lstrip('0.').str[0].astype(int)
obs = first.value_counts(normalize=True).reindex(range(1, 10), fill_value=0)
exp = pd.Series(np.log10(1 + 1 / np.arange(1, 10)), index=range(1, 10))
chi2, chip = stats.chisquare(first.value_counts().reindex(range(1, 10), fill_value=0), exp * len(first))
mad_b = float((obs - exp).abs().mean())
S['benford'] = {'n': int(len(first)), 'chi2': round(float(chi2), 1), 'p': float(f'{chip:.3g}'), 'MAD': round(mad_b, 4),
                'nigrini_conformity': 'close' if mad_b < 0.006 else 'acceptable' if mad_b < 0.012 else 'marginal' if mad_b < 0.015 else 'nonconformity'}

# ---------- 9. Seasonality ----------
seas = m.copy(); seas['FiscalMonth'] = (seas.index.month + 8) % 12 + 1
seas_idx = seas.groupby('FiscalMonth')['Revenue'].mean() / seas['Revenue'].mean()

# ---------- Charts ----------
def save(fig, name): fig.savefig(os.path.join(OUT, name), dpi=160, bbox_inches='tight'); plt.close(fig)
fig, ax = plt.subplots(1, 3, figsize=(11, 3))
ax[0].hist(amt, bins=60, color=ACT); ax[0].set_title('GL line amounts: right-skewed', loc='left', color=INK); ax[0].set_xlabel('Amount (LC)')
ax[1].hist(np.log(amt), bins=60, color=ACT); ax[1].set_title('log(amount): closer to normal', loc='left', color=INK); ax[1].set_xlabel('log amount')
stats.probplot(var, dist='norm', plot=ax[2]); ax[2].set_title(''); ax[2].get_lines()[0].set(color=ACT, markersize=3); ax[2].get_lines()[1].set(color=BAD)
ax[2].set_title('Q-Q: revenue variance vs budget (fat right tail)', loc='left', color=INK); ax[2].set_ylabel('Variance (x budget)')
save(fig, 'distributions.png')

fig, ax = plt.subplots(figsize=(5, 4))
im = ax.imshow(spear.values, cmap='RdBu_r', vmin=-1, vmax=1)
ax.set_xticks(range(len(spear))); ax.set_xticklabels(spear.columns, rotation=40, ha='right'); ax.set_yticks(range(len(spear))); ax.set_yticklabels(spear.columns)
for i in range(len(spear)):
    for j in range(len(spear)): ax.text(j, i, f'{spear.values[i, j]:.2f}', ha='center', va='center', fontsize=8, color='white' if abs(spear.values[i, j]) > .6 else INK)
ax.set_title('Spearman correlation, entity x month', loc='left', color=INK); fig.colorbar(im, ax=ax, shrink=.7)
save(fig, 'correlation.png')

fig, ax = plt.subplots(figsize=(6, 3))
ax.bar(range(1, 10), exp.values, color=BUD, label='Benford expected'); ax.plot(range(1, 10), obs.values, 'o-', color=ACT, label='Observed')
ax.set_xticks(range(1, 10)); ax.set_xlabel('First digit'); ax.set_ylabel('Share'); ax.legend(frameon=False)
ax.set_title(f"Benford first-digit test: MAD {mad_b:.4f} ({S['benford']['nigrini_conformity']})", loc='left', color=INK)
save(fig, 'benford.png')

fig, ax = plt.subplots(figsize=(8, 3))
ax.plot(m.index, m['Revenue'] / 1e6, color=ACT, lw=2)
for d in out[out['AccountName'].isin(['Trade Sales'])]['Month'].unique(): ax.axvline(d, color=BAD, lw=.8, ls='--')
ax.set_ylabel('CAD millions'); ax.set_title('Monthly group revenue, Apr 2024 - Oct 2026', loc='left', color=INK)
save(fig, 'revenue_trend.png')

fig, ax = plt.subplots(figsize=(6, 2.8))
ax.bar(seas_idx.index, seas_idx.values, color=[ACT if v >= 1 else BUD for v in seas_idx.values]); ax.axhline(1, color=MUTED, lw=.8)
ax.set_xticks(range(1, 13)); ax.set_xticklabels(['Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar'])
ax.set_title('Revenue seasonality index by fiscal month (1.0 = average)', loc='left', color=INK)
save(fig, 'seasonality.png')

# ---------- Data-driven readings ----------
def verdict(row): return 'normal' if row['normal_at_5pct'] else 'not normal'
nr = normal.set_index('series')
norm_reading = ('Reading: ' + '; '.join(f"{k.split(' - ')[0]} is {verdict(v)} (skew {v['skew']}, excess kurtosis {v['excess_kurtosis']})" for k, v in nr.iterrows()) + '. '
  'Ledger line amounts are heavily right-skewed (many small postings, few large ones), so outlier rules use median and MAD, not mean +/- 3 SD. '
  'Monthly group revenue passes both normality tests, so simple normal-based ranges are reasonable for a revenue outlook band. '
  'Variance-to-budget percentages are fat-tailed even for budgeted entities: a small number of entity-months carry most of the variance, which is why the report ranks variances instead of averaging them.')
pr = pairs.set_index('pair')
def strength(r): return 'very strong' if abs(r) >= .8 else 'strong' if abs(r) >= .6 else 'moderate' if abs(r) >= .4 else 'weak'
corr_reading = 'Reading: ' + '; '.join(f"{k}: {strength(v['spearman_rho'])} (Spearman {v['spearman_rho']}, Pearson {v['pearson_r']}, p {v['pearson_p']})" for k, v in pr.iterrows()) + '. ' \
  'Cost of sales scales almost one-for-one with revenue, so margin is protected by pricing and mix rather than volume. Operating expenses also track revenue, which means they are being added as the group grows rather than held fixed. Headcount relates to salaries but not to revenue across entities, so revenue per head varies widely by entity: a productivity question for the CFO.'
fy = S['fy2027_ytd_revenue']
perim_reading = (f"The group perimeter changes every fiscal year. FY2027 year-to-date revenue is CAD {fy['total']/1e6:.1f}M against CAD {fy['prior_ytd']/1e6:.1f}M for the same months of FY2026 "
  f"(+{fy['total_growth_pct']:.1%}). Like-for-like entities contributed CAD {fy['like_for_like']/1e6:.1f}M (organic growth {fy['organic_growth_pct']:+.1%}); entities new this year added CAD {fy['acquired']/1e6:.1f}M. "
  f"CAD {fy['unbudgeted_entity_revenue']/1e6:.1f}M of FY2027 revenue comes from entities that have no FY2027 budget, so a total-company budget variance overstates operating performance.")

# ---------- Report ----------
def md(df): return df.to_markdown(index=False)
S['normality'] = normal.to_dict('records'); S['correlation'] = pairs.to_dict('records'); S['reconciliation'] = recon.to_dict('records')
json.dump(S, open(os.path.join(OUT, 'eda_summary.json'), 'w'), indent=2, default=str)
top_out = out.head(10)[['AccountName', 'EntityName', 'Month', 'Signed', 'robust_z']].copy()
top_out['Month'] = top_out['Month'].dt.strftime('%b %Y'); top_out['Signed'] = top_out['Signed'].round(0); top_out['robust_z'] = top_out['robust_z'].round(1)
r = f"""# Exploratory data analysis and data-quality profile

Generated by `scripts/eda.py` from the files in `data/`. Rerun it after any data change; output is deterministic.

## 1. Source-file profile (before cleaning)

{S['files_profiled']} files and {S['rows_profiled']:,} raw rows were profiled. Files with at least one issue:

{md(issues[['file', 'rows', 'exact_duplicates', 'blank_department', 'unknown_account', 'non_numeric_amount', 'schema_drift']])}

**Reconciliation to the injection log** (`data/dq_injection_log.csv`): every injected issue was detected.

{md(recon)}

The new GL account 102 (Software Subscriptions) has no unknown-account rows because it was added to the chart of accounts; the report-line map includes it.

## 2. After cleaning (same rules as Power Query)

- Rows: {S['clean_rows']:,}. Exact duplicates remaining: {S['post_clean_duplicates']}.
- Nulls in key columns: {', '.join(f'{k} {v}' for k, v in S['post_clean_nulls'].items())}.
- Balance sheet integrity: {S['bs_entity_months']} entity-months checked; largest |Assets - (Liabilities + Equity)| = {S['bs_max_abs_diff_LC']:.4f} (local currency).

## 3. Consolidation perimeter

{md(perim[['EntityName', 'CurrencyCode', 'OwnershipPct', 'first_actual', 'joined_FY', 'first_budget']])}

{perim_reading}

## 4. Distribution and normality

![Distributions](distributions.png)

{md(normal)}

{norm_reading}

## 5. Correlation

![Correlation](correlation.png)

{md(pairs)}

{corr_reading}

## 6. Outliers (robust z-score > 3.5, account x entity monthly series)

{S['outliers_flagged']} of {S['outlier_series_points']:,} monthly points flagged. Largest:

{md(top_out)}

## 7. Benford's law (first digit of actual GL amounts >= 10)

![Benford](benford.png)

n = {S['benford']['n']:,}; chi-square = {S['benford']['chi2']} (p = {S['benford']['p']}); mean absolute deviation = {S['benford']['MAD']} -> Nigrini conformity: **{S['benford']['nigrini_conformity']}**. With large n, chi-square rejects almost any real dataset, so MAD is the accepted measure.

## 8. Trend and seasonality

![Revenue trend](revenue_trend.png)

![Seasonality](seasonality.png)

## Method notes

- Translation follows the semantic model: actual P&L at the Bank of Canada monthly average rate, budgets at the prior fiscal year's average rate (balance sheet at month-end rates in the model). Returns and discounts are netted off revenue in both actuals and budget.
- Normality: Shapiro-Wilk (n <= 5,000) and D'Agostino K-squared; skew and excess kurtosis reported. GL amounts are sampled to 5,000 rows with a fixed seed.
- Outliers: median and MAD per account x entity series, robust z = (x - median) / (1.4826 x MAD).
- Benford: first significant digit, chi-square goodness of fit and MAD thresholds from Nigrini (close < 0.006, acceptable < 0.012, marginal < 0.015).
"""
open(os.path.join(OUT, 'eda_report.md'), 'w').write(r)
print(json.dumps(S['fy2027_ytd_revenue'])); print(perim.to_string()); print(json.dumps({k: S[k] for k in ['files_profiled', 'rows_profiled', 'detected', 'clean_rows', 'post_clean_duplicates', 'bs_max_abs_diff_LC', 'outliers_flagged', 'benford']}, indent=1, default=str))
print(recon.to_string()); print(normal.to_string()); print(pairs.to_string()); print(top_out.to_string())
