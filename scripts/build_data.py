"""Build the CFO Performance Pack source files from AdventureWorksDW (MIT licence).

Usage:  python -I build_data.py <raw_dir> <out_dir>
  raw_dir: folder with the AdventureWorksDW CSV exports (pipe-delimited, from
           github.com/microsoft/sql-server-samples, release "adventureworks").
  out_dir: the project's data/ folder.

Key assumptions (documented in docs/02-data.md):
  * Fiscal year runs 1 April - 31 March and is named by the year it ends
    (FY2027 = Apr 2026 - Mar 2027).
  * The 36 AdventureWorks month-end snapshots are re-dated to Apr 2024 - Mar 2027.
  * The pack is "closed" at Oct 2026 (month 7 of FY2027). Nov 2026 - Mar 2027
    actuals and the FY2028 budget are written to inbox/ for the live demo.
  * FY2025 budget = the original AdventureWorks budget. FY2026-FY2028 budgets are
    synthetic: prior-year actual x growth x seeded noise, tagged BudgetSource=Synthetic.
  * Realistic source-system issues are injected (seeded, logged in
    data/dq_injection_log.csv) so the Power Query cleaning and data-quality checks
    have something real to catch. Totals are unchanged by the injections except
    where the log says otherwise.
Deterministic: fixed seed -> identical files on every run.
"""
import csv, os, random, sys, collections
from datetime import date

RAW, OUT = sys.argv[1], sys.argv[2]
SEED = 20261111
FIRST_MONTH = (2024, 4)      # period 1 = Apr 2024 (start of FY2025)
AS_OF = (2026, 10)           # last closed month shipped in actuals/
GROWTH = {'Revenue': 0.06, 'Expenditures': 0.04}
NOISE = 0.03

def rd(name):
    return list(csv.reader(open(os.path.join(RAW, name), encoding='utf-8'), delimiter='|'))

def wr(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh); w.writerow(header); w.writerows(rows)

def month_add(ym, n):
    t = ym[0] * 12 + (ym[1] - 1) + n
    return (t // 12, t % 12 + 1)

def ym_str(ym): return f'{ym[0]:04d}-{ym[1]:02d}'
def fy(ym): return ym[0] + (1 if ym[1] >= 4 else 0)

acc = {a[0]: a for a in rd('DimAccount.csv')}
org = {o[0]: o for o in rd('DimOrganization.csv')}
dept = rd('DimDepartmentGroup.csv')
cur = {c[0]: c for c in rd('DimCurrency.csv')}
fact = rd('FactFinance.csv')   # key|datekey|org|dept|scenario|account|amount|date

# ---- period mapping: cluster snapshot dates within 3 days ----
def d(k): return date(int(k[:4]), int(k[4:6]), int(k[6:]))
cnt = collections.Counter(r[1] for r in fact)
clusters = []
for k in sorted(cnt):
    if clusters and (d(k) - d(clusters[-1][-1])).days <= 3: clusters[-1].append(k)
    else: clusters.append([k])
if sum(cnt[k] for k in clusters[-1]) < 100: clusters.pop()          # trailing stragglers
period_of = {k: i + 1 for i, c in enumerate(clusters) for k in c}
month_of = {p: month_add(FIRST_MONTH, p - 1) for p in range(1, len(clusters) + 1)}

# ---- reference files ----
def stmt(t):
    return 'Balance Sheet' if t in ('Assets', 'Liabilities') else 'Income Statement' if t in ('Revenue', 'Expenditures') else 'Statistical'
acct_rows = [[a[0], a[1], a[2], a[4], a[5], a[6], stmt(a[5])] for a in acc.values()]
# New GL account opened Apr 2026 (see injection 4)
acct_rows.append(['102', '58', '6450', 'Software Subscriptions', 'Expenditures', '+', 'Income Statement'])
wr(f'{OUT}/reference/Account.csv', ['AccountKey', 'ParentAccountKey', 'AccountCode', 'AccountName', 'AccountType', 'UnaryOperator', 'Statement'], acct_rows)
wr(f'{OUT}/reference/Entity.csv', ['EntityKey', 'ParentEntityKey', 'EntityName', 'OwnershipPct', 'CurrencyCode'],
   [[o[0], o[1], o[3], o[2], cur[o[4]][1]] for o in org.values()])
wr(f'{OUT}/reference/Department.csv', ['DepartmentKey', 'ParentDepartmentKey', 'DepartmentName'], dept)

HDR = ['Month', 'EntityKey', 'DepartmentKey', 'AccountKey', 'AmountLC']
by_month = collections.defaultdict(list)
for r in fact:
    if r[4] == '1' and r[1] in period_of:
        ym = month_of[period_of[r[1]]]
        by_month[ym].append([ym_str(ym) + '-01', r[2], r[3], r[5], r[6]])
for ym in by_month: by_month[ym].sort()

# ---- budgets (from clean actuals, before injections) ----
BH = ['Month', 'EntityKey', 'DepartmentKey', 'AccountKey', 'AmountLC', 'BudgetSource']
orig = sorted([month_of[period_of[r[1]]], r[2], r[3], r[5], r[6]] for r in fact if r[4] == '2' and r[1] in period_of)
wr(f'{OUT}/budget/GL_Budget_FY{fy(orig[0][0])}.csv', BH, [[ym_str(m) + '-01', e, dp, a, v, 'Original'] for m, e, dp, a, v in orig])
rng = random.Random(SEED)
def synth(base_fy, folder):
    out = []
    for ym in sorted(k for k in by_month if fy(k) == base_fy):
        for _, e, dp, a, amt in by_month[ym]:
            t = acc[a][5]
            if t not in GROWTH: continue
            v = float(amt) * (1 + GROWTH[t]) * (1 + rng.uniform(-NOISE, NOISE))
            out.append([ym_str(month_add(ym, 12)) + '-01', e, dp, a, f'{v:.2f}', 'Synthetic'])
    wr(f'{OUT}/{folder}/GL_Budget_FY{base_fy + 1}.csv', BH, out)
    return len(out)
budgets = {'FY2025 (original)': len(orig), 'FY2026': synth(2025, 'budget'), 'FY2027': synth(2026, 'budget'), 'FY2028': synth(2027, 'inbox')}

# ---- injected source-system issues (seeded and logged) ----
irng = random.Random(SEED + 1)
log = []
# 1. Exact duplicate rows: a re-export appended ~1.5% of rows twice.
for ym in [(2025, 6), (2026, 1)]:
    rows = by_month[ym]; dup = irng.sample(rows, max(1, len(rows) * 15 // 1000))
    rows.extend([list(x) for x in dup])
    log.append([ym_str(ym), 'Exact duplicate rows', len(dup), 'Re-export appended rows twice', 'Power Query removes exact duplicates'])
# 2. Blank department on ~3% of rows after a system migration.
ym = (2025, 8); rows = by_month[ym]; idx = irng.sample(range(len(rows)), len(rows) * 3 // 100)
for i in idx: rows[i][2] = ''
log.append([ym_str(ym), 'Missing DepartmentKey', len(idx), 'Department not populated after ERP migration', 'Mapped to department 0 "Unassigned"; flagged on the data-quality page'])
# 3. Schema drift: a month exported with columns reordered and an extra Comment column.
SCHEMA_DRIFT = (2026, 9)
log.append([ym_str(SCHEMA_DRIFT), 'Schema drift', len(by_month[SCHEMA_DRIFT]), 'Columns reordered; extra Comment column', 'Loader expands columns by name, so order and extras do not matter'])
# 4. New GL account: 40% of Professional Services reclassified to Software Subscriptions from Apr 2026.
moved = 0
for ym in by_month:
    if ym >= (2026, 4):
        extra = []
        for r in by_month[ym]:
            if r[3] == '74':
                part = round(float(r[4]) * 0.4, 2); r[4] = f'{float(r[4]) - part:.2f}'
                extra.append([r[0], r[1], r[2], '102', f'{part:.2f}']); moved += 1
        by_month[ym].extend(extra)
log.append(['2026-04+', 'New GL account', moved, 'Account 102 Software Subscriptions opened; 40% of account 74 reclassified', 'Added to chart of accounts and report-line map; totals unchanged'])

# ---- write actuals (one file per month) ----
for ym, rows in sorted(by_month.items()):
    folder = 'actuals' if ym <= AS_OF else 'inbox'
    path = f'{OUT}/{folder}/GL_Actual_{ym_str(ym)}.csv'
    if ym == SCHEMA_DRIFT:
        wr(path, ['AccountKey', 'Month', 'DepartmentKey', 'EntityKey', 'AmountLC', 'Comment'],
           [[a, m, dp, e, v, 'ERP v2 export'] for m, e, dp, a, v in rows])
    else:
        wr(path, HDR, rows)
wr(f'{OUT}/dq_injection_log.csv', ['Month', 'Issue', 'RowsAffected', 'Cause', 'Treatment'], log)

print('periods', len(clusters), 'first', ym_str(month_of[1]), 'last', ym_str(month_of[len(clusters)]))
print('budget rows', budgets)
for l in log: print('inject', l)
