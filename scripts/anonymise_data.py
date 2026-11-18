"""Write a masked copy of a source folder so the model (or an AI assistant) can work on realistic data without seeing the real data.

Step 1 of the "AI-safe Power BI" workflow (docs/06-ai-safe-workflow.md). The input is any folder in this project's layout
(reference/, actuals/, budget/, fx/, inbox/ with the same CSV columns as data/), for example an export from a real ledger.
The output is the same layout with:

  * the group and every operating entity renamed ("Group", "Entity 03"); region-level entities keep their generic names so
    row-level security and the region logic keep working (pass --mask-regions to rename them too: "Region 02");
  * departments renamed "Department 05" (the top-level department keeps its name);
  * every ledger amount (AmountLC) multiplied by one private scale factor, so absolute size is hidden while every ratio,
    %, variance %, margin and day-count is unchanged;
  * free-text columns in the data-quality log replaced by a neutral label;
  * keys, hierarchy, months, accounts and FX rates unchanged, so every relationship in the model still works.

Usage:
  python -I scripts/anonymise_data.py <source_dir> <masked_dir> [--scale 0.73 | --seed 42] [--mask-regions] [--mask-accounts]

The scale is never written into the output. If you give neither --scale nor --seed, a random scale in [0.5, 1.5) is used and
printed once to the console only; keep it private if you will ever need to convert masked figures back.

Validation (always runs; non-zero exit on failure, report written to <masked_dir>/MASKING_REPORT.md):
  1. same files, same row count per file;
  2. same keys in every reference and ledger file;
  3. every ledger amount equals source x scale (to 1e-6 relative), so every ratio is preserved;
  4. no masked source name (entity, department, optionally account) appears anywhere in the output.
"""
import argparse, csv, os, random, shutil, sys

LEDGER_DIRS = ('actuals', 'budget', 'inbox')
DQ_FREE_TEXT = ('Cause', 'Treatment')


def read(path):
    with open(path, newline='', encoding='utf-8') as f:
        r = csv.DictReader(f)
        return r.fieldnames, list(r)


def write(path, cols, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def num(x):
    return float(x) if x not in (None, '') else None


def fmt(x):
    return '' if x is None else repr(round(x, 6))


def entity_names(rows, mask_regions):
    root = next(r['EntityKey'] for r in rows if not r['ParentEntityKey'])
    out, region_no = {}, 0
    for r in sorted(rows, key=lambda r: int(r['EntityKey'])):
        k = r['EntityKey']
        if k == root:
            out[k] = 'Group'
        elif r['ParentEntityKey'] == root:
            region_no += 1
            out[k] = f'Region {region_no:02d}' if mask_regions else r['EntityName']
        else:
            out[k] = f'Entity {int(k):02d}'
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('source'), ap.add_argument('masked')
    ap.add_argument('--scale', type=float, help='multiplier for every ledger amount (default: random, printed once)')
    ap.add_argument('--seed', type=int, help='seed for a reproducible random scale')
    ap.add_argument('--mask-regions', action='store_true', help='also rename region-level entities (breaks the sample RLS roles)')
    ap.add_argument('--mask-accounts', action='store_true', help='also rename accounts to "Account <code>"')
    a = ap.parse_args()
    src, dst = os.path.abspath(a.source), os.path.abspath(a.masked)
    if dst == src or dst.startswith(src + os.sep):
        sys.exit('masked_dir must be outside source_dir')
    scale = a.scale if a.scale is not None else random.Random(a.seed).uniform(0.5, 1.5)
    if a.scale is None and a.seed is None:
        print(f'Random scale used: {scale:.6f}  (printed once, not stored; keep it private)')
    if os.path.exists(dst):
        shutil.rmtree(dst)

    files = sorted(os.path.relpath(os.path.join(d, f), src) for d, _, fs in os.walk(src) for f in fs if f.lower().endswith('.csv'))
    masked_names = set()
    ent_cols, ent = read(os.path.join(src, 'reference', 'Entity.csv'))
    ent_map = entity_names(ent, a.mask_regions)
    masked_names |= {r['EntityName'] for r in ent if ent_map[r['EntityKey']] != r['EntityName']}
    dep_cols, dep = read(os.path.join(src, 'reference', 'Department.csv'))
    dep_map = {r['DepartmentKey']: (r['DepartmentName'] if not r['ParentDepartmentKey'] else f"Department {int(r['DepartmentKey']):02d}") for r in dep}
    masked_names |= {r['DepartmentName'] for r in dep if dep_map[r['DepartmentKey']] != r['DepartmentName']}
    acc_cols, acc = read(os.path.join(src, 'reference', 'Account.csv'))
    acc_names = {r['AccountName'] for r in acc} if a.mask_accounts else set()   # checked in the AccountName column only (types reuse words)

    for rel in files:
        cols, rows = read(os.path.join(src, rel))
        top, name = rel.split(os.sep)[0], os.path.basename(rel)
        if rel == os.path.join('reference', 'Entity.csv'):
            rows = [dict(r, EntityName=ent_map[r['EntityKey']]) for r in rows]
        elif rel == os.path.join('reference', 'Department.csv'):
            rows = [dict(r, DepartmentName=dep_map[r['DepartmentKey']]) for r in rows]
        elif rel == os.path.join('reference', 'Account.csv') and a.mask_accounts:
            rows = [dict(r, AccountName=f"Account {r['AccountCode']}") for r in rows]
        elif top in LEDGER_DIRS and 'AmountLC' in cols:
            rows = [dict(r, AmountLC=fmt(None if num(r['AmountLC']) is None else num(r['AmountLC']) * scale)) for r in rows]
        elif name == 'dq_injection_log.csv':
            rows = [dict(r, **{c: 'masked' for c in DQ_FREE_TEXT if c in r}) for r in rows]
        write(os.path.join(dst, rel), cols, rows)

    # ---------------------------------------------------------------- validation
    problems, lines = [], []
    out_files = sorted(os.path.relpath(os.path.join(d, f), dst) for d, _, fs in os.walk(dst) for f in fs if f.lower().endswith('.csv'))
    if out_files != files:
        problems.append('file lists differ')
    rows_checked = amounts_checked = 0
    for rel in files:
        sc, sr = read(os.path.join(src, rel))
        mc, mr = read(os.path.join(dst, rel))
        if sc != mc or len(sr) != len(mr):
            problems.append(f'{rel}: columns or row count differ')
            continue
        rows_checked += len(sr)
        for s, m in zip(sr, mr):
            for c in sc:
                if c.endswith('Key') and s[c] != m[c]:
                    problems.append(f'{rel}: key {c} changed')
                    break
            if 'AmountLC' in sc and rel.split(os.sep)[0] in LEDGER_DIRS:
                x, y = num(s['AmountLC']), num(m['AmountLC'])
                if (x is None) != (y is None) or (x is not None and abs(y - x * scale) > 1e-6 * max(1.0, abs(x * scale))):
                    problems.append(f'{rel}: amount not source x scale')
                    break
                amounts_checked += 1
    leaks = []
    for rel in out_files:
        text = open(os.path.join(dst, rel), encoding='utf-8').read()
        leaks += [f'{rel}: "{n}"' for n in masked_names if n and n in text]
    if acc_names:
        _, macc = read(os.path.join(dst, 'reference', 'Account.csv'))
        leaks += [f'reference/Account.csv: "{r["AccountName"]}"' for r in macc if r['AccountName'] in acc_names]
    problems += [f'source name leaked: {x}' for x in leaks]

    lines += ['# Masking report', '',
              f'Source files: {len(files)} · rows checked: {rows_checked:,} · ledger amounts checked: {amounts_checked:,}', '',
              '| Check | Result |', '|---|---|',
              f"| Same files and row counts | {'pass' if not any('differ' in p for p in problems) else 'FAIL'} |",
              f"| Keys unchanged (relationships intact) | {'pass' if not any('key' in p for p in problems) else 'FAIL'} |",
              f"| Every amount = source x one private scale (ratios, % and trends preserved) | {'pass' if not any('amount' in p for p in problems) else 'FAIL'} |",
              f"| No masked source name appears in the output ({len(masked_names) + len(acc_names)} names checked) | {'pass' if not leaks else 'FAIL'} |", '',
              'Masked: group and operating entity names' + (', region names' if a.mask_regions else '') + ', department names'
              + (', account names' if a.mask_accounts else '') + ', ledger amounts (scaled), data-quality log free text.',
              'Unchanged: keys, hierarchy, months, accounts' + ('' if a.mask_accounts else ' (names)') + ', FX rates, ownership %.',
              'The scale factor is not recorded here.']
    if problems:
        lines += ['', '## Problems', ''] + [f'- {p}' for p in problems[:50]]
    with open(os.path.join(dst, 'MASKING_REPORT.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main()
