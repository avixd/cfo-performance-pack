"""Static checks on the generated model and report. Run: python tests/test_model.py   (CI runs it on every push).

No Power BI needed. What the engine must compute (balance sheet balances, bridges tie) is in tests/live_checks.dax,
which is run against the open model (DAX query view or any XMLA client) before a release.
"""
import glob, json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import model_def as M  # noqa: E402

SM = os.path.join(ROOT, 'CFO-Performance-Pack.SemanticModel', 'definition')
RP = os.path.join(ROOT, 'CFO-Performance-Pack.Report', 'definition')
FAIL = []


def check(ok, msg):
    if not ok:
        FAIL.append(msg)


measures = {m['name']: m for m in M.MEAS}
columns = {(t['name'], c[0]) for t in M.TABLES for c in t.get('cols', [])}
tables = {t['name'] for t in M.TABLES}

# 1 every measure is documented and has one kind of format
for n, m in measures.items():
    check(bool(m.get('desc')), f'measure without description: {n}')
check(len(measures) == len(M.MEAS), 'duplicate measure names')

# 2 DAX variable names must not be DAX function names or keywords (broke measures twice: use, start, cos, top)
RESERVED = {'use', 'start', 'end', 'cos', 'sin', 'top', 'value', 'values', 'filter', 'all', 'sum', 'min', 'max', 'count', 'rank', 'date', 'time',
            'year', 'month', 'day', 'hour', 'now', 'today', 'left', 'right', 'mid', 'len', 'find', 'search', 'format', 'abs', 'round', 'int', 'trunc',
            'and', 'or', 'not', 'if', 'switch', 'true', 'false', 'blank', 'return', 'var', 'in', 'asc', 'desc', 'pi', 'exp', 'ln', 'log', 'sqrt',
            'power', 'mod', 'sign', 'even', 'odd', 'rand', 'path', 'row', 'union', 'except', 'error', 'concatenate', 'contains', 'divide', 'average',
            'median', 'product', 'related', 'calculate', 'earlier', 'earliest', 'first', 'last', 'next', 'previous', 'offset', 'index', 'window',
            'measure', 'column', 'table', 'define', 'evaluate', 'order', 'by', 'currency', 'boolean', 'double', 'integer', 'string', 'datetime'}
for n, m in measures.items():
    for v in re.findall(r'\bVAR\s+([A-Za-z_]\w*)', m['expr']):
        check(v.lower() not in RESERVED, f'measure {n}: reserved word used as VAR name: {v}')

# 3 measure references in DAX resolve ([Name] not preceded by a table name, not a VAR-table column like [@v])
for n, m in measures.items():
    code = re.sub(r'(//|--)[^\n]*', '', m['expr'])            # comments may mention measures by pattern ([Col ...])
    code = re.sub(r'"(?:[^"]|"")*"', '""', code)               # and so may string literals (SVG, sentences)
    for ref in re.findall(r"(?<![\w'\]])\[([^\]@][^\]]*)\]", code):
        ok = ref in measures or any(c == ref for _, c in columns) or ref in ('Value', 'Value1', 'Value2')
        check(ok, f'measure {n}: unknown reference [{ref}]')

# 4 every field used by a visual exists in the model
for vf in glob.glob(os.path.join(RP, 'pages', '*', 'visuals', '*', 'visual.json')):
    txt = open(vf, encoding='utf-8').read()
    for ent, prop in re.findall(r'"Measure": \{"Expression": \{"SourceRef": \{"Entity": "([^"]+)"\}\}, "Property": "([^"]+)"\}', txt):
        check(prop in measures, f'{os.path.relpath(vf, ROOT)}: unknown measure {prop}')
    for ent, prop in re.findall(r'"Column": \{"Expression": \{"SourceRef": \{"Entity": "([^"]+)"\}\}, "Property": "([^"]+)"\}', txt):
        check(ent in tables and ((ent, prop) in columns or ent in ('Data Dictionary',)), f'{os.path.relpath(vf, ROOT)}: unknown column {ent}[{prop}]')

# 5 TMDL: a dynamic format string comes after the plain properties and never together with a fixed one
tm = open(os.path.join(SM, 'tables', '_Measures.tmdl'), encoding='utf-8').read()
for block in re.split(r'\n\tmeasure ', tm)[1:]:
    name = block.split(' =', 1)[0]
    if 'formatStringDefinition' in block:
        check('formatString:' not in block, f'TMDL {name}: both formatString and formatStringDefinition')
        check(block.index('formatStringDefinition') > block.index('lineageTag'), f'TMDL {name}: formatStringDefinition before plain properties')

# 6 narrative rows unique, roles present
keys = [(r[0], r[1]) for r in M.STORY_ROWS]
check(len(keys) == len(set(keys)), 'duplicate Story (Page, Sort) rows')
for name, _ in getattr(M, 'ROLES', []):
    check(os.path.exists(os.path.join(SM, 'roles', f'{name}.tmdl')), f'missing role file {name}')

# 7 generated files are in sync with the scripts (the scripts are the source of truth, not Desktop's re-saves)
if '--no-build' not in sys.argv:
    subprocess.run([sys.executable, os.path.join(ROOT, 'scripts', 'build_pbip.py'), ROOT], check=True, capture_output=True)
    diff = subprocess.run(['git', 'status', '--porcelain', '--', 'CFO-Performance-Pack.SemanticModel', 'CFO-Performance-Pack.Report'],
                          cwd=ROOT, capture_output=True, text=True).stdout.strip()
    check(not diff, 'generated files differ from the scripts; run scripts/build_pbip.py and commit:\n' + diff[:800])

FAIL = [f for f in FAIL if f]
print(f'{len(measures)} measures, {len(M.TABLES)} tables checked')
if FAIL:
    print('FAILED (%d):' % len(FAIL)); print('\n'.join(' - ' + f for f in FAIL[:60])); sys.exit(1)
print('All checks passed.')
