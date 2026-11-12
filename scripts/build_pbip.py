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


REPO_URL = 'https://github.com/avixd/cfo-performance-pack'
FONT = 'DIN'
SERIES = dict(actual='#3E5C8A', outlook='#8DB3D9', budget='#9AA5B4', py='#B8C2CF', total='#3E5C8A', grid='#8A96A8')
HEADER_BG, HEADER_FG = '#1F3A5F', '#FFFFFF'   # table headers: readable on both themes

# Standard grid (1280 x 720). Left panel: filters. Header: title + insight subtitle, utilities top right.
# Content area: page content is authored on the original 1248 x 630 grid and rescaled into it.
PANEL_W = 200
CX, CY, CW, CH = 212, 76, 1052, 590            # content area
FOOT_Y = 676
SX, SY = CW / 1248, CH / 630


def T(name):          # theme colour (measure-driven)
    return mcolor('Col ' + name)


class Page:
    def __init__(self, pid, display, key):
        self.pid, self.display, self.key, self.visuals, self.z = pid, display, key, [], 0

    def add(self, key, vtype, x, y, w, h, roles=None, objects=None, title=None, sort=None, filters=None,
            background=True, container=None, subtitle=None, content=True, header=True):
        """content=True rescales coordinates from the authoring grid into the standard content area."""
        if content:
            x, y, w, h = CX + (x - 16) * SX, CY + (y - 74) * SY, w * SX, h * SY
        self.z += 1
        vid = hexid(self.pid, key)
        vco = {}
        if title is None:
            vco['title'] = [{'properties': {'show': L(False)}}]
        else:
            text = {'expr': mfield(title[1:])} if isinstance(title, str) and title.startswith('=') else L(title)
            vco['title'] = [{'properties': {'show': L(True), 'text': text, 'fontColor': T('Text'), 'fontFamily': L(FONT), 'fontSize': L(10.5)}}]
        if subtitle:
            vco['subTitle'] = [{'properties': {'show': L(True), 'text': {'expr': mfield(subtitle)}, 'fontColor': T('Muted'),
                                               'fontFamily': L(FONT), 'fontSize': L(8.5)}}]
        else:
            vco['subTitle'] = [{'properties': {'show': L(False)}}]
        if background:
            vco['background'] = [{'properties': {'show': L(True), 'color': T('Panel'), 'transparency': L(0)}}]
        else:
            vco['background'] = [{'properties': {'show': L(False)}}]
        if not header:
            vco['visualHeader'] = [{'properties': {'show': L(False)}}]
        if container:
            vco.update(container)
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
               'position': {'x': round(x, 1), 'y': round(y, 1), 'z': self.z * 1000, 'height': round(h, 1), 'width': round(w, 1), 'tabOrder': self.z * 1000},
               'visual': visual}
        if filters:
            doc['filterConfig'] = {'filters': filters}
        self.visuals.append(doc)
        return vid

    # ---------------------------------------------------------------- chrome
    def rect(self, key, x, y, w, h, colour):
        return self.add(key, 'shape', x, y, w, h, content=False, background=False, header=False,
                        objects={'shape': [{'properties': {'tileShape': L('rectangle')}}],
                                 'fill': [{'properties': {'show': L(True), 'fillColor': T(colour), 'transparency': L(0)}}],
                                 'outline': [{'properties': {'show': L(False)}}]})

    def textline(self, key, x, y, w, h, measure, size, colour='Text', content=False):
        obj = {'dataLabels': [{'properties': {'fontSize': L(size), 'color': T(colour), 'fontFamily': L(FONT)}}],
               'categoryLabels': [{'properties': {'show': L(False)}}],
               'card': [{'properties': {'barShow': L(False), 'outline': L('None'), 'cardBackground': T('Panel')}}]}
        return self.add(key, 'multiRowCard', x, y, w, h, roles={'Values': [measure]}, objects=obj, content=content, background=False, header=False)

    def button(self, key, x, y, w, h, label, link_type, url=None, tooltip=None):
        sel = {'id': 'default'}
        obj = {'icon': [{'properties': {'show': L(False)}, 'selector': sel}],
               'text': [{'properties': {'show': L(True), 'text': L(label), 'fontColor': T('Text'), 'fontFamily': L(FONT), 'fontSize': L(9)}, 'selector': sel}],
               'fill': [{'properties': {'show': L(True), 'fillColor': T('Button'), 'transparency': L(0)}, 'selector': sel}],
               'outline': [{'properties': {'show': L(True), 'lineColor': T('Line'), 'roundEdge': L(4)}, 'selector': sel}]}
        link = {'show': L(True), 'type': L(link_type)}
        if url:
            link['webUrl'] = L(url)
        if tooltip:
            link['tooltip'] = L(tooltip)
        return self.add(key, 'actionButton', x, y, w, h, objects=obj, content=False, background=False, header=False,
                        container={'visualLink': [{'properties': link}]})

    def slicer(self, key, x, y, w, h, spec, title, mode='Dropdown', single=False, horizontal=False, sync=None, content=False):
        obj = {'data': [{'properties': {'mode': L(mode)}}],
               'header': [{'properties': {'show': L(False)}}],
               'items': [{'properties': {'textSize': L(9), 'fontFamily': L(FONT), 'fontColor': solid('#1F2A37'), 'background': solid('#FFFFFF')}}],
               # singleSelect = "multi-select with CTRL" (off: plain clicks add to the selection); strictSingleSelect = single select
               'selection': [{'properties': {'singleSelect': L(False), 'strictSingleSelect': L(single), 'selectAllCheckboxEnabled': L(not single)}}]}
        if horizontal:
            obj['general'] = [{'properties': {'orientation': L(1)}}]
        vid = self.add(key, 'slicer', x, y, w, h, roles={'Values': [spec]}, objects=obj, background=False, content=content,
                       title=title, header=False,
                       container={'padding': [{'properties': {'top': L(0), 'bottom': L(0), 'left': L(4), 'right': L(4)}}]})
        if sync:  # same group name on every page = one selection shared across the report
            self.visuals[-1]['visual']['syncGroup'] = {'groupName': sync, 'fieldChanges': True, 'filterChanges': True}
        return vid

    def chrome(self, title_measure, subtitle_measure):
        """Standard frame shared by every page."""
        self.rect('bg', 0, 0, W, H, 'Page')
        self.rect('side', 0, 0, PANEL_W, H, 'Side')
        # brand
        self.textline('brand', 10, 8, PANEL_W - 16, 30, 'Brand', 12.5, 'Accent')
        # left filter panel, top to bottom
        y, sh = 46, 52
        for k, spec, ttl, mode, single, sync in [
                ('s_fy', 'Date[Fiscal Year]', 'Fiscal year', 'Dropdown', False, 'Fiscal Year'),
                ('s_m', 'Date[Month Name]', 'Month', 'Dropdown', False, 'Month Name'),
                ('s_p', 'Period View[View]', 'Period', 'Basic', True, 'View'),
                ('s_c', 'Reporting Currency[Currency]', 'Currency', 'Basic', True, 'Currency'),
                ('s_r', 'Entity[Region]', 'Region', 'Dropdown', False, 'Region'),
                ('s_e', 'Entity[EntityName]', 'Entity', 'Dropdown', False, 'Entity'),
                ('s_d', 'Department[DepartmentName]', 'Department', 'Dropdown', False, 'Department')]:
            self.slicer(k, 8, y, PANEL_W - 16, sh, spec, ttl, mode=mode, single=single, horizontal=(mode == 'Basic'), sync=sync)
            y += sh + 4
        self.button('reset', 8, y + 4, PANEL_W - 16, 28, 'Reset all filters', 'ClearAllSlicers', tooltip='Clear every slicer on every page')
        y += 40
        obj = {'dataLabels': [{'properties': {'fontSize': L(9), 'color': T('Text'), 'fontFamily': L(FONT)}}],
               'categoryLabels': [{'properties': {'show': L(True), 'fontSize': L(7.5), 'color': T('Muted'), 'fontFamily': L(FONT)}}],
               'card': [{'properties': {'barShow': L(True), 'barColor': T('Accent'), 'barWeight': L(2), 'outline': L('None'), 'cardBackground': T('Panel')}}]}
        self.add('ctx', 'multiRowCard', 8, y, PANEL_W - 16, FOOT_Y - y - 6, content=False, header=False, title='Current view',
                 roles={'Values': [('Ctx Period', 'Period'), ('Ctx Currency', 'Currency'), ('Ctx Region', 'Region'), ('Ctx Entity', 'Entity'),
                                   ('Ctx Department', 'Department')]}, objects=obj)
        # header
        self.textline('title', CX - 4, 4, 560, 34, title_measure, 17, 'Accent')
        self.textline('subtitle', CX - 4, 36, 560, 34, subtitle_measure, 9, 'Muted')
        # utilities, top right: greeting, issue/support links, theme toggle; page navigation underneath
        ux = 776
        self.textline('hello', ux, 6, 128, 26, 'Greeting', 9, 'Muted')
        self.button('issue', ux + 132, 6, 112, 26, 'Report an issue', 'WebUrl',
                    REPO_URL + '/issues/new?labels=bug&title=%5BReport%20issue%5D%20', 'Opens a GitHub issue for this report')
        self.button('support', ux + 248, 6, 112, 26, 'Request support', 'WebUrl',
                    REPO_URL + '/issues/new?labels=question&title=%5BSupport%5D%20', 'Ask a question about the report or model')
        self.slicer('s_theme', ux + 364, 4, 128, 30, 'Theme Mode[Mode]', None, mode='Basic', single=True, horizontal=True, sync='Theme')
        sel = {'id': 'default'}
        nav = {'text': [{'properties': {'fontColor': T('Text'), 'fontFamily': L(FONT), 'fontSize': L(8.5)}, 'selector': sel},
                        {'properties': {'fontColor': T('Selected Text')}, 'selector': {'id': 'selected'}}],
               'fill': [{'properties': {'show': L(True), 'fillColor': T('Button'), 'transparency': L(0)}, 'selector': sel},
                        {'properties': {'fillColor': T('Selected')}, 'selector': {'id': 'selected'}}],
               'outline': [{'properties': {'show': L(True), 'lineColor': T('Line'), 'roundEdge': L(4)}, 'selector': sel}]}
        self.add('nav', 'pageNavigator', ux, 38, CX + CW - ux, 28, objects=nav, content=False, background=False, header=False)
        # separators and footer
        self.rect('hdr_line', CX, 70, CW, 1, 'Line')
        self.rect('foot_line', CX, FOOT_Y, CW, 1, 'Line')
        self.textline('footer', CX - 4, FOOT_Y + 4, CW + 8, 36, f'Footer {self.key}', 7.5, 'Muted')

    # ---------------------------------------------------------------- content building blocks
    def table_objects(self, fields, size=9, wrap=False, colours=None):
        """Themed table formatting; colours = {queryRef: font-colour measure} for conditional text colour."""
        values = [{'properties': {'fontSize': L(size), 'fontFamily': L(FONT), 'wordWrap': L(wrap)}}]
        for f in fields:
            r = ref(f)
            values.append({'properties': {'fontColor': mcolor((colours or {}).get(r, 'Col Text')), 'backColor': T('Panel')}, 'selector': wildcard(r)})
        return {'values': values,
                'columnHeaders': [{'properties': {'fontSize': L(size), 'fontFamily': L(FONT), 'fontColor': solid(HEADER_FG), 'backColor': solid(HEADER_BG), 'wordWrap': L(True)}}],
                'total': [{'properties': {'totals': L(False)}}],
                'grid': [{'properties': {'rowPadding': L(3), 'gridHorizontal': L(True), 'gridHorizontalColor': solid(SERIES['grid']),
                                         'gridVertical': L(False), 'outlineColor': solid(SERIES['grid'])}}]}

    def story(self, key, x, y, w, h, page, title, subtitle):
        obj = self.table_objects(['Story[Section]', 'Story[Text]'], size=9.5, wrap=True)
        obj['columnWidth'] = [{'properties': {'value': L(96)}, 'selector': {'metadata': 'Story.Section'}},
                              {'properties': {'value': L(w * SX - 120)}, 'selector': {'metadata': 'Story.Text'}}]
        return self.add(key, 'tableEx', x, y, w, h, roles={'Values': [('Story[Section]', 'Topic'), ('Story[Text]', 'Detail')]},
                        objects=obj, title=title, subtitle=subtitle, sort=[('Story[Section]', 'Ascending')],
                        filters=[cat_filter(hexid(self.pid, key, 'f'), 'Story', 'Page', [page])])

    def insights(self, key, x, y, w, h, keys):
        obj = self.table_objects(['Insight[Topic]', 'Insight Text'], size=9.5, wrap=True)
        obj['columnWidth'] = [{'properties': {'value': L(100)}, 'selector': {'metadata': 'Insight.Topic'}},
                              {'properties': {'value': L(w * SX - 124)}, 'selector': {'metadata': '_Measures.Insight Text'}}]
        topics = {1: 'Growth quality', 2: 'Cost absorption', 3: 'Full-year outlook', 4: 'People cost'}
        return self.add(key, 'tableEx', x, y, w, h, roles={'Values': [('Insight[Topic]', 'Topic'), ('Insight Text', 'What the numbers say')]},
                        objects=obj, title='=VT Insights', subtitle='Sub Insights', sort=[('Insight[Topic]', 'Ascending')],
                        filters=[cat_filter(hexid(self.pid, key, 'f'), 'Insight', 'Topic', [topics[k] for k in keys])])

    def card(self, key, x, y, w, h, measure, label=None, size=20, colour='Text', colour_measure=None, label_size=8.5, content=True):
        lab = {'fontSize': L(size), 'fontFamily': L(FONT), 'color': mcolor(colour_measure) if colour_measure else T(colour)}
        if MEASURE_FMT.get(measure) == M.F:
            lab.update({'labelDisplayUnits': L(1000000), 'labelPrecision': L(1)})
        obj = {'labels': [{'properties': lab}],
               'categoryLabels': [{'properties': {'show': L(bool(label)), 'fontSize': L(label_size), 'fontFamily': L(FONT), 'color': T('Muted')}}],
               'wordWrap': [{'properties': {'show': L(True)}}]}
        return self.add(key, 'card', x, y, w, h, roles={'Values': [(measure, label)]}, objects=obj, content=content, header=False)

    def kpi(self, key, x, y, w, h, measure, label, sub=None, sub_colour=None):
        top = h - 30 if sub else h
        self.card(key, x, y, w, top, measure, label, size=19)
        if sub:
            self.card(key + '_sub', x, y + top, w, h - top, sub, None, size=8.5, colour='Muted', colour_measure=sub_colour)

    def axes(self, extra=None, value_axis=True, legend=True):
        o = {'categoryAxis': [{'properties': {'fontSize': L(8.5), 'fontFamily': L(FONT), 'labelColor': T('Muted')}}],
             'valueAxis': [{'properties': {'show': L(value_axis), 'fontSize': L(8), 'fontFamily': L(FONT), 'labelColor': T('Muted'),
                                           'labelDisplayUnits': L(1000000), 'gridlineShow': L(value_axis), 'gridlineColor': solid(SERIES['grid'])}}],
             'legend': [{'properties': {'show': L(legend), 'position': L('Top'), 'fontSize': L(8), 'fontFamily': L(FONT), 'labelColor': T('Muted')}}]}
        o.update(extra or {})
        return o

    def bars(self, key, x, y, w, h, category, value, colour_measure, title, subtitle, sort_desc=True):
        obj = self.axes({'dataPoint': [{'properties': {'fill': mcolor(colour_measure)}, 'selector': wildcard()}],
                         'labels': [{'properties': {'show': L(True), 'labelDisplayUnits': L(1000000), 'labelPrecision': L(1), 'fontSize': L(8),
                                                    'fontFamily': L(FONT), 'color': T('Text')}}]}, value_axis=False, legend=False)
        return self.add(key, 'clusteredBarChart', x, y, w, h, roles={'Category': [category], 'Y': [value]}, objects=obj, title=title,
                        subtitle=subtitle, sort=[(value, 'Descending' if sort_desc else 'Ascending')])

    def statement(self, key, x, y, w, h, statement, cols, var_colours, title, subtitle):
        fields = ['Report Line[LineName]'] + [m for m, _ in cols]
        obj = self.table_objects(fields, size=9)
        # row shading for subtotals/totals on every column (Goodly template look), conditional text colour for variances
        vals = obj['values'][:1]
        cmap = dict(var_colours)
        for f in fields:
            r = ref(f)
            vals.append({'properties': {'backColor': mcolor('Line Row Background'), 'fontColor': mcolor(cmap.get(f, 'Col Text'))}, 'selector': wildcard(r)})
        obj['values'] = vals
        obj['columnWidth'] = [{'properties': {'value': L(190)}, 'selector': {'metadata': 'Report Line.LineName'}}]
        return self.add(key, 'tableEx', x, y, w, h, roles={'Values': [('Report Line[LineName]', 'Line')] + cols},
                        objects=obj, title=title, subtitle=subtitle, sort=[('Report Line[LineName]', 'Ascending')],
                        filters=[cat_filter(hexid(self.pid, key, 'f'), 'Report Line', 'Statement', [statement])])

    def write(self, order_index):
        pdir = os.path.join(RP, 'definition', 'pages', self.pid)
        page = {'$schema': PAGE_SCHEMA, 'name': self.pid, 'displayName': self.display, 'displayOption': 'FitToPage', 'height': H, 'width': W,
                'objects': {'background': [{'properties': {'transparency': L(100)}}]}}
        write(os.path.join(pdir, 'page.json'), json.dumps(page, indent=2))
        for v in self.visuals:
            write(os.path.join(pdir, 'visuals', v['name'], 'visual.json'), json.dumps(v, indent=2, ensure_ascii=False))


# ============================================================== pages (content authored on the 1248 x 630 grid from x=16, y=74)
def combo(p, key, x, y, w, h, title, subtitle):
    obj = p.axes({'dataPoint': [{'properties': {'fill': solid(SERIES['actual'])}, 'selector': {'metadata': '_Measures.Metric Monthly Actual'}},
                                {'properties': {'fill': solid(SERIES['outlook'])}, 'selector': {'metadata': '_Measures.Metric Monthly Outlook'}},
                                {'properties': {'fill': solid(SERIES['budget'])}, 'selector': {'metadata': '_Measures.Metric Monthly Budget'}},
                                {'properties': {'fill': solid(SERIES['py'])}, 'selector': {'metadata': '_Measures.Metric Monthly Prior Year'}}],
                  'lineStyles': [{'properties': {'lineStyle': L('dashed'), 'strokeWidth': L(2)}, 'selector': {'metadata': '_Measures.Metric Monthly Budget'}},
                                 {'properties': {'lineStyle': L('dotted'), 'strokeWidth': L(2)}, 'selector': {'metadata': '_Measures.Metric Monthly Prior Year'}}]})
    return p.add(key, 'lineClusteredColumnComboChart', x, y, w, h,
                 roles={'Category': ['Date[Month Name]'],
                        'Y': [('Metric Monthly Actual', 'Actual'), ('Metric Monthly Outlook', 'Outlook (budget)')],
                        'Y2': [('Metric Monthly Budget', 'Budget'), ('Metric Monthly Prior Year', 'Prior year')]},
                 objects=obj, title=title, subtitle=subtitle, sort=[('Date[Month Name]', 'Ascending')])


def page_overview():
    p = Page('99445311384ca177b853', 'Overview', 'Overview')
    p.chrome('PT Overview', 'PS Overview')
    p.story('story', 16, 74, 400, 630, 'Overview', '=VT Story', 'Sub Story')
    x0, w4 = 428, 202
    for i, (m, lab, sub, col) in enumerate([
            ('Revenue', 'Net revenue', 'Revenue vs Budget Text', 'Revenue Var Color'),
            ('Organic Growth %', 'Organic growth', None, None),
            ('Revenue New Entities', 'New-entity revenue', None, None),
            ('Entities Reporting', 'Entities reporting', None, None)]):
        p.kpi(f'k{i}', x0 + i * (w4 + 10), 74, w4, 100, m, lab, sub, col)
    p.add('rev_fy', 'columnChart', 428, 186, 430, 300,
          roles={'Category': ['Date[Fiscal Year]'], 'Series': ['Entity[Region]'], 'Y': [('Revenue Actual (in context)', 'Net revenue')]},
          objects=p.axes({'labels': [{'properties': {'show': L(True), 'labelDisplayUnits': L(1000000), 'labelPrecision': L(1), 'fontSize': L(8),
                                                     'fontFamily': L(FONT), 'color': solid('#FFFFFF')}}]}, value_axis=False),
          title='=VT Revenue by FY', subtitle='Sub Revenue Mix', sort=[('Date[Fiscal Year]', 'Ascending')])
    fields = ['Entity[EntityName]', 'Entity[CurrencyCode]', 'Entity[Effective Ownership]', 'Entity Joined FY', 'Entity Budget Status', 'Revenue (M)']
    p.add('entities', 'tableEx', 870, 186, 394, 518,
          roles={'Values': [('Entity[EntityName]', 'Entity'), ('Entity[CurrencyCode]', 'Ccy'), ('Entity[Effective Ownership]', 'Group %'),
                            ('Entity Joined FY', 'Joined'), ('Entity Budget Status', 'Budget'), ('Revenue (M)', 'Revenue (M)')]},
          objects=p.table_objects(fields, colours={'_Measures.Entity Budget Status': 'Entity Budget Status Color'}),
          title='=VT Entities', subtitle='Sub Entities', sort=[('Entity Joined FY', 'Ascending')])
    p.insights('ins', 428, 498, 430, 206, [1, 3])
    return p


def page_executive():
    p = Page(hexid('page', 'exec'), 'Executive Summary', 'Executive')
    p.chrome('PT Executive', 'PS Executive')
    p.card('headline', 16, 74, 1248, 40, 'Headline', None, size=12, colour='Accent')
    tiles = [('Revenue', 'Net revenue', 'Revenue vs Budget Text', 'Revenue Var Color'),
             ('Gross Profit Margin %', 'Gross margin', 'Gross Margin Text', 'Gross Margin Var Color'),
             ('EBITDA', 'EBITDA', 'EBITDA vs Budget Text', 'EBITDA Var Color'),
             ('Net Income', 'Net income', 'Net Income vs Budget Text', 'Net Income Var Color'),
             ('Net Income Outlook FY', 'Full-year net income outlook', 'Net Income Outlook Gap Text', 'Net Income Outlook Gap Color'),
             ('Cash', 'Cash at month end', 'Cash Change Text', 'Cash Change Color')]
    w = (1248 - 5 * 10) / 6
    for i, (m, lab, sub, col) in enumerate(tiles):
        p.kpi(f'k{i}', 16 + i * (w + 10), 122, w, 100, m, lab, sub, col)
    wf = p.axes({'sentimentColors': [{'properties': {'increaseFill': T('Good'), 'decreaseFill': T('Bad'), 'totalFill': solid(SERIES['total'])}}],
                 'labels': [{'properties': {'show': L(True), 'labelDisplayUnits': L(1000000), 'labelPrecision': L(1), 'fontSize': L(8.5),
                                            'fontFamily': L(FONT), 'color': T('Text')}}]}, value_axis=False)
    p.add('wf_rev', 'waterfallChart', 16, 232, 404, 220, roles={'Category': ['Revenue Bridge[Step]'], 'Y': [('Revenue Bridge Value', 'Revenue growth')]},
          objects=wf, title='=Title Revenue Bridge', subtitle='Sub Revenue Bridge', sort=[('Revenue Bridge[Step]', 'Ascending')])
    p.add('wf_ebitda', 'waterfallChart', 430, 232, 404, 220, roles={'Category': ['EBITDA Bridge[Step]'], 'Y': [('EBITDA Bridge Value', 'EBITDA variance')]},
          objects=wf, title='=Title EBITDA Bridge', subtitle='Sub EBITDA Bridge', sort=[('EBITDA Bridge[Step]', 'Ascending')])
    p.insights('ins', 844, 232, 420, 220, [1, 2, 4])
    fields = ['Exception Rank Shown', 'Entity[EntityName]', 'Report Line[LineName]', 'Exception Actual', 'Exception Var', 'Exception Var %']
    p.add('exceptions', 'tableEx', 16, 462, 620, 242,
          roles={'Values': [('Exception Rank Shown', '#'), ('Entity[EntityName]', 'Entity'), ('Report Line[LineName]', 'P&L line'),
                            ('Exception Actual', 'Actual (K)'), ('Exception Var', 'Var (K)'), ('Exception Var %', 'Var %')]},
          objects=p.table_objects(fields, colours={'_Measures.Exception Var': 'Exception Color', '_Measures.Exception Var %': 'Exception Color'}),
          title='=VT Exceptions', subtitle='Sub Exceptions', sort=[('Exception Rank Shown', 'Ascending')],
          filters=[cat_filter(hexid(p.pid, 'exceptions', 'f'), 'Report Line', 'LineType', ['Detail']),
                   cat_filter(hexid(p.pid, 'exceptions', 'g'), 'Report Line', 'Statement', ['Income Statement'])])
    p.bars('by_entity', 646, 462, 618, 242, 'Entity[EntityName]', 'Metric Var vs Budget', 'Metric Var Color', '=VT Exec Entity', 'Sub Entity Variance')
    return p


def page_bva():
    p = Page(hexid('page', 'bva'), 'Budget vs Actual', 'BvA')
    p.chrome('PT BvA', 'Title BvA')
    p.slicer('s_metric', 16, 74, 640, 44, 'Metric[Metric]', None, mode='Basic', single=True, horizontal=True, content=True)
    tiles = [('Metric Actual', 'Actual', 'Metric Var Text', 'Metric Var Color'),
             ('Metric Budget', 'Budget', None, None),
             ('Metric PY', 'Prior year', 'Metric Growth Text', None),
             ('Metric Outlook FY', 'Full-year outlook', 'Metric Gap Text', 'Metric Gap Color')]
    w = (1248 - 3 * 10) / 4
    for i, (m, lab, sub, col) in enumerate(tiles):
        p.kpi(f'k{i}', 16 + i * (w + 10), 124, w, 96, m, lab, sub, col)
    combo(p, 'trend', 16, 230, 620, 258, '=Title BvA Trend', 'Sub Monthly')
    obj = p.axes({'dataPoint': [{'properties': {'fill': solid(SERIES['actual'])}, 'selector': {'metadata': '_Measures.Metric Cumulative Actual'}},
                                {'properties': {'fill': solid(SERIES['outlook'])}, 'selector': {'metadata': '_Measures.Metric Cumulative Outlook'}},
                                {'properties': {'fill': solid(SERIES['budget'])}, 'selector': {'metadata': '_Measures.Metric Cumulative Budget'}}],
                  'lineStyles': [{'properties': {'lineStyle': L('dashed')}, 'selector': {'metadata': '_Measures.Metric Cumulative Outlook'}},
                                 {'properties': {'lineStyle': L('dotted')}, 'selector': {'metadata': '_Measures.Metric Cumulative Budget'}},
                                 {'properties': {'strokeWidth': L(3)}, 'selector': {'metadata': '_Measures.Metric Cumulative Actual'}}]})
    p.add('cum', 'lineChart', 646, 230, 618, 258,
          roles={'Category': ['Date[Month Name]'],
                 'Y': [('Metric Cumulative Actual', 'Actual YTD'), ('Metric Cumulative Outlook', 'Outlook'), ('Metric Cumulative Budget', 'Budget')]},
          objects=obj, title='=Title BvA Outlook', subtitle='Sub Cumulative', sort=[('Date[Month Name]', 'Ascending')])
    p.bars('by_entity', 16, 498, 620, 206, 'Entity[EntityName]', 'Metric Var vs Budget', 'Metric Var Color', '=Title Variance by Entity', 'Sub Entity Variance')
    p.bars('by_dept', 646, 498, 618, 206, 'Department[DepartmentName]', 'Operating Expenses Var vs Budget', 'Operating Expenses Var Color',
           '=Title Variance by Department', 'Sub Department', sort_desc=False)
    return p


def page_income():
    p = Page(hexid('page', 'is'), 'Income Statement', 'IS')
    p.chrome('PT IS', 'PS IS')
    cols = [('Line Actual', 'Actual'), ('Line Budget', 'Budget'), ('Line Var vs Budget', 'Var'), ('Line Var % vs Budget', 'Var %'),
            ('Line Prior Year', 'Prior year'), ('Line Growth %', 'vs PY %'), ('Line % of Revenue', '% of rev'), ('Line Outlook FY', 'FY outlook'),
            ('Line Budget FY', 'FY budget')]
    p.statement('pl', 16, 74, 900, 630, 'Income Statement', cols,
                [('Line Var vs Budget', 'Line Var Color'), ('Line Var % vs Budget', 'Line Var Color'), ('Line Growth %', 'Line Growth Color')],
                '=VT PL', 'Sub PL')
    tiles = [('Gross Profit Margin %', 'Gross margin', 'Gross Margin Text', 'Gross Margin Var Color'),
             ('EBITDA Margin %', 'EBITDA margin', None, None),
             ('OpEx % of Revenue', 'Opex % of revenue', None, None),
             ('Salary Cost per Head', 'Salary cost per head', None, None)]
    for i, (m, lab, sub, col) in enumerate(tiles):
        p.kpi(f'k{i}', 926, 74 + i * 100, 338, 92, m, lab, sub, col)
    p.insights('ins', 926, 476, 338, 228, [2, 4])
    return p


def page_balance():
    p = Page(hexid('page', 'bs'), 'Balance Sheet & Cash', 'BS')
    p.chrome('PT BS', 'Sub Cash')
    cols = [('Line Closing Balance', 'Closing'), ('Line Prior Year-End Balance', 'Year end'), ('Line Balance Change', 'Change')]
    p.statement('bs', 16, 74, 600, 630, 'Balance Sheet', cols, [('Line Balance Change', 'Balance Change Color')], '=VT BS', 'Sub BS')
    tiles = [('Cash', 'Cash'), ('Current Ratio', 'Current ratio (x)'), ('Debt to Equity', 'Debt to equity (x)'), ('Cash Conversion Cycle (days)', 'Cash cycle (days)'),
             ('DSO (days)', 'Receivable days'), ('DIO (days)', 'Inventory days'), ('DPO (days)', 'Payable days'), ('DQ Balance Sheet Difference', 'Balance check')]
    w = (648 - 3 * 10) / 4
    for i, (m, lab) in enumerate(tiles):
        p.kpi(f'k{i}', 626 + (i % 4) * (w + 10), 74 + (i // 4) * 96, w, 88, m, lab)
    obj = p.axes({'dataPoint': [{'properties': {'fill': solid(SERIES['actual'])}, 'selector': {'metadata': '_Measures.Cash Balance (month)'}},
                                {'properties': {'fill': solid(SERIES['outlook'])}, 'selector': {'metadata': '_Measures.Working Capital (month)'}}],
                  'lineStyles': [{'properties': {'lineChartType': L('straight'), 'strokeWidth': L(2)}}]})
    obj['categoryAxis'][0]['properties']['axisType'] = L('Scalar')
    p.add('cash', 'lineChart', 626, 270, 638, 434,
          roles={'Category': ['Date[Month]'], 'Y': [('Cash Balance (month)', 'Cash'), ('Working Capital (month)', 'Trade working capital')]},
          objects=obj, title='=VT Cash', subtitle='Sub Cash Trend', sort=[('Date[Month]', 'Ascending')],
          filters=[cat_filter(hexid(p.pid, 'cash', 'f'), 'Date', 'IsClosed', ['true'])])
    return p


def page_dq():
    p = Page(hexid('page', 'dq'), 'Data Quality', 'DQ')
    p.chrome('PT DQ', 'PS DQ')
    tiles = [('DQ Files Loaded', 'Ledger files loaded'), ('DQ Duplicates Removed', 'Duplicates removed'),
             ('DQ Blank Departments Fixed', 'Blank depts fixed'), ('DQ Files With Schema Drift', 'Schema-drift files'),
             ('DQ Balance Sheet Difference', 'Balance-sheet diff'), ('DQ Rows Missing FX Rate', 'Rows missing FX'),
             ('DQ Accounts Missing From Chart', 'Unknown accounts'), ('DQ Synthetic Budget Share', 'Synthetic budget')]
    w = (1248 - 7 * 10) / 8
    for i, (m, lab) in enumerate(tiles):
        p.kpi(f'k{i}', 16 + i * (w + 10), 74, w, 88, m, lab)
    f1 = ['DQ Injection Log[Month]', 'DQ Injection Log[Issue]', 'DQ Injection Log[RowsAffected]', 'DQ Injection Log[Treatment]']
    o1 = p.table_objects(f1, wrap=True)
    o1['columnWidth'] = [{'properties': {'value': L(62)}, 'selector': {'metadata': 'DQ Injection Log.Month'}},
                         {'properties': {'value': L(126)}, 'selector': {'metadata': 'DQ Injection Log.Issue'}},
                         {'properties': {'value': L(40)}, 'selector': {'metadata': 'DQ Injection Log.RowsAffected'}},
                         {'properties': {'value': L(280)}, 'selector': {'metadata': 'DQ Injection Log.Treatment'}}]
    p.add('inj', 'tableEx', 16, 172, 620, 232,
          roles={'Values': [('DQ Injection Log[Month]', 'Month'), ('DQ Injection Log[Issue]', 'Issue injected'), ('DQ Injection Log[RowsAffected]', 'Rows'),
                            ('DQ Injection Log[Treatment]', 'How the model handles it')]},
          objects=o1, title='=VT DQ Injected', subtitle='Sub DQ Injected')
    f2 = ['DQ File Log[Folder]', 'DQ File Log[Name]', 'DQ File Log[RawRows]', 'DQ File Log[DuplicateRows]', 'DQ File Log[MissingDepartmentRows]', 'DQ File Log[SchemaDrift]']
    p.add('files', 'tableEx', 646, 172, 618, 532,
          roles={'Values': [('DQ File Log[Folder]', 'Folder'), ('DQ File Log[Name]', 'File'), ('DQ File Log[RawRows]', 'Rows'),
                            ('DQ File Log[DuplicateRows]', 'Duplicates'), ('DQ File Log[MissingDepartmentRows]', 'Blank dept'),
                            ('DQ File Log[SchemaDrift]', 'Schema drift')]},
          objects=p.table_objects(f2), title='=VT DQ Files', subtitle='Sub DQ Files', sort=[('DQ File Log[Name]', 'Ascending')])
    p.story('eda', 16, 414, 620, 290, 'DQ', '=VT EDA', 'Sub EDA')
    return p


THEME_NAME = 'CFO-Performance-Pack-Theme.json'


def theme():
    return {
        'name': 'CFO Performance Pack',
        'dataColors': [SERIES['actual'], '#2A9DB0', '#E0A33A', SERIES['outlook'], SERIES['budget'], '#5B6676', SERIES['py'], '#2E7D32', '#C0392B'],
        'foreground': '#1F2A37', 'background': '#FFFFFF', 'backgroundLight': '#F4F6F9', 'tableAccent': HEADER_BG,
        'good': '#2E7D32', 'bad': '#C0392B', 'neutral': SERIES['budget'],
        'textClasses': {'callout': {'fontSize': 19, 'fontFace': FONT, 'color': '#1F2A37'},
                        'title': {'fontSize': 10.5, 'fontFace': FONT, 'color': '#1F2A37'},
                        'header': {'fontSize': 10.5, 'fontFace': FONT, 'color': '#1F2A37'},
                        'label': {'fontSize': 9, 'fontFace': FONT, 'color': '#5B6676'},
                        'smallLabel': {'fontSize': 8, 'fontFace': FONT, 'color': '#5B6676'}},
        'visualStyles': {
            '*': {'*': {'border': [{'show': False}], 'dropShadow': [{'show': False}],
                        'title': [{'fontSize': 10.5, 'fontFamily': FONT}],
                        'padding': [{'top': 6, 'bottom': 6, 'left': 8, 'right': 8}]}},
            'page': {'*': {'outspace': [{'color': {'solid': {'color': '#5B6676'}}, 'transparency': 0}]}}}}


def prune(pages):
    """Remove report page/visual folders the generator no longer produces (IDs derive from names, so renamed or
    removed visuals would otherwise linger). Only touches <name>.Report/definition/pages."""
    import shutil
    pdir = os.path.join(RP, 'definition', 'pages')
    keep = {pg.pid: {v['name'] for v in pg.visuals} for pg in pages}
    removed = 0
    for d in os.listdir(pdir):
        full = os.path.join(pdir, d)
        if not os.path.isdir(full):
            continue
        if d not in keep:
            shutil.rmtree(full); removed += 1; continue
        vdir = os.path.join(full, 'visuals')
        for v in os.listdir(vdir) if os.path.isdir(vdir) else []:
            if v not in keep[d]:
                shutil.rmtree(os.path.join(vdir, v)); removed += 1
    print('pruned stale folders:', removed)


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
    prune(pages)
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
