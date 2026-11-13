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


WRITES = {'written': 0, 'unchanged': 0}


def write(path, text):
    """Write only when the content changed: keeps file-sync and Git churn (and sync locks) to the files that really differ."""
    data = text.replace('\r\n', '\n').replace('\n', '\r\n').encode('utf-8')
    if os.path.exists(path):
        with open(path, 'rb') as fh:
            if fh.read() == data:
                WRITES['unchanged'] += 1
                return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as fh:
        fh.write(data)
    WRITES['written'] += 1


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
            if m.get('cat'):
                L.append(f"\t\tdataCategory: {m['cat']}")
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
        if t.get('group'):
            L.append(f"\t\tqueryGroup: {q(t['group'])}")
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
        lines += [f'\tlineageTag: {tag("expr", name)}', f"\tqueryGroup: {q(M.QUERY_GROUPS[0])}", '', '\tannotation PBI_ResultType = Function', '']
        return lines
    L = ['/// Root folder holding reference/, actuals/, budget/, fx/ and inbox/. Change this one value to run the model on another machine.',
         f'expression DataRoot = "{data_root}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]',
         f'\tlineageTag: {tag("expr", "DataRoot")}', f"\tqueryGroup: {q(M.QUERY_GROUPS[0])}", '', '\tannotation PBI_ResultType = Text', '']
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
    for i, g in enumerate(M.QUERY_GROUPS):   # folders in the Power Query Queries pane
        L += [f'queryGroup {q(g)}', '', f'\tannotation PBI_QueryGroupOrder = {i}', '']
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
    # model-view layout: fact in the middle, dimensions around it, helper tables in rows below (positions in model_def.DIAGRAM)
    nodes = [{'location': {'x': x, 'y': y}, 'nodeIndex': name, 'nodeLineageTag': tag(name), 'size': {'height': h, 'width': w}, 'zIndex': i}
             for i, (name, (x, y, w, h)) in enumerate(M.DIAGRAM.items())]
    write(os.path.join(os.path.dirname(SM), 'diagramLayout.json'), json.dumps({
        'version': '1.1.0', 'diagrams': [{'ordinal': 0, 'scrollPosition': {'x': 0, 'y': 0}, 'nodes': nodes, 'name': 'All tables', 'zoomValue': 60,
                                          'pinKeyFieldsToTop': False, 'showExtraHeaderInfo': False, 'hideKeyFieldsWhenCollapsed': False, 'tablesLocked': False}],
        'selectedDiagram': 'All tables', 'defaultDiagram': 'All tables'}, indent=2))


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
PANEL_W = 196
CX, CY, CW, CH = 208, 92, 1060, 570            # content area
FOOT_Y = 670
DOCS_URL = 'https://github.com/avixd/cfo-performance-pack/blob/main/docs/01-semantic-model.md'
SX, SY = CW / 1248, CH / 630


def T(name):          # theme colour (measure-driven)
    return mcolor('Col ' + name)


class Page:
    def __init__(self, pid, display, key, hidden=False):
        self.pid, self.display, self.key, self.visuals, self.z, self.hidden = pid, display, key, [], 0, hidden

    def add(self, key, vtype, x, y, w, h, roles=None, objects=None, title=None, sort=None, filters=None,
            background=True, container=None, subtitle=None, content=True, header=True, title_colour='Title'):
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
            vco['title'] = [{'properties': {'show': L(True), 'text': text, 'fontColor': T(title_colour), 'fontSize': L(10.5), 'bold': L(True)}}]
        if subtitle:
            vco['subTitle'] = [{'properties': {'show': L(True), 'text': {'expr': mfield(subtitle)}, 'fontColor': T('Muted'), 'fontSize': L(8.5)}}]
        else:
            vco['subTitle'] = [{'properties': {'show': L(False)}}]
        if background:
            vco['background'] = [{'properties': {'show': L(True), 'color': T('Panel'), 'transparency': L(0)}}]
            vco['border'] = [{'properties': {'show': L(True), 'color': T('Line'), 'radius': L(10)}}]
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
        """Themed panel/line: an empty text box whose container background follows the theme (shape fills ignored fx)."""
        return self.add(key, 'textbox', x, y, w, h, content=False, background=False, header=False,
                        objects={'general': [{'properties': {'paragraphs': [{'textRuns': [{'value': ''}]}]}}]},
                        container={'background': [{'properties': {'show': L(True), 'color': T(colour), 'transparency': L(0)}}],
                                   'padding': [{'properties': {'top': L(0), 'bottom': L(0), 'left': L(0), 'right': L(0)}}]})

    def textline(self, key, x, y, w, h, measure, size, colour='Text', content=False, align='left', bold=False):
        """Dynamic text line: a transparent, action-less button whose text is a measure (left-aligned, themed)."""
        sel = {'id': 'default'}
        txt = {'text': {'expr': mfield(measure)}, 'fontColor': T(colour), 'fontSize': L(size), 'horizontalAlignment': L(align),
               'verticalAlignment': L('middle'), 'bold': L(bold), 'leftMargin': L(4), 'rightMargin': L(4), 'topMargin': L(0), 'bottomMargin': L(0)}
        obj = {'text': [{'properties': {'show': L(True)}}, {'properties': txt, 'selector': sel}],
               'icon': [{'properties': {'show': L(False)}}],
               'fill': [{'properties': {'show': L(False)}}],
               'outline': [{'properties': {'show': L(False)}}]}
        return self.add(key, 'actionButton', x, y, w, h, objects=obj, content=content, background=False, header=False)

    def button(self, key, x, y, w, h, label, link_type=None, url=None, tooltip=None, fill='Button', text='Text', outline='Line',
               size=8.5, align='center', page=None, round_=4, measure=None, content=False, bold=False, valign='middle'):
        sel = {'id': 'default'}
        txt = {'text': {'expr': mfield(measure)} if measure else L(label), 'fontColor': T(text), 'fontSize': L(size), 'horizontalAlignment': L(align),
               'bold': L(bold), 'leftMargin': L(6), 'rightMargin': L(4), 'topMargin': L(0), 'bottomMargin': L(0)}
        if valign:
            txt['verticalAlignment'] = L(valign)
        obj = {'icon': [{'properties': {'show': L(False)}}],
               'text': [{'properties': {'show': L(True)}}, {'properties': txt, 'selector': sel}],
               'fill': [{'properties': {'show': L(fill is not None)}}] + ([{'properties': {'fillColor': T(fill), 'transparency': L(0)}, 'selector': sel}] if fill else []),
               'outline': [{'properties': {'show': L(outline is not None)}}] + ([{'properties': {'lineColor': T(outline), 'roundEdge': L(round_)}, 'selector': sel}] if outline else [])}
        container = None
        if link_type:
            link = {'show': L(True), 'type': L(link_type)}
            if url:
                link['webUrl'] = L(url)
            if page:
                link['navigationSection'] = L(page)
            if tooltip:
                link['tooltip'] = L(tooltip)
            container = {'visualLink': [{'properties': link}]}
        return self.add(key, 'actionButton', x, y, w, h, objects=obj, content=content, background=False, header=False, container=container)

    def slicer(self, key, x, y, w, h, spec, title, mode='Dropdown', single=False, horizontal=False, sync=None, content=False):
        obj = {'data': [{'properties': {'mode': L(mode)}}],
               'header': [{'properties': {'show': L(False)}}],
               'items': [{'properties': {'textSize': L(9), 'fontColor': solid('#1F2A37'), 'background': solid('#FFFFFF')}}],
               # singleSelect = "multi-select with CTRL" (off: plain clicks add to the selection); strictSingleSelect = single select
               'selection': [{'properties': {'singleSelect': L(False), 'strictSingleSelect': L(single), 'selectAllCheckboxEnabled': L(not single)}}]}
        if horizontal:
            obj['general'] = [{'properties': {'orientation': L(1)}}]
        vid = self.add(key, 'slicer', x, y, w, h, roles={'Values': [spec]}, objects=obj, background=False, content=content,
                       title=title, header=False, title_colour='Sidebar Text',
                       container={'padding': [{'properties': {'top': L(0), 'bottom': L(0), 'left': L(4), 'right': L(4)}}]})
        if sync:  # same group name on every page = one selection shared across the report
            self.visuals[-1]['visual']['syncGroup'] = {'groupName': sync, 'fieldChanges': True, 'filterChanges': True}
        return vid

    def chrome(self, title_measure, subtitle_measure):
        """Standard frame shared by every page (reference layout: dark sidebar, header with chips, numbered footer)."""
        self.rect('bg', 0, 0, W, H, 'Page')
        self.rect('side', 0, 0, PANEL_W, H, 'Sidebar')
        self.textline('brand', 8, 10, PANEL_W - 16, 24, 'Brand', 11.5, 'Sidebar Text', bold=True)
        self.textline('brand2', 8, 32, PANEL_W - 16, 22, 'Brand Sub', 8.5, 'Sidebar Muted')
        # page navigation: one button per page, the current page highlighted
        y = 58
        for pid, name, glyph in PAGES_NAV:
            on = pid == self.pid
            self.button(f'nav_{pid}', 8, y, PANEL_W - 16, 22, f'{glyph}   {name}', 'PageNavigation', page=pid, fill='Sidebar Active' if on else 'Sidebar',
                        text='Sidebar Text' if on else 'Sidebar Muted', outline=None, size=8.5, align='left', bold=on, round_=6, valign='middle')
            y += 24
        self.textline('lbl_f', 8, y, PANEL_W - 16, 16, 'Lbl Filters', 7.5, 'Sidebar Muted', bold=True)
        y += 17
        for k, spec, ttl, mode, single, sync in [
                ('s_fy', 'Date[Fiscal Year]', 'Fiscal year', 'Dropdown', False, 'Fiscal Year'),
                ('s_m', 'Date[Month Name]', 'Month', 'Dropdown', False, 'Month Name'),
                ('s_p', 'Period View[View]', 'Period', 'Basic', True, 'View'),
                ('s_c', 'Reporting Currency[Currency]', 'Currency', 'Basic', True, 'Currency'),
                ('s_r', 'Entity[Region]', 'Region', 'Dropdown', False, 'Region'),
                ('s_e', 'Entity[EntityName]', 'Entity', 'Dropdown', False, 'Entity'),
                ('s_d', 'Department[DepartmentName]', 'Department', 'Dropdown', False, 'Department')]:
            hh = 54 if mode == 'Basic' else 59   # title row + one control row (dropdown boxes are taller than tiles)
            self.slicer(k, 6, y, PANEL_W - 12, hh, spec, ttl, mode=mode, single=single, horizontal=(mode == 'Basic'), sync=sync)
            y += hh + 1
        self.button('reset', 10, y + 1, PANEL_W - 20, 22, '\u21ba  Reset all filters', 'ClearAllSlicers', tooltip='Clear every slicer on every page',
                    fill='Sidebar Active', text='Sidebar Text', outline=None, round_=6)
        self.textline('tagline', 8, H - 21, PANEL_W - 16, 19, 'Tagline', 7.5, 'Sidebar Muted')
        # header: title, insight subtitle, filter chips + refresh stamp; utilities top right
        self.textline('title', CX - 4, 4, 540, 32, title_measure, 16, 'Title', bold=True)
        self.textline('subtitle', CX - 4, 34, 640, 22, subtitle_measure, 8.5, 'Muted')
        x = CX
        for k, wdt in [('Period', 132), ('Currency', 92), ('Region', 128), ('Entity', 128), ('Department', 150)]:
            self.button(f'chip_{k}', x, 58, wdt, 24, '', measure=f'Ctx Line {k}', fill='Accent Soft', text='Accent', outline=None, size=7.5, round_=12)
            x += wdt + 6
        ux = 744
        self.textline('hello', ux, 6, 112, 28, 'Greeting', 9, 'Muted', align='right')
        self.button('issue', ux + 116, 6, 104, 28, 'Report an issue', 'WebUrl',
                    REPO_URL + '/issues/new?labels=bug&title=%5BReport%20issue%5D%20', 'Opens a GitHub issue for this report')
        self.button('support', ux + 224, 6, 106, 28, 'Request support', 'WebUrl',
                    REPO_URL + '/issues/new?labels=question&title=%5BSupport%5D%20', 'Ask a question about the report or model')
        self.slicer('s_theme', ux + 334, 4, CX + CW - ux - 334, 32, 'Theme Mode[Mode]', None, mode='Basic', single=True, horizontal=True, sync='Theme')
        self.textline('refreshed', ux + 40, 36, CX + CW - ux - 40, 22, 'Last Refreshed', 7.5, 'Muted', align='right')
        self.rect('hdr_line', CX, 86, CW, 1, 'Line')
        # footer: numbered notes + page-specific source note
        self.rect('foot_line', CX, FOOT_Y, CW, 1, 'Line')
        self.textline('note1', CX - 4, FOOT_Y + 3, 520, 22, 'Footer Note 1', 7.5, 'Muted')
        self.textline('note2', CX - 4, FOOT_Y + 25, 520, 22, 'Footer Note 2', 7.5, 'Muted')
        self.button('footer', CX + 520, FOOT_Y + 3, CW - 520, 44, '', measure=f'Footer {self.key}', fill=None, text='Muted', outline=None, size=7, align='right')

    # ---------------------------------------------------------------- content building blocks
    def table_objects(self, fields, size=9, wrap=False, colours=None):
        """Themed table formatting; colours = {queryRef: font-colour measure} for conditional text colour."""
        values = [{'properties': {'fontSize': L(size), 'wordWrap': L(wrap)}}]
        for f in fields:
            r = ref(f)
            values.append({'properties': {'fontColor': mcolor((colours or {}).get(r, 'Col Text')), 'backColor': T('Panel')}, 'selector': wildcard(r)})
        return {'values': values,
                'columnHeaders': [{'properties': {'fontSize': L(size), 'fontColor': solid(HEADER_FG), 'backColor': solid(HEADER_BG), 'wordWrap': L(True)}}],
                'total': [{'properties': {'totals': L(False)}}],
                'grid': [{'properties': {'rowPadding': L(3), 'gridHorizontal': L(True), 'gridHorizontalColor': solid(SERIES['grid']),
                                         'gridVertical': L(False), 'outlineColor': solid(SERIES['grid'])}}]}

    def story(self, key, x, y, w, h, page, title, subtitle, size=9.5, head=('Topic', 'Detail')):
        obj = self.table_objects(['Story[Section]', 'Story[Text]'], size=size, wrap=True)
        obj['columnWidth'] = [{'properties': {'value': L(96)}, 'selector': {'metadata': 'Story.Section'}},
                              {'properties': {'value': L(w * SX - 120)}, 'selector': {'metadata': 'Story.Text'}}]
        return self.add(key, 'tableEx', x, y, w, h, roles={'Values': [('Story[Section]', head[0]), ('Story[Text]', head[1])]},
                        objects=obj, title=title, subtitle=subtitle, sort=[('Story[Section]', 'Ascending')],
                        filters=[cat_filter(hexid(self.pid, key, 'f'), 'Story', 'Page', [page])])

    def insights(self, key, x, y, w, h, keys):
        obj = self.table_objects(['Insight[Topic]', 'Insight Text'], size=9.5, wrap=True)
        obj['columnWidth'] = [{'properties': {'value': L(100)}, 'selector': {'metadata': 'Insight.Topic'}},
                              {'properties': {'value': L(w * SX - 124)}, 'selector': {'metadata': '_Measures.Insight Text'}}]
        topics = {1: 'Growth quality', 2: 'Cost absorption', 3: 'Full-year outlook', 4: 'People cost', 5: 'Currency effect'}
        return self.add(key, 'tableEx', x, y, w, h, roles={'Values': [('Insight[Topic]', 'Topic'), ('Insight Text', 'What the numbers say')]},
                        objects=obj, title='=VT Insights', subtitle='Sub Insights', sort=[('Insight[Topic]', 'Ascending')],
                        filters=[cat_filter(hexid(self.pid, key, 'f'), 'Insight', 'Topic', [topics[k] for k in keys])])

    def card(self, key, x, y, w, h, measure, label=None, size=20, colour='Text', colour_measure=None, label_size=8.5, content=True):
        lab = {'fontSize': L(size), 'color': mcolor(colour_measure) if colour_measure else T(colour)}
        if MEASURE_FMT.get(measure) == M.F:
            lab.update({'labelDisplayUnits': L(1000000), 'labelPrecision': L(1)})
        obj = {'labels': [{'properties': lab}],
               'categoryLabels': [{'properties': {'show': L(bool(label)), 'fontSize': L(label_size), 'color': T('Muted')}}],
               'wordWrap': [{'properties': {'show': L(True)}}]}
        return self.add(key, 'card', x, y, w, h, roles={'Values': [(measure, label)]}, objects=obj, content=content, header=False)

    def kpi(self, key, x, y, w, h, measure, label, sub=None, sub_colour=None):
        """Compact KPI tile (no icon, sparkline or pacing bar): same blocks, alignment and number format as kpi_full."""
        self.kpi_full(key, x, y, w, h, 'KV ' + measure, label, None, sub, sub_colour, doc_anchor=ANCHOR(FOLDER[measure]), desc=DESC.get(measure) or label)

    def kpi_full(self, key, x, y, w, h, value, label, glyph, sub=None, sub_colour=None, spark=None, prog_text=None, prog_bar=None, doc_anchor=None, desc=None):
        """Reference-style KPI card: icon circle, value, label (hover = definition, click = DAX), comparison, sparkline, progress to FY budget."""
        X = lambda v: CX + (v - 16) * SX
        Y = lambda v: CY + (v - 74) * SY
        x0, y0, w0, h0 = X(x), Y(y), w * SX, h * SY
        self.add(key + '_bg', 'textbox', x0, y0, w0, h0, content=False, header=False,
                 objects={'general': [{'properties': {'paragraphs': [{'textRuns': [{'value': ''}]}]}}]})
        ix = 36 if glyph else 6          # compact tiles have no icon, so the text starts at the panel edge
        if glyph:
            self.button(key + '_ic', x0 + 8, y0 + 9, 26, 26, glyph, fill='Accent Soft', text='Accent', outline=None, size=10, round_=13, bold=True)
        self.button(key + '_v', x0 + ix, y0 + 6, 92 if spark else (w0 - ix - 6), 30, '', measure=value, fill=None, text='Title', outline=None, size=14, align='left', bold=True)
        self.button(key + '_l', x0 + ix, y0 + 34, w0 - ix - 6, 20, label + '  \u24d8', 'WebUrl', url=DOCS_URL + (doc_anchor or ''),
                    tooltip=(desc or label)[:250], fill=None, text='Muted', outline=None, size=8, align='left')
        if sub:
            self.button(key + '_s', x0 + (4 if glyph else ix - 2), y0 + 56, w0 - 8, 22, '', measure=sub, fill=None, text='Muted', outline=None, size=7.5, align='left')
            if sub_colour:
                self.visuals[-1]['visual']['objects']['text'][1]['properties']['fontColor'] = mcolor(sub_colour)
        if spark:
            self.image(key + '_sp', x0 + 130, y0 + 9, w0 - 140, 24, spark)
        if prog_text:
            self.button(key + '_pt', x0 + 4, y0 + h0 - 36, w0 - 8, 20, '', measure=prog_text, fill=None, text='Muted', outline=None, size=7, align='left')
        if prog_bar:
            self.image(key + '_pb', x0 + 10, y0 + h0 - 16, w0 - 20, 10, prog_bar)

    def image(self, key, x, y, w, h, measure):
        """Image visual bound to an SVG measure (dataCategory ImageUrl)."""
        obj = {'image': [{'properties': {'sourceType': L('imageData'), 'sourceField': {'expr': mfield(measure)}}}],
               'imageScaling': [{'properties': {'imageScalingType': L('Fit')}}]}
        return self.add(key, 'image', x, y, w, h, objects=obj, content=False, background=False, header=False,
                        container={'padding': [{'properties': {'top': L(0), 'bottom': L(0), 'left': L(0), 'right': L(0)}}]})

    def axes(self, extra=None, value_axis=True, legend=True):
        o = {'categoryAxis': [{'properties': {'fontSize': L(8.5), 'labelColor': T('Muted')}}],
             'valueAxis': [{'properties': {'show': L(value_axis), 'fontSize': L(8), 'labelColor': T('Muted'),
                                           'labelDisplayUnits': L(1000000), 'gridlineShow': L(value_axis), 'gridlineColor': solid(SERIES['grid'])}}],
             'legend': [{'properties': {'show': L(legend), 'position': L('Top'), 'fontSize': L(8), 'labelColor': T('Muted')}}]}
        o.update(extra or {})
        return o

    def bars(self, key, x, y, w, h, category, value, colour_measure, title, subtitle, sort_desc=True):
        obj = self.axes({'dataPoint': [{'properties': {'fill': mcolor(colour_measure)}, 'selector': wildcard()}],
                         'labels': [{'properties': {'show': L(True), 'labelDisplayUnits': L(1000000), 'labelPrecision': L(1), 'fontSize': L(8), 'color': T('Text')}}]}, value_axis=False, legend=False)
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
        if self.hidden:   # reachable in Desktop and through navigation, not shown as a tab to report readers
            page['visibility'] = 'HiddenInViewMode'
        write(os.path.join(pdir, 'page.json'), json.dumps(page, indent=2))
        for v in self.visuals:
            write(os.path.join(pdir, 'visuals', v['name'], 'visual.json'), json.dumps(v, indent=2, ensure_ascii=False))


# ============================================================== pages (content authored on the 1248 x 630 grid from x=16, y=74)
# Visible tabs are numbered in reading order; hidden analysis pages carry an H prefix. docs/03-page-guide.md uses the same numbers.
PAGES_NAV = [('99445311384ca177b853', '1  Overview', '\u2302'), (hexid('page', 'exec'), '2  Executive', '\u25c6'),
             (hexid('page', 'bva'), '3  Budget vs Actual', '\u25a4'), (hexid('page', 'is'), '4  P&L', '\u2261'),
             (hexid('page', 'bs'), '5  Balance Sheet', '\u25a5'), (hexid('page', 'dq'), '6  Data Quality', '\u2713'),
             (hexid('page', 'dd'), '7  Data Dictionary', '\u2637'), (hexid('page', 'notes'), '8  Notes', '\u2139')]
TAB = {pid: name.replace('  ', ' · ', 1) for pid, name, _ in PAGES_NAV}     # tab captions: "1 · Overview"
DESC = {m['name']: m.get('desc') for m in M.MEAS}
ANCHOR = lambda folder: '#' + re.sub(r'[^a-z0-9 -]', '', folder.lower()).replace(' ', '-')
FOLDER = {m['name']: m['folder'] for m in M.MEAS}


def full(p, key, x, y, w, h, measure, label, glyph, sub=None, sub_colour=None, spark=None, prog=None, bar=None):
    p.kpi_full(key, x, y, w, h, 'KV ' + measure, label, glyph, sub, sub_colour, spark, prog, bar,
               doc_anchor=ANCHOR(FOLDER[measure]), desc=DESC.get(measure) or label)
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
    p = Page('99445311384ca177b853', TAB['99445311384ca177b853'], 'Overview')
    p.chrome('PT Overview', 'PS Overview')
    p.story('story', 16, 74, 400, 630, 'Overview', '=VT Story', 'Sub Story')
    x0, w4 = 428, 202
    full(p, 'k0', x0, 74, w4, 136, 'Revenue', 'Net revenue', '$', 'Revenue vs Budget Text', 'Revenue Var Color', 'SVG Spark Revenue', 'Revenue Progress Text', 'SVG Bar Revenue')
    full(p, 'k1', x0 + (w4 + 10), 74, w4, 136, 'Organic Growth %', 'Organic growth', '\u2197', 'Revenue Growth Short', 'Revenue Growth Color')
    full(p, 'k2', x0 + 2 * (w4 + 10), 74, w4, 136, 'Revenue New Entities', 'New-entity revenue', '+', 'Entity Budget Status Summary')
    full(p, 'k3', x0 + 3 * (w4 + 10), 74, w4, 136, 'Entities Reporting', 'Entities reporting', '#', 'Sub Entities Short')
    p.add('rev_fy', 'columnChart', 428, 220, 430, 270,
          roles={'Category': ['Date[Fiscal Year]'], 'Series': ['Entity[Region]'], 'Y': [('Revenue Actual (in context)', 'Net revenue')]},
          objects=p.axes({'labels': [{'properties': {'show': L(True), 'labelDisplayUnits': L(1000000), 'labelPrecision': L(1), 'fontSize': L(8), 'color': solid('#FFFFFF')}}]}, value_axis=False),
          title='=VT Revenue by FY', subtitle='Sub Revenue Mix', sort=[('Date[Fiscal Year]', 'Ascending')])
    fields = ['Entity[EntityName]', 'Entity[CurrencyCode]', 'Entity[Effective Ownership]', 'Entity Joined FY', 'Entity Budget Status', 'Revenue (M)']
    p.add('entities', 'tableEx', 870, 220, 394, 484,
          roles={'Values': [('Entity[EntityName]', 'Entity'), ('Entity[CurrencyCode]', 'Ccy'), ('Entity[Effective Ownership]', 'Group %'),
                            ('Entity Joined FY', 'Joined'), ('Entity Budget Status', 'Budget'), ('Revenue (M)', 'Revenue (M)')]},
          objects=dict(p.table_objects(fields, colours={'_Measures.Entity Budget Status': 'Entity Budget Status Color'}),
                       columnWidth=[{'properties': {'value': L(112)}, 'selector': {'metadata': 'Entity.EntityName'}},
                                    {'properties': {'value': L(34)}, 'selector': {'metadata': 'Entity.CurrencyCode'}},
                                    {'properties': {'value': L(48)}, 'selector': {'metadata': 'Entity.Effective Ownership'}},
                                    {'properties': {'value': L(48)}, 'selector': {'metadata': '_Measures.Entity Joined FY'}},
                                    {'properties': {'value': L(92)}, 'selector': {'metadata': '_Measures.Entity Budget Status'}}]),
          title='=VT Entities', subtitle='Sub Entities', sort=[('Entity Joined FY', 'Ascending')])
    p.insights('ins', 428, 498, 430, 206, [1, 3])
    return p


def page_executive():
    p = Page(hexid('page', 'exec'), TAB[hexid('page', 'exec')], 'Executive')
    p.chrome('PT Executive', 'PS Executive')
    p.card('headline', 16, 74, 1248, 40, 'Headline', None, size=12, colour='Accent')
    w = (1248 - 5 * 10) / 6
    tiles = [('Revenue', 'Net revenue', '$', 'Revenue vs Budget Text', 'Revenue Var Color', 'SVG Spark Revenue', 'Revenue Progress Text', 'SVG Bar Revenue'),
             ('Gross Profit Margin %', 'Gross margin', '%', 'Gross Margin Text', 'Gross Margin Var Color', 'SVG Spark Gross Margin', 'Gross Margin Progress Text', None),
             ('EBITDA', 'EBITDA', '\u03a3', 'EBITDA vs Budget Text', 'EBITDA Var Color', 'SVG Spark EBITDA', 'EBITDA Progress Text', 'SVG Bar EBITDA'),
             ('Net Income', 'Net income', '\u25c6', 'Net Income vs Budget Text', 'Net Income Var Color', 'SVG Spark Net Income', 'Net Income Progress Text', 'SVG Bar Net Income'),
             ('Net Income Outlook FY', 'FY net income outlook', '\u2197', 'Net Income Outlook Gap Text', 'Net Income Outlook Gap Color', None, 'Net Income Outlook Progress Text', 'SVG Bar Net Income Outlook'),
             ('Cash', 'Cash at month end', '\u00a4', 'Cash Change Text', 'Cash Change Color', 'SVG Spark Cash', 'Cash Progress Text', None)]
    for i, t in enumerate(tiles):
        full(p, f'k{i}', 16 + i * (w + 10), 120, w, 136, *t)
    wf = p.axes({'sentimentColors': [{'properties': {'increaseFill': T('Good'), 'decreaseFill': T('Bad'), 'totalFill': solid(SERIES['total'])}}],
                 'labels': [{'properties': {'show': L(True), 'labelDisplayUnits': L(1000000), 'labelPrecision': L(1), 'fontSize': L(8.5), 'color': T('Text')}}]}, value_axis=False)
    p.add('wf_rev', 'waterfallChart', 16, 266, 404, 190, roles={'Category': ['Revenue Bridge[Step]'], 'Y': [('Revenue Bridge Value', 'Revenue growth')]},
          objects=wf, title='=Title Revenue Bridge', subtitle='Sub Revenue Bridge', sort=[('Revenue Bridge[Step]', 'Ascending')])
    p.add('wf_ebitda', 'waterfallChart', 430, 266, 404, 190, roles={'Category': ['EBITDA Bridge[Step]'], 'Y': [('EBITDA Bridge Value', 'EBITDA variance')]},
          objects=wf, title='=Title EBITDA Bridge', subtitle='Sub EBITDA Bridge', sort=[('EBITDA Bridge[Step]', 'Ascending')])
    p.insights('ins', 844, 266, 420, 190, [1, 2, 5])
    fields = ['Exception Rank Shown', 'Entity[EntityName]', 'Report Line[LineName]', 'Exception Actual', 'Exception Var', 'Exception Var %']
    p.add('exceptions', 'tableEx', 16, 466, 620, 238,
          roles={'Values': [('Exception Rank Shown', '#'), ('Entity[EntityName]', 'Entity'), ('Report Line[LineName]', 'P&L line'),
                            ('Exception Actual', 'Actual (K)'), ('Exception Var', 'Var (K)'), ('Exception Var %', 'Var %')]},
          objects=p.table_objects(fields, colours={'_Measures.Exception Var': 'Exception Color', '_Measures.Exception Var %': 'Exception Color'}),
          title='=VT Exceptions', subtitle='Sub Exceptions', sort=[('Exception Rank Shown', 'Ascending')],
          filters=[cat_filter(hexid(p.pid, 'exceptions', 'f'), 'Report Line', 'LineType', ['Detail']),
                   cat_filter(hexid(p.pid, 'exceptions', 'g'), 'Report Line', 'Statement', ['Income Statement'])])
    p.bars('by_entity', 646, 466, 618, 238, 'Entity[EntityName]', 'Metric Var vs Budget', 'Metric Var Color', '=VT Exec Entity', 'Sub Entity Variance')
    return p


def page_bva():
    p = Page(hexid('page', 'bva'), TAB[hexid('page', 'bva')], 'BvA')
    p.chrome('PT BvA', 'Title BvA')
    p.slicer('s_metric', 16, 74, 640, 44, 'Metric[Metric]', None, mode='Basic', single=True, horizontal=True, content=True)
    w = (1248 - 3 * 10) / 4
    tiles = [('Metric Actual', 'Actual', '$', 'Metric Var Text', 'Metric Var Color', 'SVG Spark Metric', 'Metric Progress Text', 'SVG Bar Metric'),
             ('Metric Budget', 'Budget', '\u25a4', 'Metric Budget FY Text', None, 'SVG Spark Metric Budget', None, None),
             ('Metric PY', 'Prior year', '\u21ba', 'Metric Growth Text', 'Metric Growth Color', 'SVG Spark Metric PY', None, None),
             ('Metric Outlook FY', 'Full-year outlook', '\u2197', 'Metric Gap Text', 'Metric Gap Color', None, 'Metric Outlook Progress Text', 'SVG Bar Metric Outlook')]
    for i, t in enumerate(tiles):
        full(p, f'k{i}', 16 + i * (w + 10), 124, w, 132, *t)
    combo(p, 'trend', 16, 264, 620, 226, '=Title BvA Trend', 'Sub Monthly')
    obj = p.axes({'dataPoint': [{'properties': {'fill': solid(SERIES['actual'])}, 'selector': {'metadata': '_Measures.Metric Cumulative Actual'}},
                                {'properties': {'fill': solid(SERIES['outlook'])}, 'selector': {'metadata': '_Measures.Metric Cumulative Outlook'}},
                                {'properties': {'fill': solid(SERIES['budget'])}, 'selector': {'metadata': '_Measures.Metric Cumulative Budget'}}],
                  'lineStyles': [{'properties': {'lineStyle': L('dashed')}, 'selector': {'metadata': '_Measures.Metric Cumulative Outlook'}},
                                 {'properties': {'lineStyle': L('dotted')}, 'selector': {'metadata': '_Measures.Metric Cumulative Budget'}},
                                 {'properties': {'strokeWidth': L(3)}, 'selector': {'metadata': '_Measures.Metric Cumulative Actual'}}]})
    p.add('cum', 'lineChart', 646, 264, 618, 226,
          roles={'Category': ['Date[Month Name]'],
                 'Y': [('Metric Cumulative Actual', 'Actual YTD'), ('Metric Cumulative Outlook', 'Outlook'), ('Metric Cumulative Budget', 'Budget')]},
          objects=obj, title='=Title BvA Outlook', subtitle='Sub Cumulative', sort=[('Date[Month Name]', 'Ascending')])
    p.bars('by_entity', 16, 498, 620, 206, 'Entity[EntityName]', 'Metric Var vs Budget', 'Metric Var Color', '=Title Variance by Entity', 'Sub Entity Variance')
    p.bars('by_dept', 646, 498, 618, 206, 'Department[DepartmentName]', 'Operating Expenses Var vs Budget', 'Operating Expenses Var Color',
           '=Title Variance by Department', 'Sub Department', sort_desc=False)
    return p


def page_income():
    p = Page(hexid('page', 'is'), TAB[hexid('page', 'is')], 'IS')
    p.chrome('PT IS', 'PS IS')
    cols = [('Line Actual', 'Actual'), ('Line Budget', 'Budget'), ('Line Var vs Budget', 'Var'), ('Line Var % vs Budget', 'Var %'),
            ('Line Prior Year', 'Prior year'), ('Line Growth %', 'vs PY %'), ('Line % of Revenue', '% of rev'), ('Line Outlook FY', 'FY outlook'),
            ('Line Budget FY', 'FY budget')]
    p.statement('pl', 16, 74, 900, 630, 'Income Statement', cols,
                [('Line Var vs Budget', 'Line Var Color'), ('Line Var % vs Budget', 'Line Var Color'), ('Line Growth %', 'Line Growth Color')],
                '=VT PL', 'Sub PL')
    tiles = [('Gross Profit Margin %', 'Gross margin', 'Gross Margin Text', 'Gross Margin Var Color'),
             ('EBITDA Margin %', 'EBITDA margin', 'EBITDA Margin Text', 'EBITDA Margin Var Color'),
             ('OpEx % of Revenue', 'Opex % of revenue', 'OpEx Ratio Text', 'OpEx Ratio Var Color'),
             ('Salary Cost per Head', 'Salary cost per head', 'Salary per Head Text', 'Salary per Head Color'),
             ('Net Income Attributable to Group', 'Net income attributable to the group', 'NCI Text', None)]
    for i, (m, lab, sub, col) in enumerate(tiles):
        p.kpi(f'k{i}', 926, 74 + i * 94, 338, 86, m, lab, sub, col)
    p.insights('ins', 926, 544, 338, 160, [2, 4])
    return p


def page_balance():
    p = Page(hexid('page', 'bs'), TAB[hexid('page', 'bs')], 'BS')
    p.chrome('PT BS', 'Sub Cash')
    cols = [('Line Closing Balance', 'Closing'), ('Line Prior Year-End Balance', 'Year end'), ('Line Balance Change', 'Change')]
    p.statement('bs', 16, 74, 600, 630, 'Balance Sheet', cols, [('Line Balance Change', 'Balance Change Color')], '=VT BS', 'Sub BS')
    tiles = [('Cash', 'Cash', 'Cash Change Text', 'Cash Change Color'), ('Current Ratio', 'Current ratio', 'Current Ratio Change Text', 'Current Ratio Change Color'),
             ('Debt to Equity', 'Debt to equity', 'Debt to Equity Change Text', 'Debt to Equity Change Color'),
             ('Cash Conversion Cycle (days)', 'Cash cycle (days)', 'CCC Change Text', 'CCC Change Color'),
             ('DSO (days)', 'Receivable days', 'DSO Change Text', 'DSO Change Color'), ('DIO (days)', 'Inventory days', 'DIO Change Text', 'DIO Change Color'),
             ('DPO (days)', 'Payable days', 'DPO Change Text', 'DPO Change Color'),
             ('DQ Balance Sheet Difference', 'Balance check', 'Balance Check Text', 'Balance Check Color')]
    w = (648 - 3 * 10) / 4
    for i, (m, lab, sub, col) in enumerate(tiles):
        p.kpi(f'k{i}', 626 + (i % 4) * (w + 10), 74 + (i // 4) * 98, w, 90, m, lab, sub, col)
    # cash bridge: green = source of cash, red = use of cash; the total is the change in cash since the year end
    wf = p.axes({'sentimentColors': [{'properties': {'increaseFill': T('Good'), 'decreaseFill': T('Bad'), 'totalFill': solid(SERIES['total'])}}],
                 'labels': [{'properties': {'show': L(True), 'labelDisplayUnits': L(1000000), 'labelPrecision': L(1), 'fontSize': L(8.5), 'color': T('Text')}}]}, value_axis=False, legend=False)
    p.add('cash_bridge', 'waterfallChart', 626, 272, 638, 212, roles={'Category': ['Cash Bridge[Step]'], 'Y': [('Cash Bridge Value', 'Cash effect')]},
          objects=wf, title='=VT Cash Bridge', subtitle='Sub Cash Bridge', sort=[('Cash Bridge[Step]', 'Ascending')])
    obj = p.axes({'dataPoint': [{'properties': {'fill': solid(SERIES['actual'])}, 'selector': {'metadata': '_Measures.Cash Balance (month)'}},
                                {'properties': {'fill': solid(SERIES['outlook'])}, 'selector': {'metadata': '_Measures.Working Capital (month)'}}],
                  'lineStyles': [{'properties': {'lineChartType': L('straight'), 'strokeWidth': L(2)}}]})
    obj['categoryAxis'][0]['properties']['axisType'] = L('Scalar')
    p.add('cash', 'lineChart', 626, 494, 638, 210,
          roles={'Category': ['Date[Month]'], 'Y': [('Cash Balance (month)', 'Cash'), ('Working Capital (month)', 'Trade working capital')]},
          objects=obj, title='=VT Cash', subtitle='Sub Cash Trend', sort=[('Date[Month]', 'Ascending')],
          filters=[cat_filter(hexid(p.pid, 'cash', 'f'), 'Date', 'IsClosed', ['true'])])
    return p


def page_dq():
    p = Page(hexid('page', 'dq'), TAB[hexid('page', 'dq')], 'DQ')
    p.chrome('PT DQ', 'PS DQ')
    tiles = [('DQ Files Loaded', 'Ledger files loaded', None, None), ('DQ Duplicates Removed', 'Duplicates removed', None, None),
             ('DQ Blank Departments Fixed', 'Blank depts fixed', None, None), ('DQ Files With Schema Drift', 'Schema-drift files', None, None),
             ('DQ Balance Sheet Difference', 'Balance-sheet diff', 'Balance Check Text', 'Balance Check Color'),
             ('DQ Rows Missing FX Rate', 'Rows missing FX', 'FX Check Text', 'FX Check Color'),
             ('DQ Accounts Missing From Chart', 'Unknown accounts', 'Chart Check Text', 'Chart Check Color'), ('DQ Synthetic Budget Share', 'Synthetic budget', None, None)]
    w = (1248 - 7 * 10) / 8
    for i, (m, lab, sub, col) in enumerate(tiles):
        p.kpi(f'k{i}', 16 + i * (w + 10), 74, w, 88, m, lab, sub, col)
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


def page_notes():
    """Assumptions, policies and definitions: what a reader must know before quoting a number from any page."""
    p = Page(hexid('page', 'notes'), TAB[hexid('page', 'notes')], 'Notes')
    p.chrome('PT Notes', 'PS Notes')
    p.story('notes', 16, 74, 800, 630, 'Notes', '=VT Notes', 'Sub Notes', size=8.5, head=('Topic', 'Assumption or policy'))
    p.story('defs', 826, 74, 438, 630, 'Defs', '=VT Defs', 'Sub Defs', size=8.5, head=('Metric', 'Definition'))
    return p


def cslicer(p, key, x, y, w, h, spec, title, mode='Dropdown', single=False, horizontal=False, search=False, sort=None):
    """Slicer inside the content area (page-specific filters), styled as a panel. search=True adds the slicer's own search box."""
    obj = {'data': [{'properties': {'mode': L(mode)}}], 'header': [{'properties': {'show': L(False)}}],
           'items': [{'properties': {'textSize': L(9), 'fontColor': solid('#1F2A37'), 'background': solid('#FFFFFF')}}],
           'selection': [{'properties': {'singleSelect': L(False), 'strictSingleSelect': L(single), 'selectAllCheckboxEnabled': L(not single)}}],
           'general': [{'properties': dict({'orientation': L(1)} if horizontal else {}, **({'selfFilterEnabled': L(True)} if search else {}))}]}
    return p.add(key, 'slicer', x, y, w, h, roles={'Values': [spec]}, objects=obj, title=title, header=False, sort=sort,
                 container={'padding': [{'properties': {'top': L(2), 'bottom': L(2), 'left': L(6), 'right': L(6)}}]})


def matrix_objects(p, value_fields, size=8.5, back=None, colours=None):
    """Themed matrix formatting; back / colours = {field: measure} for conditional cell background / font colour."""
    obj = p.table_objects(value_fields, size=size, colours=colours)
    if back:
        for v in obj['values'][1:]:
            m = back.get(v['selector']['metadata'])
            if m:
                v['properties']['backColor'] = mcolor(m)
                v['selector'] = {'data': [{'dataViewWildcard': {'matchingOption': 0}}], 'metadata': v['selector']['metadata']}   # 0 = cells and totals
    del obj['total']
    obj['rowHeaders'] = [{'properties': {'fontSize': L(size), 'fontColor': T('Text'), 'backColor': T('Panel'), 'wordWrap': L(False), 'showExpandCollapseButtons': L(True)}}]
    return obj


def page_dictionary():
    """Tab 7: the model described by the model. One calculated table unions INFO.VIEW.TABLES/COLUMNS/MEASURES/RELATIONSHIPS."""
    pid = hexid('page', 'dd')
    p = Page(pid, TAB[pid], 'DD')
    p.chrome('PT DD', 'PS DD')
    w = (1248 - 3 * 10) / 4
    for i, (m, lab) in enumerate([('DD Tables', 'Tables'), ('DD Columns', 'Columns'), ('DD Measures', 'Measures'), ('DD Relationships', 'Relationships')]):
        p.kpi(f'k{i}', 16 + i * (w + 10), 74, w, 74, m, lab)
    # page-specific slicers: tiles, searchable dropdowns and a free-text "contains" search
    cslicer(p, 'f_type', 16, 156, 330, 66, 'Data Dictionary[Object Type]', 'Object type', mode='Basic', horizontal=True)
    cslicer(p, 'f_table', 356, 156, 210, 66, 'Data Dictionary[Table]', 'Table (type to search)', search=True)
    cslicer(p, 'f_folder', 576, 156, 250, 66, 'Data Dictionary[Folder]', 'Display folder (type to search)', search=True)
    cslicer(p, 'f_name', 836, 156, 210, 66, 'Data Dictionary[Name]', 'Name (type to search)', search=True)
    p.add('f_text', 'textSlicer', 1056, 156, 208, 66, roles={'Values': ['Data Dictionary[Name]']}, title='Name contains (free text)', header=False)
    fields = ['Data Dictionary[Object Type]', 'Data Dictionary[Table]', 'Data Dictionary[Name]', 'Data Dictionary[Description]', 'Data Dictionary[Expression]',
              'Data Dictionary[Folder]']
    obj = p.table_objects(fields, size=8.5, wrap=True)
    obj['columnWidth'] = [{'properties': {'value': L(wd)}, 'selector': {'metadata': 'Data Dictionary.' + c}}
                          for c, wd in (('Object Type', 76), ('Table', 96), ('Name', 170), ('Description', 250), ('Expression', 330), ('Folder', 110))]
    p.add('dict', 'tableEx', 16, 230, 1248, 474, roles={'Values': [(f, f.split('[')[1][:-1]) for f in fields]}, objects=obj, title='=VT DD', subtitle='Sub DD',
          sort=[('Data Dictionary[Object Type]', 'Ascending')])
    return p


def page_sankey():
    """Hidden H1: income-statement Sankey drawn by one DAX measure (SVG), so no custom visual has to be installed."""
    p = Page(hexid('page', 'sankey'), 'H1 · Revenue Flow (Sankey)', 'Sankey', hidden=True)
    p.chrome('PT Sankey', 'PS Sankey')
    p.add('sankey', 'image', 16, 74, 1248, 516, title='=VT Sankey', subtitle='Sub Sankey', header=False,
          objects={'image': [{'properties': {'sourceType': L('imageData'), 'sourceField': {'expr': mfield('SVG Sankey')}}}],
                   'imageScaling': [{'properties': {'imageScalingType': L('Fit')}}]})
    w = (1248 - 3 * 10) / 4
    for i, (m, lab, sub, col) in enumerate([('Revenue', 'Net revenue', 'Revenue vs Budget Text', 'Revenue Var Color'), ('Gross Profit Margin %', 'Gross margin', 'Gross Margin Text', 'Gross Margin Var Color'),
                                            ('EBITDA', 'EBITDA', 'EBITDA vs Budget Text', 'EBITDA Var Color'), ('Net Income', 'Net income', 'Net Income vs Budget Text', 'Net Income Var Color')]):
        p.kpi(f'k{i}', 16 + i * (w + 10), 600, w, 104, m, lab, sub, col)
    return p


def page_isx():
    """Hidden H2: Income Statement Explorer. Same components as the Goodly dynamic P&L page, in this report's look:
    six KPI cards (value, PY, change, % change), a focus selector driving a rule-based summary and a CY vs PY trend,
    a Thousand/Absolute toggle and an expandable section > line matrix with CY, % Rev, PY, % Rev, change, change % and bps."""
    p = Page(hexid('page', 'isx'), 'H2 · Income Statement Explorer', 'ISX', hidden=True)
    p.chrome('PT ISX', 'PS ISX')
    X = lambda v: CX + (v - 16) * SX
    Y = lambda v: CY + (v - 74) * SY
    cslicer(p, 'f_focus', 16, 74, 470, 64, 'PL Focus[Focus]', 'Focus (drives the summary and the trend)', mode='Basic', single=True, horizontal=True)
    cards = [('Revenue', 'Revenue ($)'), ('Cost of Sales', 'COGS ($)'), ('Gross Profit', 'Gross Profit ($)'), ('EBITDA', 'EBITDA ($)'), ('EBIT', 'EBIT ($)'), ('Net Income', 'Net Profit ($)')]
    cw = (470 - 2 * 8) / 3
    for i, (n, lab) in enumerate(cards):
        x0, y0, w0, h0 = X(16 + (i % 3) * (cw + 8)), Y(144 + (i // 3) * 124), cw * SX, 118 * SY
        p.add(f'c{i}_bg', 'textbox', x0, y0, w0, h0, content=False, header=False, objects={'general': [{'properties': {'paragraphs': [{'textRuns': [{'value': ''}]}]}}]})
        p.button(f'c{i}_l', x0 + 4, y0 + 3, w0 - 8, 18, lab, fill=None, text='Muted', outline=None, size=8.5, align='center', valign='middle')
        p.button(f'c{i}_v', x0 + 4, y0 + 20, w0 - 8, 26, '', measure=f'KV {n}', fill=None, text='Title', outline=None, size=14, align='center', bold=True, valign='middle')
        p.button(f'c{i}_p', x0 + 4, y0 + 48, w0 - 8, 18, '', measure=f'IS {n} PY Text', fill=None, text='Muted', outline=None, size=7.5, align='left', valign='middle')
        p.button(f'c{i}_c', x0 + 4, y0 + 66, w0 - 8, 18, '', measure=f'IS {n} Chg Text', fill=None, text='Muted', outline=None, size=7.5, align='left', valign='middle')
        p.button(f'c{i}_g', x0 + 4, y0 + 84, w0 - 8, 18, '', measure=f'IS {n} Pct Text', fill=None, text='Muted', outline=None, size=7.5, align='left', valign='middle')
        p.visuals[-1]['visual']['objects']['text'][1]['properties']['fontColor'] = mcolor(f'IS {n} PY Color')
    # rule-based summary for the focus line
    sx, sy, sw, sh = X(16), Y(398), 470 * SX, 126 * SY
    p.add('sum_bg', 'textbox', sx, sy, sw, sh, content=False, header=False, title='=VT Focus Summary',
          objects={'general': [{'properties': {'paragraphs': [{'textRuns': [{'value': ''}]}]}}]})
    for i in range(4):
        p.button(f'sum_{i}', sx + 6, sy + 24 + i * 22, sw - 12, 22, '', measure=f'Focus Bullet {i + 1}', fill=None, text='Text', outline=None, size=8, align='left', valign='middle')
    obj = p.axes({'dataPoint': [{'properties': {'fill': solid(SERIES['actual'])}, 'selector': {'metadata': '_Measures.Focus Monthly CY'}},
                                {'properties': {'fill': solid(SERIES['py'])}, 'selector': {'metadata': '_Measures.Focus Monthly PY'}}],
                  'lineStyles': [{'properties': {'lineChartType': L('smooth'), 'strokeWidth': L(2), 'showMarker': L(True)}}],
                  'labels': [{'properties': {'show': L(True), 'labelDisplayUnits': L(1000), 'labelPrecision': L(0), 'fontSize': L(7.5), 'color': T('Text')}}]}, value_axis=False)
    p.add('trend', 'lineChart', 16, 530, 470, 174, roles={'Category': ['Date[Month Name]'], 'Y': [('Focus Monthly CY', 'CY'), ('Focus Monthly PY', 'PY')]},
          objects=obj, title='=VT Focus Trend', subtitle='Sub Focus Trend', sort=[('Date[Month Name]', 'Ascending')])
    # right: unit toggle, expandable statement matrix, method notes
    cslicer(p, 'f_unit', 496, 74, 300, 64, 'Display Unit[Unit]', 'Amounts in', mode='Basic', single=True, horizontal=True)
    vals = [('IS CY', 'CY'), ('IS CY % Rev', 'CY % Rev'), ('IS PY', 'PY'), ('IS PY % Rev', 'PY % Rev'), ('IS Chg PY', 'Δ PY'), ('IS Chg % PY', 'Δ% PY'), ('IS Chg Rev bps', 'Δ % Rev (bps)')]
    names = [m for m, _ in vals]
    obj = matrix_objects(p, names, back={'_Measures.' + m: 'IS Row Background' for m in names},
                         colours={'_Measures.IS Chg PY': 'IS Chg Color', '_Measures.IS Chg % PY': 'IS Chg Color'})
    # no subtotal or grand-total rows: a collapsed section shows its own total (the measures sum the section's accounts),
    # and a P&L has no meaningful 'sum of all sections'
    obj['subTotals'] = [{'properties': {'rowSubtotals': L(False), 'columnSubtotals': L(False)}}]
    obj['rowHeaders'][0]['properties']['steppedLayout'] = L(True)
    p.add('matrix', 'pivotTable', 496, 144, 768, 386, roles={'Rows': [('Report Line[Section]', 'Heads'), ('Report Line[LineName]', 'Line')], 'Values': vals},
          objects=obj, title='=VT ISX', subtitle='Sub ISX',
          filters=[cat_filter(hexid(p.pid, 'matrix', 'f1'), 'Report Line', 'Statement', ['Income Statement']),
                   cat_filter(hexid(p.pid, 'matrix', 'f2'), 'Report Line', 'MatrixRow', ['Yes'])])
    p.story('method', 496, 536, 768, 168, 'ISX Method', '=VT ISX Method', 'Sub ISX Method', size=8, head=('Topic', 'Note'))
    return p


def page_rf():
    """Hidden H3: Rolling Forecast. Same components as the Goodly Budget vs Actual page (level 3): an 'Actuals Until' selector and a
    month matrix that shows actuals up to that month and budget after it; plus the question it exists to answer: will we reach the target?"""
    p = Page(hexid('page', 'rf'), 'H3 · Rolling Forecast', 'RF', hidden=True)
    p.chrome('PT RF', 'PS RF')
    # single-select slicers select their first item, so the list runs newest first: the page opens on the latest close
    cslicer(p, 'f_until', 16, 74, 220, 64, 'Actuals Until[Label]', 'Actuals until', single=True, sort=[('Actuals Until[Label]', 'Descending')])
    cslicer(p, 'f_metric', 246, 74, 800, 64, 'Metric[Metric]', 'Metric', mode='Basic', single=True, horizontal=True)
    w = (1248 - 3 * 10) / 4
    for i, (m, lab, sub, col) in enumerate([('RF Total', 'Rolling forecast (actual + remaining budget)', 'RF Total Text', 'RF Status Color'),
                                            ('RF Target', 'Target', 'RF Target Text', None),
                                            ('RF Required per Month', 'Required per remaining month', 'RF Required Text', 'RF Required Color'),
                                            ('RF Run-Rate Total', 'Average-month projection (cross-check)', 'RF Run-Rate Text', 'RF Run-Rate Color')]):
        p.kpi(f'k{i}', 16 + i * (w + 10), 144, w, 92, m, lab, sub, col)
    obj = matrix_objects(p, ['RF Value'], back={'_Measures.RF Value': 'RF Cell Color'})
    p.add('matrix', 'pivotTable', 16, 242, 1248, 268, roles={'Rows': [('Entity[EntityName]', 'Entity')], 'Columns': ['Date[Month Name]'], 'Values': [('RF Value', 'Value')]},
          objects=obj, title='=VT RF Matrix', subtitle='Sub RF Matrix')
    fields = ['Entity[EntityName]', 'RF Actual to Date', 'RF Remaining Budget', 'RF Total', 'RF Target', 'RF Gap', 'RF Attainment %', 'RF Required per Month',
              'RF Average per Month', 'RF Status']
    heads = ['Entity', 'Actual to date', 'Remaining budget', 'Rolling forecast', 'Target', 'Gap', 'Attainment', 'Required / month', 'Average / month', 'Status']
    obj = p.table_objects(fields, size=8.5, colours={'_Measures.RF Gap': 'RF Status Color', '_Measures.RF Status': 'RF Status Color', '_Measures.RF Attainment %': 'RF Status Color'})
    obj['total'] = [{'properties': {'totals': L(True)}}]
    obj['columnWidth'] = [{'properties': {'value': L(wd)}, 'selector': {'metadata': m if '[' not in m else m.replace('[', '.').rstrip(']')}}
                          for m, wd in zip(['Entity.EntityName'] + ['_Measures.' + f for f in fields[1:]], [104, 64, 64, 64, 64, 58, 54, 62, 58, 64])]
    p.add('table', 'tableEx', 16, 516, 846, 188, roles={'Values': list(zip(fields, heads))}, objects=obj, title='=VT RF Table', subtitle='Sub RF Table',
          sort=[('RF Gap', 'Ascending')])
    p.story('method', 872, 516, 392, 188, 'RF Method', '=VT RF Method', 'Sub RF Method', size=8, head=('Topic', 'Note'))
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
                        'title': [{'fontSize': 10.5}],
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
    pages = [page_overview(), page_executive(), page_bva(), page_income(), page_balance(), page_dq(), page_dictionary(), page_notes(),
             page_sankey(), page_isx(), page_rf()]
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
    print('files written:', WRITES['written'], '| unchanged:', WRITES['unchanged'])
    print('DataRoot:', 'kept from existing model' if '--data-root' not in sys.argv else 'set from argument', '| placeholder' if dr == PLACEHOLDER else '')
