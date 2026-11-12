"""Generate the CFO Performance Pack PBIP (TMDL semantic model + PBIR report) from code.

Usage:  python build_pbip.py <project_root> [--data-root "<path ending in \\data\\>"]

  * The semantic model is defined in model_def.py (tables, Power Query, DAX measures).
  * The report pages are defined below (layout, visuals, dynamic titles, colours).
  * If --data-root is omitted, the DataRoot value already in expressions.tmdl is kept,
    so the machine-specific path never has to appear in this script or in the repo.
  * Output overwrites the model and report definition files in place. Open the .pbip in
    Power BI Desktop afterwards and click Refresh.
Deterministic: object IDs are derived from names, so reruns produce identical files.
"""
import json, os, re, sys, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import model_def as M  # noqa: E402

ROOT = sys.argv[1]
NAME = 'CFO-Performance-Pack'
SM = os.path.join(ROOT, f'{NAME}.SemanticModel', 'definition')
RP = os.path.join(ROOT, f'{NAME}.Report')
NS = uuid.UUID('6f1c9a52-3e0b-4f7e-9a51-2b7d0c4e8a10')
PLACEHOLDER = '<YOUR-LOCAL-PATH>\\data\\'


def tag(*parts):
    return str(uuid.uuid5(NS, '/'.join(parts)))


def hexid(*parts):
    return uuid.uuid5(NS, '/'.join(parts)).hex[:20]


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\r\n') as fh:
        fh.write(text)


# ============================================================== TMDL
def q(name):
    return name if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) else "'" + name.replace("'", "''") + "'"


def expr_block(expr, indent):
    """Return ' = expr' for one-liners, or ' =' plus lines indented `indent` tabs."""
    expr = expr.strip('\n')
    if '\n' not in expr:
        return f' = {expr}', []
    return ' =', ['\t' * indent + ln for ln in expr.split('\n')]


def render_table(t):
    tn = t['name']
    L = []
    if t.get('desc'):
        L.append(f"/// {t['desc']}")
    L.append(f'table {q(tn)}')
    L.append(f'\tlineageTag: {tag(tn)}')
    if t.get('hidden'):
        L.append('\tisHidden')
    if tn == 'Date':
        L.append('\tdataCategory: Time')
    L.append('')
    if tn == '_Measures':
        for m in M.MEAS:
            if m.get('desc'):
                L.append(f"\t/// {m['desc']}")
            head, body = expr_block(m['expr'], 3)
            L.append(f"\tmeasure {q(m['name'])}{head}")
            L.extend(body)
            if m.get('fmt'):
                L.append(f"\t\tformatString: {m['fmt']}")
            L.append(f"\t\tdisplayFolder: {m['folder']}")
            L.append(f"\t\tlineageTag: {tag(tn, 'measure', m['name'])}")
            L.append('')
    calc_table = 'dax' in t
    for cn, dt, p in t['cols']:
        if p.get('desc'):
            L.append(f"\t/// {p['desc']}")
        if 'expr' in p:
            head, body = expr_block(p['expr'], 3)
            L.append(f'\tcolumn {q(cn)}{head}')
            L.extend(body)
        else:
            L.append(f'\tcolumn {q(cn)}')
            if not calc_table:
                L.append(f'\t\tdataType: {dt}')
        if p.get('hidden'):
            L.append('\t\tisHidden')
        if p.get('fmt'):
            L.append(f"\t\tformatString: {p['fmt']}")
        L.append(f"\t\tlineageTag: {tag(tn, 'column', cn)}")
        if dt in ('int64', 'double', 'dateTime', 'decimal'):
            L.append('\t\tsummarizeBy: none')
        if calc_table:
            L.append('\t\tisNameInferred')
            L.append(f'\t\tsourceColumn: [{cn}]')
        elif 'expr' not in p:
            L.append(f'\t\tsourceColumn: {cn}')
        if p.get('sortBy'):
            L.append(f"\t\tsortByColumn: {q(p['sortBy'])}")
        if dt == 'dateTime' and not calc_table and 'expr' not in p:
            L.append('')
            L.append('\t\tannotation UnderlyingDateTimeDataType = Date')
        L.append('')
    if calc_table:
        L.append(f'\tpartition {q(tn)} = calculated')
        L.append('\t\tmode: import')
        L.append('\t\tsource =')
        L.extend('\t\t\t\t' + ln for ln in t['dax'].split('\n'))
        L.append('')
    else:
        L.append(f'\tpartition {q(tn)} = m')
        L.append('\t\tmode: import')
        L.append('\t\tsource =')
        L.extend('\t\t\t\t' + ln for ln in t['m'].split('\n'))
        L.append('')
        L.append('\tannotation PBI_ResultType = Table')
        L.append('')
    return '\n'.join(L) + '\n'


def current_data_root():
    path = os.path.join(SM, 'expressions.tmdl')
    if os.path.exists(path):
        m = re.search(r'expression DataRoot = "(.*?)" meta', open(path, encoding='utf-8').read())
        if m:
            return m.group(1)
    return PLACEHOLDER


def render_expressions(data_root):
    def fn(name, desc, body):
        lines = [f'/// {desc}', f'expression {name} =']
        lines += ['\t\t' + ln for ln in body.split('\n')]
        lines += [f'\tlineageTag: {tag("expr", name)}', '', '\tannotation PBI_ResultType = Function', '']
        return lines
    L = ['/// Root folder holding reference/, actuals/, budget/, fx/ and inbox/. Change this one value to run the model on another machine.',
         f'expression DataRoot = "{data_root}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]',
         f'\tlineageTag: {tag("expr", "DataRoot")}', '', '\tannotation PBI_ResultType = Text', '']
    L += fn('fnReadCsv', 'Reads one UTF-8 CSV (subfolder of DataRoot, file name) through the single Folder.Files(DataRoot) source; blank strings become null.', M.FN_READ_CSV)
    L += fn('fnLoadLedgerFolder', 'Combines every GL_*.csv in a subfolder of DataRoot: columns matched by name (order and extra columns ignored), exact duplicate rows removed, blank department mapped to 0 "Unassigned". Adding or removing a file adds or removes a period.', M.FN_LOAD_LEDGER)
    return '\n'.join(L) + '\n'


def render_model():
    order = ['DataRoot', 'fnReadCsv', 'fnLoadLedgerFolder'] + [t['name'] for t in M.TABLES if 'm' in t]
    L = ['model Model', '\tculture: en-CA', '\tdefaultPowerBIDataSourceVersion: powerBI_V3', '\tsourceQueryCulture: en-CA',
         '\tvalueFilterBehavior: independent', '\tdiscourageImplicitMeasures', '\tdataAccessOptions', '\t\tlegacyRedirects', '\t\treturnErrorValuesAsNull', '',
         'annotation __PBI_TimeIntelligenceEnabled = 0', '',
         'annotation PBI_ProTooling = ["MCP-PBIModeling","DevMode"]', '',
         'annotation PBI_QueryOrder = ' + json.dumps(order, separators=(',', ':')), '']
    L += [f"ref table {q(t['name'])}" for t in M.TABLES]
    L += ['', 'ref cultureInfo en-CA', '']
    return '\n'.join(L) + '\n'


def render_relationships():
    L = []
    for ft, fc, tt, tc in M.RELATIONSHIPS:
        L += [f'relationship {ft}_{fc}_{tt}_{tc}', f'\tfromColumn: {q(ft)}.{q(fc)}', f'\ttoColumn: {q(tt)}.{q(tc)}', '']
    return '\n'.join(L) + '\n'


def build_model(data_root):
    write(os.path.join(SM, 'model.tmdl'), render_model())
    write(os.path.join(SM, 'expressions.tmdl'), render_expressions(data_root))
    write(os.path.join(SM, 'relationships.tmdl'), render_relationships())
    for t in M.TABLES:
        write(os.path.join(SM, 'tables', f"{t['name']}.tmdl"), render_table(t))


# ============================================================== PBIR helpers
VC_SCHEMA = 'https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.14.0/schema.json'
PAGE_SCHEMA = 'https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json'
W, H = 1280, 720
C = dict(navy='#1F3A5F', ink='#1F2A37', muted='#5B6676', actual='#2F3B4C', budget='#9AA5B4', py='#C9D0D9',
         outlook='#8DB3D9', good='#2E7D32', bad='#C0392B', line='#E3E7ED', panel='#FFFFFF', page='#F4F6F9')
MEASURE_NAMES = {m['name'] for m in M.MEAS}
MEASURE_FMT = {m['name']: m.get('fmt') for m in M.MEAS}
COLUMN_NAMES = {(t['name'], c[0]) for t in M.TABLES for c in t['cols']}


def L(v):
    if isinstance(v, bool):
        return {'expr': {'Literal': {'Value': 'true' if v else 'false'}}}
    if isinstance(v, (int, float)):
        return {'expr': {'Literal': {'Value': f'{v}D'}}}
    return {'expr': {'Literal': {'Value': "'" + str(v).replace("'", "''") + "'"}}}


def solid(hex_):
    return {'solid': {'color': L(hex_)}}


def mfield(name):
    assert name in MEASURE_NAMES, f'unknown measure {name}'
    return {'Measure': {'Expression': {'SourceRef': {'Entity': '_Measures'}}, 'Property': name}}


def cfield(table, col):
    assert (table, col) in COLUMN_NAMES, f'unknown column {table}[{col}]'
    return {'Column': {'Expression': {'SourceRef': {'Entity': table}}, 'Property': col}}


def mcolor(name):
    return {'solid': {'color': {'expr': mfield(name)}}}


def proj(f, display=None):
    if 'Measure' in f:
        ref = '_Measures.' + f['Measure']['Property']; native = f['Measure']['Property']
    else:
        ref = f"{f['Column']['Expression']['SourceRef']['Entity']}.{f['Column']['Property']}"; native = f['Column']['Property']
    p = {'field': f, 'queryRef': ref, 'nativeQueryRef': native}
    if display:
        p['displayName'] = display
    return p


def F(spec):
    """'Table[Col]' -> column field, otherwise measure field."""
    m = re.fullmatch(r'(.+)\[(.+)\]', spec)
    return cfield(m.group(1), m.group(2)) if m else mfield(spec)


def ref(spec):
    return proj(F(spec))['queryRef']


def wildcard(meta=None):
    s = {'data': [{'dataViewWildcard': {'matchingOption': 1}}]}
    if meta:
        s['metadata'] = meta
    return s


def cat_filter(name, table, col, values):
    vals = [[{'Literal': {'Value': v if v in ('true', 'false') else "'" + v + "'"}}] for v in values]
    return {'name': name, 'field': cfield(table, col), 'type': 'Categorical',
            'filter': {'Version': 2, 'From': [{'Name': 't', 'Entity': table, 'Type': 0}],
                       'Where': [{'Condition': {'In': {'Expressions': [{'Column': {'Expression': {'SourceRef': {'Source': 't'}}, 'Property': col}}],
                                                       'Values': vals}}}]},
            'howCreated': 'User'}


class Page:
    def __init__(self, pid, display):
        self.pid, self.display, self.visuals, self.z = pid, display, [], 0

    def add(self, key, vtype, x, y, w, h, roles=None, objects=None, title=None, sort=None, filters=None,
            background=True, container=None):
        self.z += 1
        vid = hexid(self.pid, key)
        vco = {}
        if title is None:
            vco['title'] = [{'properties': {'show': L(False)}}]
        else:
            text = {'expr': mfield(title[1:])} if isinstance(title, str) and title.startswith('=') else L(title)
            vco['title'] = [{'properties': {'show': L(True), 'text': text}}]
        vco['subTitle'] = [{'properties': {'show': L(False)}}]
        if not background:
            vco['background'] = [{'properties': {'show': L(False)}}]
        if container:
            for k, v in container.items():
                vco[k] = v
        visual = {'visualType': vtype}
        if roles:
            qs = {}
            for role, specs in roles.items():
                qs[role] = {'projections': [proj(F(s), d) for s, d in ((x_ if isinstance(x_, tuple) else (x_, None)) for x_ in specs)]}
            visual['query'] = {'queryState': qs}
            if sort:
                visual['query']['sortDefinition'] = {'sort': [{'field': F(s), 'direction': d} for s, d in sort], 'isDefaultSort': True}
        if objects:
            visual['objects'] = objects
        visual['visualContainerObjects'] = vco
        visual['drillFilterOtherVisuals'] = True
        doc = {'$schema': VC_SCHEMA, 'name': vid,
               'position': {'x': x, 'y': y, 'z': self.z * 1000, 'height': h, 'width': w, 'tabOrder': self.z * 1000},
               'visual': visual}
        if filters:
            doc['filterConfig'] = {'filters': filters}
        self.visuals.append(doc)
        return vid

    # ---- building blocks
    def text(self, key, x, y, w, h, paragraphs, background=False):
        """paragraphs: list of (text, size, bold, color) or list of lists of runs for mixed styling."""
        paras = []
        for p in paragraphs:
            runs = p if isinstance(p, list) else [p]
            tr = []
            for t, size, bold, color in runs:
                style = {'fontSize': f'{size}pt', 'color': color, 'fontFamily': 'Segoe UI Semibold' if bold else 'Segoe UI'}
                tr.append({'value': t, 'textStyle': style})
            paras.append({'textRuns': tr})
        return self.add(key, 'textbox', x, y, w, h, objects={'general': [{'properties': {'paragraphs': paras}}]}, background=background)

    def narrative(self, key, x, y, w, h, measures, size=10.5, color=C['ink'], title=None, bar=True, background=True):
        obj = {'dataLabels': [{'properties': {'fontSize': L(size), 'color': solid(color)}}],
               'categoryLabels': [{'properties': {'show': L(False)}}],
               'card': [{'properties': {'barShow': L(bar), 'barColor': solid(C['navy']), 'barWeight': L(3), 'outline': L('None')}}]}
        return self.add(key, 'multiRowCard', x, y, w, h, roles={'Values': measures}, objects=obj, title=title, background=background)

    def insights(self, key, x, y, w, h, keys, title):
        obj = {'values': [{'properties': {'fontSize': L(9.5), 'wordWrap': L(True), 'fontColor': solid(C['ink'])}}],
               'columnHeaders': [{'properties': {'fontSize': L(9), 'fontColor': solid('#FFFFFF'), 'backColor': solid(C['navy'])}}],
               'columnWidth': [{'properties': {'value': L(110)}, 'selector': {'metadata': 'Insight.Topic'}},
                               {'properties': {'value': L(w - 150)}, 'selector': {'metadata': '_Measures.Insight Text'}}],
               'total': [{'properties': {'totals': L(False)}}],
               'grid': [{'properties': {'rowPadding': L(3), 'gridHorizontal': L(True), 'gridHorizontalColor': solid(C['line'])}}]}
        topics = {1: 'Growth quality', 2: 'Cost absorption', 3: 'Full-year outlook'}
        return self.add(key, 'tableEx', x, y, w, h, roles={'Values': [('Insight[Topic]', 'Topic'), ('Insight Text', 'What the numbers say')]},
                        objects=obj, title=title, sort=[('Insight[Topic]', 'Ascending')],
                        filters=[cat_filter(hexid(self.pid, key, 'f'), 'Insight', 'Topic', [topics[k] for k in keys])])

    def card(self, key, x, y, w, h, measure, label=None, size=20, color=C['ink'], color_measure=None, label_size=9, background=True):
        lab = {'fontSize': L(size), 'color': mcolor(color_measure) if color_measure else solid(color)}
        if MEASURE_FMT.get(measure) == M.F:
            lab.update({'labelDisplayUnits': L(1000000), 'labelPrecision': L(1)})
        obj = {'labels': [{'properties': lab}],
               'categoryLabels': [{'properties': {'show': L(bool(label)), 'fontSize': L(label_size), 'color': solid(C['muted'])}}],
               'wordWrap': [{'properties': {'show': L(True)}}]}
        return self.add(key, 'card', x, y, w, h, roles={'Values': [(measure, label)]}, objects=obj, background=background)

    def kpi(self, key, x, y, w, h, measure, label, sub=None, sub_color=None):
        """Value card with its label, and an optional one-line comparison text underneath (coloured by a measure)."""
        top = h - 30 if sub else h
        self.card(key, x, y, w, top, measure, label, size=20)
        if sub:
            self.card(key + '_sub', x, y + top, w, h - top, sub, None, size=9, color_measure=sub_color, color=C['muted'])

    def slicer(self, key, x, y, w, h, spec, header, mode='Dropdown', single=False, horizontal=False, sync=None):
        obj = {'data': [{'properties': {'mode': L(mode)}}],
               'header': [{'properties': {'show': L(True), 'text': L(header), 'textSize': L(8), 'fontColor': solid(C['muted'])}}],
               'items': [{'properties': {'textSize': L(9)}}],
               'selection': [{'properties': {'singleSelect': L(single), 'strictSingleSelect': L(single)}}]}
        if horizontal:
            obj['general'] = [{'properties': {'orientation': L(1)}}]
        vid = self.add(key, 'slicer', x, y, w, h, roles={'Values': [spec]}, objects=obj, background=False)
        if sync:  # same group name on every page = one selection shared across the report
            self.visuals[-1]['visual']['syncGroup'] = {'groupName': sync, 'fieldChanges': True, 'filterChanges': True}
        return vid

    def header(self, title, subtitle_measure, metric=False):
        self.text('hdr', 12, 2, 620, 44, [(title, 18, True, C['navy'])])
        self.narrative('hdr_sub', 16, 40, 660, 38, [subtitle_measure], size=9.5, color=C['muted'], bar=False, background=False)
        self.slicer('s_fy', 680, 6, 96, 60, 'Date[Fiscal Year]', 'Fiscal year', sync='Fiscal Year')
        self.slicer('s_m', 780, 6, 84, 60, 'Date[Month Name]', 'Month', sync='Month Name')
        self.slicer('s_p', 868, 6, 250, 60, 'Period View[View]', 'Period', mode='Basic', single=True, horizontal=True, sync='View')
        self.slicer('s_c', 1122, 6, 146, 60, 'Reporting Currency[Currency]', 'Currency', mode='Basic', single=True, horizontal=True, sync='Currency')

    # ---- charts
    def bars(self, key, x, y, w, h, category, value, color_measure, title, sort_desc=True):
        obj = {'dataPoint': [{'properties': {'fill': mcolor(color_measure)}, 'selector': wildcard()}],
               'labels': [{'properties': {'show': L(True), 'labelDisplayUnits': L(1000000), 'labelPrecision': L(1), 'fontSize': L(8)}}],
               'valueAxis': [{'properties': {'show': L(False), 'gridlineShow': L(False)}}],
               'categoryAxis': [{'properties': {'fontSize': L(9)}}]}
        return self.add(key, 'clusteredBarChart', x, y, w, h, roles={'Category': [category], 'Y': [value]}, objects=obj, title=title,
                        sort=[(value, 'Descending')] if sort_desc else None)

    def write(self, order_index):
        pdir = os.path.join(RP, 'definition', 'pages', self.pid)
        write(os.path.join(pdir, 'page.json'), json.dumps({'$schema': PAGE_SCHEMA, 'name': self.pid, 'displayName': self.display,
                                                            'displayOption': 'FitToPage', 'height': H, 'width': W}, indent=2))
        for v in self.visuals:
            write(os.path.join(pdir, 'visuals', v['name'], 'visual.json'), json.dumps(v, indent=2, ensure_ascii=False))


# ============================================================== pages
def page_overview():
    p = Page('99445311384ca177b853', 'Company Overview')
    p.header('Adventure Works Group', 'Title Overview')
    T, B, I, N = C['ink'], C['navy'], C['muted'], C['navy']
    p.text('story', 16, 80, 400, 624, [
        ('Who we are', 13, True, N),
        ('Designs and sells performance bicycles, components and riding apparel through dealers and its own online store. '
         'Canadian parent: reports in CAD, fiscal year 1 April to 31 March (FY2027 ends 31 March 2027).', 10, False, T),
        ('', 6, False, T),
        ('Three years in brief', 13, True, N),
        [('FY2025  ', 10, True, T), ('North American core: five US divisions and Canada.', 10, False, T)],
        [('FY2026  ', 10, True, T), ('European entry: France (50%) and Germany (25%) joined in April 2025, after the budget was set. '
                                     'An ERP migration in August 2025 left 3% of postings without a department.', 10, False, T)],
        [('FY2027  ', 10, True, T), ('Pacific entry: an Australian joint venture (37.5% group interest) began trading in April 2026, again outside the budget. '
                                     'A new Software Subscriptions account opened as cloud tools replaced professional services; '
                                     'September 2026 was the first ledger exported from ERP v2.', 10, False, T)],
        ('', 6, False, T),
        ('The CFO\'s four questions', 13, True, N),
        [('1  Is growth organic or bought?  ', 10, True, T), ('Executive Summary', 10, False, I)],
        [('2  Is cost growth eating the upside?  ', 10, True, T), ('Income Statement', 10, False, I)],
        [('3  Where will the year land?  ', 10, True, T), ('Budget vs Actual', 10, False, I)],
        [('4  Is the balance sheet funding growth?  ', 10, True, T), ('Balance Sheet & Cash', 10, False, I)],
        ('', 6, False, T),
        ('Fictional company built on Microsoft\'s AdventureWorksDW sample (MIT licence), re-dated; FY2026-FY2028 budgets generated by a documented script.', 8, False, I),
    ], background=True)
    x0, w4 = 428, 202
    for i, (m, lab, sub, col) in enumerate([
            ('Revenue', 'Net revenue', 'Revenue vs Budget Text', 'Revenue Var Color'),
            ('Organic Growth %', 'Organic growth', None, None),
            ('Revenue New Entities', 'New-entity revenue', None, None),
            ('Entities Reporting', 'Entities reporting', None, None)]):
        p.kpi(f'k{i}', x0 + i * (w4 + 10), 80, w4, 96, m, lab, sub, col)
    p.add('rev_fy', 'columnChart', 428, 188, 430, 300,
          roles={'Category': ['Date[Fiscal Year]'], 'Series': ['Entity[Region]'], 'Y': [('Revenue Actual (in context)', 'Net revenue')]},
          objects={'labels': [{'properties': {'show': L(True), 'labelDisplayUnits': L(1000000), 'labelPrecision': L(1), 'fontSize': L(8)}}],
                   'valueAxis': [{'properties': {'show': L(False), 'gridlineShow': L(False)}}],
                   'legend': [{'properties': {'show': L(True), 'position': L('Top'), 'fontSize': L(8)}}]},
          title='=Title Overview Revenue', sort=[('Date[Fiscal Year]', 'Ascending')])
    p.add('entities', 'tableEx', 870, 188, 394, 516,
          roles={'Values': [('Entity[EntityName]', 'Entity'), ('Entity[CurrencyCode]', 'Ccy'),
                            ('Entity[Effective Ownership]', 'Group %'), ('Entity Joined FY', 'Joined'), ('Entity Budget Status', 'Budget'),
                            ('Revenue', 'Revenue')]},
          objects={'values': [{'properties': {'fontSize': L(8.5)}},
                              {'properties': {'fontColor': mcolor('Entity Budget Status Color')}, 'selector': {'data': [{'dataViewWildcard': {'matchingOption': 1}}], 'metadata': '_Measures.Entity Budget Status'}}],
                   'total': [{'properties': {'totals': L(False)}}],
                   'columnHeaders': [{'properties': {'fontSize': L(9), 'fontColor': solid('#FFFFFF'), 'backColor': solid(C['navy'])}}],
                   'grid': [{'properties': {'rowPadding': L(4), 'gridHorizontal': L(True), 'gridHorizontalColor': solid(C['line'])}}]},
          title='Group perimeter: who reports, since when, and who has a budget',
          sort=[('Entity Joined FY', 'Ascending')])
    p.insights('ins', 428, 500, 430, 204, [1, 3], 'What changed')
    return p


def page_executive():
    p = Page(hexid('page', 'exec'), 'Executive Summary')
    p.header('Executive Summary', 'Title Executive')
    p.card('headline', 16, 76, 1248, 44, 'Headline', None, size=13, color=C['navy'])
    tiles = [('Revenue', 'Net revenue', 'Revenue vs Budget Text', 'Revenue Var Color'),
             ('Gross Profit Margin %', 'Gross margin', 'Gross Margin Text', 'Gross Margin Var Color'),
             ('EBITDA', 'EBITDA', 'EBITDA vs Budget Text', 'EBITDA Var Color'),
             ('Net Income', 'Net income', 'Net Income vs Budget Text', 'Net Income Var Color'),
             ('Net Income Outlook FY', 'Full-year net income outlook', 'Net Income Outlook Gap Text', 'Net Income Outlook Gap Color'),
             ('Cash', 'Cash at month end', 'Cash Change Text', 'Cash Change Color')]
    w = (1248 - 5 * 10) / 6
    for i, (m, lab, sub, col) in enumerate(tiles):
        p.kpi(f'k{i}', 16 + i * (w + 10), 128, w, 100, m, lab, sub, col)
    wf = {'sentimentColors': [{'properties': {'increaseFill': solid(C['good']), 'decreaseFill': solid(C['bad']), 'totalFill': solid(C['navy'])}}],
          'labels': [{'properties': {'show': L(True), 'labelDisplayUnits': L(1000000), 'labelPrecision': L(1), 'fontSize': L(9)}}],
          'valueAxis': [{'properties': {'show': L(False), 'gridlineShow': L(False)}}],
          'categoryAxis': [{'properties': {'fontSize': L(9)}}]}
    p.add('wf_rev', 'waterfallChart', 16, 240, 404, 250, roles={'Category': ['Revenue Bridge[Step]'], 'Y': [('Revenue Bridge Value', 'Revenue growth')]},
          objects=wf, title='=Title Revenue Bridge', sort=[('Revenue Bridge[Step]', 'Ascending')])
    p.add('wf_ebitda', 'waterfallChart', 430, 240, 404, 250, roles={'Category': ['EBITDA Bridge[Step]'], 'Y': [('EBITDA Bridge Value', 'EBITDA variance')]},
          objects=wf, title='=Title EBITDA Bridge', sort=[('EBITDA Bridge[Step]', 'Ascending')])
    p.insights('ins', 844, 240, 420, 250, [1, 2, 3], 'What the CFO needs to know')
    combo(p, 'trend', 16, 500, 620, 204, 'Revenue by month: actual, outlook and budget')
    p.bars('by_entity', 646, 500, 618, 204, 'Entity[EntityName]', 'Metric Var vs Budget', 'Metric Var Color',
           'Revenue variance to budget by entity (unbudgeted entities show their full revenue)')
    return p


def combo(p, key, x, y, w, h, title):
    obj = {'dataPoint': [{'properties': {'fill': solid(C['actual'])}, 'selector': {'metadata': '_Measures.Metric Monthly Actual'}},
                         {'properties': {'fill': solid(C['outlook'])}, 'selector': {'metadata': '_Measures.Metric Monthly Outlook'}},
                         {'properties': {'fill': solid(C['budget'])}, 'selector': {'metadata': '_Measures.Metric Monthly Budget'}},
                         {'properties': {'fill': solid(C['py'])}, 'selector': {'metadata': '_Measures.Metric Monthly Prior Year'}}],
           'lineStyles': [{'properties': {'lineStyle': L('dashed'), 'strokeWidth': L(2)}, 'selector': {'metadata': '_Measures.Metric Monthly Budget'}},
                          {'properties': {'lineStyle': L('dotted'), 'strokeWidth': L(2)}, 'selector': {'metadata': '_Measures.Metric Monthly Prior Year'}}],
           'legend': [{'properties': {'show': L(True), 'position': L('Top'), 'fontSize': L(8)}}],
           'valueAxis': [{'properties': {'show': L(True), 'labelDisplayUnits': L(1000000), 'fontSize': L(8), 'gridlineShow': L(True), 'gridlineColor': solid(C['line'])}}],
           'categoryAxis': [{'properties': {'fontSize': L(9)}}]}
    return p.add(key, 'lineClusteredColumnComboChart', x, y, w, h,
                 roles={'Category': ['Date[Month Name]'],
                        'Y': [('Metric Monthly Actual', 'Actual'), ('Metric Monthly Outlook', 'Outlook (budget)')],
                        'Y2': [('Metric Monthly Budget', 'Budget'), ('Metric Monthly Prior Year', 'Prior year')]},
                 objects=obj, title=title if not title.startswith('=') else title, sort=[('Date[Month Name]', 'Ascending')])


def page_bva():
    p = Page(hexid('page', 'bva'), 'Budget vs Actual')
    p.header('Budget vs Actual', 'Title BvA')
    p.slicer('s_metric', 16, 74, 640, 50, 'Metric[Metric]', 'Measure analysed', mode='Basic', single=True, horizontal=True)
    tiles = [('Metric Actual', 'Actual', 'Metric Var Text', 'Metric Var Color'),
             ('Metric Budget', 'Budget', None, None),
             ('Metric PY', 'Prior year', 'Metric Growth Text', None),
             ('Metric Outlook FY', 'Full-year outlook', 'Metric Gap Text', 'Metric Gap Color')]
    w = (1248 - 3 * 10) / 4
    for i, (m, lab, sub, col) in enumerate(tiles):
        p.kpi(f'k{i}', 16 + i * (w + 10), 132, w, 96, m, lab, sub, col)
    combo(p, 'trend', 16, 238, 620, 250, '=Title BvA Trend')
    obj = {'dataPoint': [{'properties': {'fill': solid(C['actual'])}, 'selector': {'metadata': '_Measures.Metric Cumulative Actual'}},
                         {'properties': {'fill': solid(C['outlook'])}, 'selector': {'metadata': '_Measures.Metric Cumulative Outlook'}},
                         {'properties': {'fill': solid(C['budget'])}, 'selector': {'metadata': '_Measures.Metric Cumulative Budget'}}],
           'lineStyles': [{'properties': {'lineStyle': L('dashed')}, 'selector': {'metadata': '_Measures.Metric Cumulative Outlook'}},
                          {'properties': {'lineStyle': L('dotted')}, 'selector': {'metadata': '_Measures.Metric Cumulative Budget'}},
                          {'properties': {'strokeWidth': L(3)}, 'selector': {'metadata': '_Measures.Metric Cumulative Actual'}}],
           'legend': [{'properties': {'show': L(True), 'position': L('Top'), 'fontSize': L(8)}}],
           'valueAxis': [{'properties': {'labelDisplayUnits': L(1000000), 'fontSize': L(8), 'gridlineColor': solid(C['line'])}}],
           'categoryAxis': [{'properties': {'fontSize': L(9)}}]}
    p.add('cum', 'lineChart', 646, 238, 618, 250,
          roles={'Category': ['Date[Month Name]'],
                 'Y': [('Metric Cumulative Actual', 'Actual YTD'), ('Metric Cumulative Outlook', 'Outlook'), ('Metric Cumulative Budget', 'Budget')]},
          objects=obj, title='=Title BvA Outlook', sort=[('Date[Month Name]', 'Ascending')])
    p.bars('by_entity', 16, 498, 620, 206, 'Entity[EntityName]', 'Metric Var vs Budget', 'Metric Var Color', '=Title Variance by Entity')
    p.bars('by_dept', 646, 498, 618, 206, 'Department[DepartmentName]', 'Operating Expenses Var vs Budget', 'Operating Expenses Var Color', '=Title Variance by Department', sort_desc=False)
    return p


def statement_matrix(p, key, x, y, w, h, statement, cols, var_colors, title):
    values = []
    for m, d in cols:
        values.append({'properties': {'backColor': mcolor('Line Row Background')}, 'selector': wildcard('_Measures.' + m)})
    for m, cm in var_colors:
        values.append({'properties': {'fontColor': mcolor(cm)}, 'selector': wildcard('_Measures.' + m)})
    obj = {'values': [{'properties': {'fontSize': L(9.5)}}] + values,
           'rowHeaders': [{'properties': {'fontSize': L(9.5), 'fontColor': solid(C['ink'])}}],
           'columnHeaders': [{'properties': {'fontSize': L(9), 'fontColor': solid('#FFFFFF'), 'backColor': solid(C['navy']), 'alignment': L('Right')}}],
           'subTotals': [{'properties': {'rowSubtotals': L(False), 'columnSubtotals': L(False)}}],
           'grid': [{'properties': {'rowPadding': L(4), 'gridHorizontal': L(True), 'gridHorizontalColor': solid(C['line'])}}]}
    return p.add(key, 'pivotTable', x, y, w, h,
                 roles={'Rows': [('Report Line[LineName]', 'Line')], 'Values': cols},
                 objects=obj, title=title, sort=[('Report Line[LineName]', 'Ascending')],
                 filters=[cat_filter(hexid(p.pid, key, 'f'), 'Report Line', 'Statement', [statement])])


def page_income():
    p = Page(hexid('page', 'is'), 'Income Statement')
    p.header('Income Statement', 'Title Income Statement')
    cols = [('Line Actual', 'Actual'), ('Line Budget', 'Budget'), ('Line Var vs Budget', 'Var'), ('Line Var % vs Budget', 'Var %'),
            ('Line Prior Year', 'Prior year'), ('Line Growth %', 'vs PY %'), ('Line % of Revenue', '% of revenue'), ('Line Outlook FY', 'FY outlook'),
            ('Line Budget FY', 'FY budget')]
    statement_matrix(p, 'pl', 16, 76, 900, 628, 'Income Statement', cols,
                     [('Line Var vs Budget', 'Line Var Color'), ('Line Var % vs Budget', 'Line Var Color'), ('Line Growth %', 'Line Growth Color')],
                     'Management P&L (Goodly template: one row per report line, subtotals defined by account lists)')
    tiles = [('Gross Profit Margin %', 'Gross margin', 'Gross Margin Text', 'Gross Margin Var Color'),
             ('EBITDA Margin %', 'EBITDA margin', None, None),
             ('OpEx % of Revenue', 'Operating expenses % of revenue', None, None),
             ('Net Income Attributable to NCI', 'Net income to minority partners (NCI)', None, None)]
    for i, (m, lab, sub, col) in enumerate(tiles):
        p.kpi(f'k{i}', 926, 76 + i * 104, 338, 96, m, lab, sub, col)
    p.insights('ins', 926, 492, 338, 212, [2, 1], 'Reading the P&L')
    return p


def page_balance():
    p = Page(hexid('page', 'bs'), 'Balance Sheet & Cash')
    p.header('Balance Sheet & Cash', 'Title Balance Sheet')
    cols = [('Line Closing Balance', 'Closing'), ('Line Prior Year-End Balance', 'Prior year end'), ('Line Balance Change', 'Change')]
    statement_matrix(p, 'bs', 16, 76, 600, 628, 'Balance Sheet', cols, [], 'Consolidated balance sheet (month-end rates)')
    tiles = [('Cash', 'Cash'), ('Current Ratio', 'Current ratio (x)'), ('Debt to Equity', 'Debt to equity (x)'), ('Cash Conversion Cycle (days)', 'Cash conversion cycle (days)'),
             ('DSO (days)', 'Receivable days (DSO)'), ('DIO (days)', 'Inventory days (DIO)'), ('DPO (days)', 'Payable days (DPO)'), ('DQ Balance Sheet Difference', 'Assets - (liabilities + equity)')]
    w = (648 - 3 * 10) / 4
    for i, (m, lab) in enumerate(tiles):
        p.kpi(f'k{i}', 626 + (i % 4) * (w + 10), 76 + (i // 4) * 96, w, 88, m, lab)
    obj = {'dataPoint': [{'properties': {'fill': solid(C['navy'])}, 'selector': {'metadata': '_Measures.Cash Balance (month)'}},
                         {'properties': {'fill': solid(C['outlook'])}, 'selector': {'metadata': '_Measures.Working Capital (month)'}}],
           'legend': [{'properties': {'show': L(True), 'position': L('Top'), 'fontSize': L(8)}}],
           'valueAxis': [{'properties': {'labelDisplayUnits': L(1000000), 'fontSize': L(8), 'gridlineColor': solid(C['line'])}}],
           'categoryAxis': [{'properties': {'fontSize': L(8)}}]}
    p.add('cash', 'lineChart', 626, 272, 638, 432,
          roles={'Category': ['Date[Year Month]'], 'Y': [('Cash Balance (month)', 'Cash'), ('Working Capital (month)', 'Trade working capital')]},
          objects=obj, title='Cash and trade working capital by month end (closed months)', sort=[('Date[Year Month]', 'Ascending')],
          filters=[cat_filter(hexid(p.pid, 'cash', 'f'), 'Date', 'IsClosed', ['true'])])
    return p


def page_dq():
    p = Page(hexid('page', 'dq'), 'Data Quality')
    p.header('Data Quality & About', 'Title DQ')
    tiles = [('DQ Files Loaded', 'Ledger files loaded'), ('DQ Duplicates Removed', 'Duplicate rows removed'),
             ('DQ Blank Departments Fixed', 'Blank depts fixed'), ('DQ Files With Schema Drift', 'Files with schema drift'),
             ('DQ Balance Sheet Difference', 'Balance-sheet difference'), ('DQ Rows Missing FX Rate', 'Rows missing an FX rate'),
             ('DQ Accounts Missing From Chart', 'Accounts not in chart'), ('DQ Synthetic Budget Share', 'Synthetic budget rows')]
    w = (1248 - 7 * 10) / 8
    for i, (m, lab) in enumerate(tiles):
        p.kpi(f'k{i}', 16 + i * (w + 10), 76, w, 88, m, lab)
    tbl = {'values': [{'properties': {'fontSize': L(9)}}],
           'columnHeaders': [{'properties': {'fontSize': L(9), 'fontColor': solid('#FFFFFF'), 'backColor': solid(C['navy'])}}],
           'grid': [{'properties': {'rowPadding': L(3), 'gridHorizontalColor': solid(C['line'])}}]}
    p.add('inj', 'tableEx', 16, 174, 620, 210,
          roles={'Values': [('DQ Injection Log[Month]', 'Month'), ('DQ Injection Log[Issue]', 'Issue injected'), ('DQ Injection Log[RowsAffected]', 'Rows'),
                            ('DQ Injection Log[Treatment]', 'How the model handles it')]},
          objects=tbl, title='What the data generator deliberately broke (reconcile with the counts above)')
    p.add('files', 'tableEx', 646, 174, 618, 530,
          roles={'Values': [('DQ File Log[Folder]', 'Folder'), ('DQ File Log[Name]', 'File'), ('DQ File Log[RawRows]', 'Rows'),
                            ('DQ File Log[DuplicateRows]', 'Duplicates'), ('DQ File Log[MissingDepartmentRows]', 'Blank dept'),
                            ('DQ File Log[SchemaDrift]', 'Schema drift')]},
          objects=tbl, title='Every source file, profiled on each refresh', sort=[('DQ File Log[Name]', 'Ascending')])
    T, N, I = C['ink'], C['navy'], C['muted']
    p.text('eda', 16, 394, 620, 310, [
        ('What the exploratory analysis found (docs/eda/eda_report.md)', 12, True, N),
        [('Distribution  ', 10, True, T), ('Monthly group revenue is close to normal (Shapiro-Wilk p = 0.52); individual ledger lines are heavily right-skewed, '
                                           'so outliers are flagged with robust median/MAD z-scores, not mean and standard deviation.', 10, False, T)],
        [('Correlation  ', 10, True, T), ('Revenue and cost of sales move almost one-for-one (Spearman 0.94); operating expenses less so (0.66). '
                                          'Margin is therefore decided below gross profit.', 10, False, T)],
        [('Integrity  ', 10, True, T), ('Every injected issue was detected: 30 of 30 duplicates, 30 of 30 blank departments, 1 of 1 schema-drift file. '
                                        'The balance sheet balances in every month.', 10, False, T)],
        [('Benford  ', 10, True, T), ('First-digit distribution conforms (Nigrini MAD 0.0068, acceptable).', 10, False, T)],
        ('', 6, False, T),
        ('Assumptions: fiscal year April-March; P&L at monthly average rates, balance sheet at month-end rates, budget at the prior fiscal year\'s average rate '
         '(Bank of Canada). Adding a monthly file to data/actuals and refreshing moves the whole pack forward one month.', 9, False, I),
    ], background=True)
    return p


THEME_NAME = 'CFO-Performance-Pack-Theme.json'


def theme():
    return {
        'name': 'CFO Performance Pack',
        'dataColors': [C['navy'], '#2A7F8E', '#D98E04', C['outlook'], C['budget'], C['muted'], C['py'], C['good'], C['bad']],
        'foreground': C['ink'], 'background': '#FFFFFF', 'backgroundLight': C['page'], 'tableAccent': C['navy'],
        'good': C['good'], 'bad': C['bad'], 'neutral': C['budget'],
        'textClasses': {'callout': {'fontSize': 20, 'fontFace': 'Segoe UI Semibold', 'color': C['ink']},
                        'title': {'fontSize': 11, 'fontFace': 'Segoe UI Semibold', 'color': C['ink']},
                        'header': {'fontSize': 11, 'fontFace': 'Segoe UI Semibold', 'color': C['ink']},
                        'label': {'fontSize': 9, 'fontFace': 'Segoe UI', 'color': C['muted']}},
        'visualStyles': {
            '*': {'*': {'background': [{'show': True, 'color': {'solid': {'color': '#FFFFFF'}}, 'transparency': 0}],
                        'border': [{'show': False}], 'dropShadow': [{'show': False}],
                        'title': [{'fontSize': 10, 'fontColor': {'solid': {'color': C['ink']}}, 'fontFamily': 'Segoe UI Semibold'}],
                        'padding': [{'top': 6, 'bottom': 6, 'left': 8, 'right': 8}]}},
            'page': {'*': {'background': [{'color': {'solid': {'color': C['page']}}, 'transparency': 0}],
                           'outspace': [{'color': {'solid': {'color': C['page']}}, 'transparency': 0}]}}}}


def build_report():
    rdir = os.path.join(RP, 'definition')
    rep = json.load(open(os.path.join(rdir, 'report.json'), encoding='utf-8'))
    base = rep['themeCollection']['baseTheme']
    rep['themeCollection']['customTheme'] = {'name': THEME_NAME, 'reportVersionAtImport': base['reportVersionAtImport'], 'type': 'RegisteredResources'}
    rep['resourcePackages'] = [r for r in rep['resourcePackages'] if r['type'] != 'RegisteredResources']
    rep['resourcePackages'].append({'name': 'RegisteredResources', 'type': 'RegisteredResources',
                                    'items': [{'name': THEME_NAME, 'path': THEME_NAME, 'type': 'CustomTheme'}]})
    write(os.path.join(rdir, 'report.json'), json.dumps(rep, indent=2))
    write(os.path.join(RP, 'StaticResources', 'RegisteredResources', THEME_NAME), json.dumps(theme(), indent=2))
    pages = [page_overview(), page_executive(), page_bva(), page_income(), page_balance(), page_dq()]
    for i, pg in enumerate(pages):
        pg.write(i)
    write(os.path.join(rdir, 'pages', 'pages.json'), json.dumps({
        '$schema': 'https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json',
        'pageOrder': [pg.pid for pg in pages], 'activePageName': pages[0].pid}, indent=2))
    return pages


if __name__ == '__main__':
    dr = sys.argv[sys.argv.index('--data-root') + 1] if '--data-root' in sys.argv else current_data_root()
    build_model(dr)
    pages = build_report()
    print('model:', len(M.TABLES), 'tables,', len(M.MEAS), 'measures,', len(M.RELATIONSHIPS), 'relationships')
    print('report:', ', '.join(f'{pg.display} ({len(pg.visuals)})' for pg in pages))
    print('DataRoot:', 'kept from existing model' if '--data-root' not in sys.argv else 'set from argument', '| placeholder' if dr == PLACEHOLDER else '')
