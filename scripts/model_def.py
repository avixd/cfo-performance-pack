"""Semantic model definition for the CFO Performance Pack (rendered to TMDL by build_pbip.py)."""

# ---------------------------------------------------------------- Power Query
# Every query reads through ONE static data source, Folder.Files(DataRoot), and filters to the subfolder it needs.
# A path assembled from a function argument cannot be resolved statically, which makes Power BI demand a gateway,
# and mixing File.Contents with Folder.Files triggers privacy-level prompts. One source avoids both.
FN_READ_CSV = '''(subfolder as text, fileName as text) as table =>
let
    Target = Text.Lower(if subfolder = "" then DataRoot else DataRoot & subfolder & "\\"),
    Hit = Table.SelectRows(Folder.Files(DataRoot), each Text.Lower([Folder Path]) = Target and Text.Lower([Name]) = Text.Lower(fileName)),
    Source = Csv.Document(Hit{0}[Content], [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Blanks = Table.TransformColumns(Promoted, {}, (x) => if x = "" then null else x)
in
    Blanks'''

FN_LOAD_LEDGER = '''(subfolder as text, scenario as text) as table =>
let
    Target = Text.Lower(DataRoot & subfolder & "\\"),
    Files = Table.SelectRows(Folder.Files(DataRoot), each Text.Lower([Folder Path]) = Target),
    Csvs = Table.SelectRows(Files, each Text.Lower([Extension]) = ".csv" and Text.StartsWith([Name], "GL_")),
    Parsed = Table.AddColumn(Csvs, "Data", each Table.Distinct(Table.SelectColumns(Table.PromoteHeaders(Csv.Document([Content], [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]), [PromoteAllScalars = true]), {"Month", "EntityKey", "DepartmentKey", "AccountKey", "AmountLC", "BudgetSource"}, MissingField.UseNull))),
    Kept = Table.SelectColumns(Parsed, {"Name", "Data"}),
    Expanded = Table.ExpandTableColumn(Kept, "Data", {"Month", "EntityKey", "DepartmentKey", "AccountKey", "AmountLC", "BudgetSource"}),
    DeptFixed = Table.ReplaceValue(Table.ReplaceValue(Expanded, "", "0", Replacer.ReplaceValue, {"DepartmentKey"}), null, "0", Replacer.ReplaceValue, {"DepartmentKey"}),
    WithScenario = Table.AddColumn(DeptFixed, "Scenario", each scenario, type text)
in
    WithScenario'''

M_ACCOUNT = '''let
    Src = fnReadCsv("reference", "Account.csv"),
    Typed = Table.TransformColumnTypes(Src, {{"AccountKey", Int64.Type}, {"ParentAccountKey", Int64.Type}, {"AccountCode", type text}, {"AccountName", type text}, {"AccountType", type text}, {"UnaryOperator", type text}, {"Statement", type text}}, "en-US")
in
    Typed'''

M_ENTITY = '''let
    Src = fnReadCsv("reference", "Entity.csv"),
    Typed = Table.TransformColumnTypes(Src, {{"EntityKey", Int64.Type}, {"ParentEntityKey", Int64.Type}, {"EntityName", type text}, {"OwnershipPct", type number}, {"CurrencyCode", type text}}, "en-US")
in
    Typed'''

M_DEPARTMENT = '''let
    Src = fnReadCsv("reference", "Department.csv"),
    Typed = Table.TransformColumnTypes(Src, {{"DepartmentKey", Int64.Type}, {"ParentDepartmentKey", Int64.Type}, {"DepartmentName", type text}}, "en-US"),
    WithUnassigned = Table.Combine({Typed, #table(type table [DepartmentKey = Int64.Type, ParentDepartmentKey = Int64.Type, DepartmentName = text], {{0, 1, "Unassigned"}})})
in
    WithUnassigned'''

M_GL = '''let
    Actuals = fnLoadLedgerFolder("actuals", "Actual"),
    Budget = fnLoadLedgerFolder("budget", "Budget"),
    Combined = Table.Combine({Actuals, Budget}),
    Renamed = Table.RenameColumns(Combined, {{"Name", "SourceFile"}}),
    Source = Table.TransformColumns(Renamed, {{"BudgetSource", each if _ = null or _ = "" then "Ledger" else _}}),
    Typed = Table.TransformColumnTypes(Source, {{"Month", type date}, {"EntityKey", Int64.Type}, {"DepartmentKey", Int64.Type}, {"AccountKey", Int64.Type}, {"AmountLC", type number}, {"BudgetSource", type text}, {"SourceFile", type text}}, "en-US")
in
    Typed'''

M_FX = '''let
    FY = (d as date) as number => Date.Year(d) + (if Date.Month(d) >= 4 then 1 else 0),
    Src = fnReadCsv("fx", "FX_Rates.csv"),
    Typed = Table.TransformColumnTypes(Src, {{"Month", type date}, {"CurrencyCode", type text}, {"AvgRate", type number}, {"EndRate", type number}}, "en-US"),
    Observed = Table.SelectColumns(Typed, {"Month", "CurrencyCode", "AvgRate", "EndRate"}),
    LastObserved = List.Max(Observed[Month]),
    GridEnd = #date(FY(LastObserved) + 1, 3, 1),
    FirstMonth = List.Min(Observed[Month]),
    Months = List.Generate(() => FirstMonth, each _ <= GridEnd, each Date.AddMonths(_, 1)),
    Currencies = List.Distinct(Observed[CurrencyCode]),
    Grid = Table.FromRows(List.TransformMany(Currencies, each Months, (c, m) => {c, m}), type table [CurrencyCode = text, Month = date]),
    Joined = Table.NestedJoin(Grid, {"CurrencyCode", "Month"}, Observed, {"CurrencyCode", "Month"}, "R", JoinKind.LeftOuter),
    Expanded = Table.ExpandTableColumn(Joined, "R", {"AvgRate", "EndRate"}),
    Status = Table.AddColumn(Expanded, "RateStatus", each if [AvgRate] = null then "Carried forward" else "Observed", type text),
    EndFallback = Table.AddColumn(Status, "EndRate2", each if [EndRate] = null then [AvgRate] else [EndRate]),
    Sorted = Table.Sort(Table.RemoveColumns(EndFallback, {"EndRate"}), {{"CurrencyCode", Order.Ascending}, {"Month", Order.Ascending}}),
    Filled = Table.FillDown(Table.RenameColumns(Sorted, {{"EndRate2", "EndRate"}}), {"AvgRate", "EndRate"}),
    FYAvg = Table.Group(Table.AddColumn(Table.SelectRows(Filled, each [RateStatus] = "Observed"), "FiscalYear", each FY([Month]), Int64.Type), {"CurrencyCode", "FiscalYear"}, {{"BudgetRate", each List.Average([AvgRate]), type number}}),
    WithBY = Table.AddColumn(Filled, "BudgetBaseFY", each FY([Month]) - 1, Int64.Type),
    JoinedB = Table.NestedJoin(WithBY, {"CurrencyCode", "BudgetBaseFY"}, FYAvg, {"CurrencyCode", "FiscalYear"}, "B", JoinKind.LeftOuter),
    ExpandedB = Table.ExpandTableColumn(JoinedB, "B", {"BudgetRate"}),
    SortedB = Table.Sort(ExpandedB, {{"CurrencyCode", Order.Ascending}, {"Month", Order.Ascending}}),
    FilledB = Table.FillDown(SortedB, {"BudgetRate"}),
    BudgetFix = Table.AddColumn(FilledB, "BudgetRate2", each if [BudgetRate] = null then [AvgRate] else [BudgetRate]),
    Keyed = Table.AddColumn(BudgetFix, "FXKey", each [CurrencyCode] & "|" & Date.ToText([Month], "yyyy-MM"), type text),
    Final = Table.RenameColumns(Table.SelectColumns(Keyed, {"FXKey", "CurrencyCode", "Month", "AvgRate", "EndRate", "BudgetRate2", "RateStatus"}), {{"BudgetRate2", "BudgetRate"}}),
    Typed2 = Table.TransformColumnTypes(Final, {{"AvgRate", type number}, {"EndRate", type number}, {"BudgetRate", type number}})
in
    Typed2'''

M_DQ_FILES = '''let
    Expected = {"Month", "EntityKey", "DepartmentKey", "AccountKey", "AmountLC"},
    Profile = (sub as text) as table =>
        let
            F = Table.SelectRows(Folder.Files(DataRoot), each Text.Lower([Folder Path]) = Text.Lower(DataRoot & sub & "\\") and Text.Lower([Extension]) = ".csv" and Text.StartsWith([Name], "GL_")),
            WithStats = Table.AddColumn(F, "Stats", each
                let
                    T = Table.PromoteHeaders(Csv.Document([Content], [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]), [PromoteAllScalars = true]),
                    Cols = Table.ColumnNames(T),
                    Core = Table.SelectColumns(T, Expected, MissingField.UseNull),
                    Raw = Table.RowCount(T),
                    Distinct = Table.RowCount(Table.Distinct(T)),
                    MissingDept = Table.RowCount(Table.SelectRows(Core, each [DepartmentKey] = null or [DepartmentKey] = "")),
                    Drift = List.FirstN(Cols, 5) <> Expected or List.Count(List.RemoveItems(Cols, Expected & {"BudgetSource"})) > 0
                in
                    [RawRows = Raw, DuplicateRows = Raw - Distinct, MissingDepartmentRows = MissingDept, SchemaDrift = Drift, Columns = Text.Combine(Cols, ", ")]),
            Out = Table.AddColumn(Table.SelectColumns(WithStats, {"Name", "Stats"}), "Folder", each sub, type text)
        in
            Out,
    Combined = Table.Combine({Profile("actuals"), Profile("budget")}),
    Expanded = Table.ExpandRecordColumn(Combined, "Stats", {"RawRows", "DuplicateRows", "MissingDepartmentRows", "SchemaDrift", "Columns"}),
    Typed = Table.TransformColumnTypes(Expanded, {{"Name", type text}, {"RawRows", Int64.Type}, {"DuplicateRows", Int64.Type}, {"MissingDepartmentRows", Int64.Type}, {"SchemaDrift", type logical}, {"Columns", type text}})
in
    Typed'''

M_DQ_INJ = '''let
    Src = fnReadCsv("", "dq_injection_log.csv"),
    Typed = Table.TransformColumnTypes(Src, {{"Month", type text}, {"Issue", type text}, {"RowsAffected", Int64.Type}, {"Cause", type text}, {"Treatment", type text}}, "en-US")
in
    Typed'''

R = lambda a, b: list(range(a, b + 1))
GS = [52, 101]; RD = [53, 54]; NR = GS + RD; COS = [56, 57]; GP = NR + COS
SAL = [60, 61, 62]; COM = [63]; TE = R(65, 69); MKT = [71, 72]; OFF = [73, 74, 78, 102]; OCC = [76, 77, 87]
OPEX = SAL + COM + TE + MKT + OFF + OCC; EBITDA = GP + OPEX; DA = R(80, 85); EBIT = EBITDA + DA
INT = [89, 90]; OTH = [91, 92, 93]; PBT = EBIT + INT + OTH; TAX = [94]; NI = PBT + TAX
CA = [4]; AR = [6, 7, 8]; INV = [10, 11, 12]; OCA = [13, 14, 15]; TCA = CA + AR + INV + OCA; PPE = R(18, 23); OA = [24]; TA = TCA + PPE + OA
AP = [29]; ACR = [31, 32, 33]; STD = [28, 100]; OCL = [34, 35]; TCL = AP + ACR + STD + OCL; LTD = [37]; OLT = [38, 39, 40]; TL = TCL + LTD + OLT
PIC = [42, 43]; RE = [45, 46]; TEQ = PIC + RE; TLE = TL + TEQ
LINES = [
    (1, 'Gross Sales', 'Revenue', 'Detail', 'Income Statement', GS), (2, 'Returns & Discounts', 'Revenue', 'Detail', 'Income Statement', RD),
    (3, 'Net Revenue', 'Revenue', 'Subtotal', 'Income Statement', NR), (4, 'Cost of Sales', 'Cost of Sales', 'Detail', 'Income Statement', COS),
    (5, 'Gross Profit', 'Gross Profit', 'Subtotal', 'Income Statement', GP), (6, 'Salaries & Benefits', 'Operating Expenses', 'Detail', 'Income Statement', SAL),
    (7, 'Commissions', 'Operating Expenses', 'Detail', 'Income Statement', COM), (8, 'Travel & Entertainment', 'Operating Expenses', 'Detail', 'Income Statement', TE),
    (9, 'Marketing', 'Operating Expenses', 'Detail', 'Income Statement', MKT), (10, 'Office, Professional & Software', 'Operating Expenses', 'Detail', 'Income Statement', OFF),
    (11, 'Occupancy & Utilities', 'Operating Expenses', 'Detail', 'Income Statement', OCC), (12, 'Total Operating Expenses', 'Operating Expenses', 'Subtotal', 'Income Statement', OPEX),
    (13, 'EBITDA', 'EBITDA', 'Total', 'Income Statement', EBITDA), (14, 'Depreciation & Amortization', 'Below EBITDA', 'Detail', 'Income Statement', DA),
    (15, 'Operating Profit (EBIT)', 'EBIT', 'Total', 'Income Statement', EBIT), (16, 'Net Interest', 'Below EBIT', 'Detail', 'Income Statement', INT),
    (17, 'Other Income / (Expense)', 'Below EBIT', 'Detail', 'Income Statement', OTH), (18, 'Profit Before Tax', 'Profit Before Tax', 'Total', 'Income Statement', PBT),
    (19, 'Income Tax', 'Below PBT', 'Detail', 'Income Statement', TAX), (20, 'Net Income', 'Net Income', 'Total', 'Income Statement', NI),
    (101, 'Cash', 'Assets', 'Detail', 'Balance Sheet', CA), (102, 'Receivables', 'Assets', 'Detail', 'Balance Sheet', AR),
    (103, 'Inventory', 'Assets', 'Detail', 'Balance Sheet', INV), (104, 'Other Current Assets (incl. intercompany)', 'Assets', 'Detail', 'Balance Sheet', OCA),
    (105, 'Total Current Assets', 'Assets', 'Subtotal', 'Balance Sheet', TCA), (106, 'Property, Plant & Equipment', 'Assets', 'Detail', 'Balance Sheet', PPE),
    (107, 'Other Assets', 'Assets', 'Detail', 'Balance Sheet', OA), (108, 'Total Assets', 'Assets', 'Total', 'Balance Sheet', TA),
    (109, 'Accounts Payable', 'Liabilities', 'Detail', 'Balance Sheet', AP), (110, 'Accrued Liabilities', 'Liabilities', 'Detail', 'Balance Sheet', ACR),
    (111, 'Short-term Debt', 'Liabilities', 'Detail', 'Balance Sheet', STD), (112, 'Other Current Liabilities (incl. intercompany)', 'Liabilities', 'Detail', 'Balance Sheet', OCL),
    (113, 'Total Current Liabilities', 'Liabilities', 'Subtotal', 'Balance Sheet', TCL), (114, 'Long-term Debt', 'Liabilities', 'Detail', 'Balance Sheet', LTD),
    (115, 'Pension & Other Long-term Liabilities', 'Liabilities', 'Detail', 'Balance Sheet', OLT), (116, 'Total Liabilities', 'Liabilities', 'Subtotal', 'Balance Sheet', TL),
    (117, 'Paid-in Capital', 'Equity', 'Detail', 'Balance Sheet', PIC), (118, 'Retained Earnings', 'Equity', 'Detail', 'Balance Sheet', RE),
    (119, 'Total Equity', 'Equity', 'Subtotal', 'Balance Sheet', TEQ), (120, 'Total Liabilities & Equity', 'Liabilities & Equity', 'Total', 'Balance Sheet', TLE),
]

def m_table(cols, rows):
    head = ', '.join(f'{n} = {t}' for n, t in cols)
    def lit(v): return '"' + v.replace('"', '""') + '"' if isinstance(v, str) else str(v)   # M escapes a quote by doubling it
    body = ',\n        '.join('{' + ', '.join(lit(v) for v in r) + '}' for r in rows)
    return f'let\n    Source = #table(type table [{head}], {{\n        {body}\n    }})\nin\n    Source'

M_REPORT_LINE = m_table([('LineKey', 'Int64.Type'), ('LineName', 'text'), ('Section', 'text'), ('LineType', 'text'), ('Statement', 'text')],
                        [l[:5] for l in LINES])
M_REPORT_MAP = m_table([('LineKey', 'Int64.Type'), ('AccountKey', 'Int64.Type')], [(l[0], a) for l in LINES for a in l[5]])
M_CURRENCY = m_table([('Currency', 'text'), ('Sort', 'Int64.Type')], [('CAD', 1), ('USD', 2)])
M_PERIOD = m_table([('View', 'text'), ('Sort', 'Int64.Type')], [('YTD', 1), ('QTD', 2), ('MTD', 3)])
M_METRIC = m_table([('Metric', 'text'), ('LineKey', 'Int64.Type'), ('Sort', 'Int64.Type')],
                   [('Revenue', 3, 1), ('Gross Profit', 5, 2), ('Operating Expenses', 12, 3), ('EBITDA', 13, 4), ('Net Income', 20, 5)])
M_REV_BRIDGE = m_table([('Step', 'text'), ('Sort', 'Int64.Type')], [('Organic growth', 1), ('New entities', 2)])
M_EBITDA_BRIDGE = m_table([('Step', 'text'), ('Sort', 'Int64.Type')], [('Revenue', 1), ('Cost of sales', 2), ('Operating expenses', 3)])
M_INSIGHT = m_table([('Key', 'Int64.Type'), ('Topic', 'text')], [(1, 'Growth quality'), (2, 'Cost absorption'), (3, 'Full-year outlook')])
M_EMPTY = '#table(type table [Placeholder = text], {})'

DATE_DAX = '''VAR FYOf = YEAR ( MIN ( GL[Month] ) ) + IF ( MONTH ( MIN ( GL[Month] ) ) >= 4, 1, 0 )
VAR FYTo = YEAR ( MAX ( GL[Month] ) ) + IF ( MONTH ( MAX ( GL[Month] ) ) >= 4, 1, 0 )
VAR AsOf = CALCULATE ( MAX ( GL[Month] ), GL[Scenario] = "Actual" )
RETURN
    SELECTCOLUMNS (
        FILTER ( CALENDAR ( DATE ( FYOf - 1, 4, 1 ), DATE ( FYTo, 3, 1 ) ), DAY ( [Date] ) = 1 ),
        "Month", [Date],
        "Year", YEAR ( [Date] ),
        "Fiscal Year Number", YEAR ( [Date] ) + IF ( MONTH ( [Date] ) >= 4, 1, 0 ),
        "Fiscal Year", "FY" & ( YEAR ( [Date] ) + IF ( MONTH ( [Date] ) >= 4, 1, 0 ) ),
        "Fiscal Month Number", MOD ( MONTH ( [Date] ) + 8, 12 ) + 1,
        "Fiscal Quarter", "Q" & ( INT ( MOD ( MONTH ( [Date] ) + 8, 12 ) / 3 ) + 1 ),
        "Month Name", FORMAT ( [Date], "mmm" ),
        "Year Month", FORMAT ( [Date], "mmm yyyy" ),
        "Month Index", YEAR ( [Date] ) * 12 + MONTH ( [Date] ),
        "IsClosed", [Date] <= AsOf,
        "Period Status", IF ( [Date] <= AsOf, "Actual", "Outlook" )
    )'''

# ---------------------------------------------------------------- tables
# column spec: (name, dataType, props-dict)   props: hidden, fmt, sum, sortBy, desc, expr (calculated)
TABLES = [
    dict(name='Account', desc='Chart of accounts (parent-child) with statement type.', m=M_ACCOUNT, cols=[
        ('AccountKey', 'int64', {}), ('ParentAccountKey', 'int64', {'hidden': 1}), ('AccountCode', 'string', {}), ('AccountName', 'string', {}),
        ('AccountType', 'string', {}), ('UnaryOperator', 'string', {'hidden': 1}), ('Statement', 'string', {}),
        ('Sign', 'int64', {'hidden': 1, 'expr': 'SWITCH ( Account[AccountType], "Revenue", 1, "Expenditures", -1, "Assets", 1, "Liabilities", 1, 0 )',
                           'desc': 'Ledger stores revenue and costs as positive values; costs are shown negative so subtotals sum and a positive variance is always favourable.'})]),
    dict(name='Entity', desc='Reporting entities with local currency and ownership %.', m=M_ENTITY, cols=[
        ('EntityKey', 'int64', {}), ('ParentEntityKey', 'int64', {'hidden': 1}), ('EntityName', 'string', {}), ('OwnershipPct', 'double', {'fmt': '0%'}),
        ('CurrencyCode', 'string', {}),
        ('Effective Ownership', 'double', {'fmt': '0%', 'desc': 'Group economic interest: product of ownership % along the entity hierarchy.',
            'expr': 'VAR p = PATH ( Entity[EntityKey], Entity[ParentEntityKey] )\nRETURN\n    PRODUCTX (\n        GENERATESERIES ( 1, PATHLENGTH ( p ) ),\n        LOOKUPVALUE ( Entity[OwnershipPct], Entity[EntityKey], PATHITEM ( p, [Value], INTEGER ) )\n    )'}),
        ('Region', 'string', {'desc': 'Operating region (level 2 of the entity hierarchy).',
            'expr': 'VAR p = PATH ( Entity[EntityKey], Entity[ParentEntityKey] )\nVAR r = IF ( PATHLENGTH ( p ) >= 2, LOOKUPVALUE ( Entity[EntityName], Entity[EntityKey], PATHITEM ( p, 2, INTEGER ) ), Entity[EntityName] )\nRETURN SWITCH ( r, "North America Operations", "North America", "European Operations", "Europe", "Pacific Operations", "Pacific", r )'})]),
    dict(name='Department', desc='Department groups; 0 = Unassigned (blank department in source).', m=M_DEPARTMENT, cols=[
        ('DepartmentKey', 'int64', {}), ('ParentDepartmentKey', 'int64', {'hidden': 1}), ('DepartmentName', 'string', {})]),
    dict(name='GL', desc='General ledger fact in local currency: actuals one file per month, budgets one file per fiscal year. Grain: month x entity x department x account x scenario.', m=M_GL, cols=[
        ('Month', 'dateTime', {'fmt': 'mmm yyyy'}), ('EntityKey', 'int64', {'hidden': 1}), ('DepartmentKey', 'int64', {'hidden': 1}),
        ('AccountKey', 'int64', {'hidden': 1}), ('AmountLC', 'double', {'hidden': 1, 'fmt': '#,0'}), ('Scenario', 'string', {}),
        ('BudgetSource', 'string', {}), ('SourceFile', 'string', {'hidden': 1}),
        ('Rate Type', 'string', {'hidden': 1, 'expr': 'IF ( RELATED ( Account[Statement] ) = "Balance Sheet", "End", IF ( GL[Scenario] = "Budget", "Budget", "Avg" ) )'}),
        ('Rate to CAD', 'double', {'hidden': 1, 'expr': 'VAR k = RELATED ( Entity[CurrencyCode] ) & "|" & FORMAT ( GL[Month], "yyyy-MM" )\nRETURN\n    SWITCH (\n        GL[Rate Type],\n        "End", LOOKUPVALUE ( FX[EndRate], FX[FXKey], k ),\n        "Budget", LOOKUPVALUE ( FX[BudgetRate], FX[FXKey], k ),\n        LOOKUPVALUE ( FX[AvgRate], FX[FXKey], k )\n    )'}),
        ('Rate USD to CAD', 'double', {'hidden': 1, 'expr': 'VAR k = "USD|" & FORMAT ( GL[Month], "yyyy-MM" )\nRETURN\n    SWITCH (\n        GL[Rate Type],\n        "End", LOOKUPVALUE ( FX[EndRate], FX[FXKey], k ),\n        "Budget", LOOKUPVALUE ( FX[BudgetRate], FX[FXKey], k ),\n        LOOKUPVALUE ( FX[AvgRate], FX[FXKey], k )\n    )'}),
        ('Amount CAD', 'double', {'hidden': 1, 'fmt': '#,0', 'expr': 'GL[AmountLC] * GL[Rate to CAD] * RELATED ( Account[Sign] )'}),
        ('Amount USD', 'double', {'hidden': 1, 'fmt': '#,0', 'expr': 'DIVIDE ( GL[Amount CAD], GL[Rate USD to CAD] )'})]),
    dict(name='FX', desc='Bank of Canada rates (CAD per unit): monthly average for P&L, month-end for balance sheet, budget rate = prior fiscal-year average. Months after the last observed rate carry it forward.', m=M_FX, cols=[
        ('FXKey', 'string', {'hidden': 1}), ('CurrencyCode', 'string', {}), ('Month', 'dateTime', {'fmt': 'mmm yyyy'}),
        ('AvgRate', 'double', {'fmt': '0.0000'}), ('EndRate', 'double', {'fmt': '0.0000'}), ('BudgetRate', 'double', {'fmt': '0.0000'}), ('RateStatus', 'string', {})]),
    dict(name='Report Line', desc='Management P&L and balance-sheet template (Goodly method). Order follows LineKey.', m=M_REPORT_LINE, cols=[
        ('LineKey', 'int64', {}), ('LineName', 'string', {'sortBy': 'LineKey'}), ('Section', 'string', {}), ('LineType', 'string', {}), ('Statement', 'string', {})]),
    dict(name='Report Line Map', hidden=1, desc='Each report line mapped to every account it includes; subtotals repeat the accounts of the lines they roll up.', m=M_REPORT_MAP, cols=[
        ('LineKey', 'int64', {}), ('AccountKey', 'int64', {})]),
    dict(name='Date', desc='Monthly fiscal calendar (April-March, named by the year it ends). Spans every fiscal year in GL, so a new year appears when its files land.', dax=DATE_DAX, cols=[
        ('Month', 'dateTime', {'fmt': 'mmm yyyy'}), ('Year', 'int64', {'fmt': '0'}), ('Fiscal Year Number', 'int64', {'fmt': '0', 'hidden': 1}),
        ('Fiscal Year', 'string', {'sortBy': 'Fiscal Year Number'}), ('Fiscal Month Number', 'int64', {'hidden': 1}), ('Fiscal Quarter', 'string', {}),
        ('Month Name', 'string', {'sortBy': 'Fiscal Month Number'}), ('Year Month', 'string', {'sortBy': 'Month Index'}), ('Month Index', 'int64', {'hidden': 1}),
        ('IsClosed', 'boolean', {}), ('Period Status', 'string', {})]),
    dict(name='Reporting Currency', desc='Slicer: presentation currency (CAD default).', m=M_CURRENCY, cols=[('Currency', 'string', {'sortBy': 'Sort'}), ('Sort', 'int64', {'hidden': 1})]),
    dict(name='Period View', desc='Slicer: MTD, QTD or YTD (default YTD).', m=M_PERIOD, cols=[('View', 'string', {'sortBy': 'Sort'}), ('Sort', 'int64', {'hidden': 1})]),
    dict(name='Metric', desc='Slicer: which P&L measure the Budget vs Actual page analyses.', m=M_METRIC, cols=[('Metric', 'string', {'sortBy': 'Sort'}), ('LineKey', 'int64', {'hidden': 1}), ('Sort', 'int64', {'hidden': 1})]),
    dict(name='Revenue Bridge', desc='Axis for the prior-year to current-year revenue bridge.', m=M_REV_BRIDGE, cols=[('Step', 'string', {'sortBy': 'Sort'}), ('Sort', 'int64', {'hidden': 1})]),
    dict(name='EBITDA Bridge', desc='Axis for the budget to actual EBITDA bridge.', m=M_EBITDA_BRIDGE, cols=[('Step', 'string', {'sortBy': 'Sort'}), ('Sort', 'int64', {'hidden': 1})]),
    dict(name='Insight', desc='Rows for the insight tables: each topic shows one narrative measure.', m=M_INSIGHT, cols=[('Key', 'int64', {'hidden': 1}), ('Topic', 'string', {'sortBy': 'Key'})]),
    dict(name='DQ File Log', desc='Profile of every source file on each refresh: raw rows, exact duplicates, blank departments, schema drift.', m=M_DQ_FILES, cols=[
        ('Name', 'string', {}), ('Folder', 'string', {}), ('RawRows', 'int64', {'sum': 'sum'}), ('DuplicateRows', 'int64', {'sum': 'sum'}),
        ('MissingDepartmentRows', 'int64', {'sum': 'sum'}), ('SchemaDrift', 'boolean', {}), ('Columns', 'string', {})]),
    dict(name='DQ Injection Log', desc='What the reproducible generator deliberately broke (data/dq_injection_log.csv), for reconciliation to what was detected.', m=M_DQ_INJ, cols=[
        ('Month', 'string', {}), ('Issue', 'string', {}), ('RowsAffected', 'int64', {'sum': 'sum'}), ('Cause', 'string', {}), ('Treatment', 'string', {})]),
    dict(name='_Measures', desc='Home table for all measures, organised in display folders.', m=M_EMPTY, cols=[('Placeholder', 'string', {'hidden': 1})]),
]

RELATIONSHIPS = [('GL', 'Month', 'Date', 'Month'), ('GL', 'EntityKey', 'Entity', 'EntityKey'),
                 ('GL', 'DepartmentKey', 'Department', 'DepartmentKey'), ('GL', 'AccountKey', 'Account', 'AccountKey')]

# ---------------------------------------------------------------- measures
# Number-format standard (one place, used by every text measure and KPI card):
#   money      $ prefix; one decimal in millions (>= 1M), whole thousands (>= 1K), whole units below; negatives in brackets
#   variances  explicit sign (+$0.6M / -$1.2M) or arrow (▲ $0.6M / ▼ $1.2M); colour, not sign, says favourable/unfavourable
#   counts     #,0      percentages 0.0%      percentage points 0.0 pts      ratios 0.00x      days #,0
MONEY_FMT = {'plain': ('"$#,0.0\\M;($#,0.0\\M)"', '"$#,0\\K;($#,0\\K)"', '"$#,0;($#,0)"'),
             'signed': ('"+$#,0.0\\M;-$#,0.0\\M;$0.0\\M"', '"+$#,0\\K;-$#,0\\K;$0\\K"', '"+$#,0;-$#,0;$0"'),
             'arrow': ('"▲ $#,0.0\\M;▼ $#,0.0\\M;$0.0\\M"', '"▲ $#,0\\K;▼ $#,0\\K;$0\\K"', '"▲ $#,0;▼ $#,0;$0"')}
def money(x, style='plain'):
    """DAX text for a currency amount, scaled to M / K / units (see the number-format standard above)."""
    fm, fk, fu = MONEY_FMT[style]
    return (f'( VAR _x = {x} RETURN IF ( NOT ISBLANK ( _x ), SWITCH ( TRUE (), ABS ( _x ) >= 1e6, FORMAT ( _x / 1e6, {fm} ), '
            f'ABS ( _x ) >= 1e3, FORMAT ( _x / 1e3, {fk} ), FORMAT ( _x, {fu} ) ) ) )')

F, P, PTS = '#,0;(#,0);-', '0.0%;-0.0%;-', '+0.0%;-0.0%;-'
MEAS = []
def add(name, expr, folder, fmt=None, desc=None): MEAS.append(dict(name=name, expr=expr, folder=folder, fmt=fmt, desc=desc))
LINE = lambda key, base: f"CALCULATE ( {base}, TREATAS ( CALCULATETABLE ( VALUES ( 'Report Line Map'[AccountKey] ), 'Report Line Map'[LineKey] = {key} ), Account[AccountKey] ) )"
ACC = lambda base: ("IF ( HASONEVALUE ( 'Report Line'[LineKey] ),\n    VAR accts = CALCULATETABLE ( VALUES ( 'Report Line Map'[AccountKey] ), TREATAS ( VALUES ( 'Report Line'[LineKey] ), 'Report Line Map'[LineKey] ) )\n"
                    f"    RETURN CALCULATE ( {base}, TREATAS ( accts, Account[AccountKey] ) )\n)")
MET = lambda base: ("VAR lk = SELECTEDVALUE ( Metric[LineKey], 3 )\nVAR accts = CALCULATETABLE ( VALUES ( 'Report Line Map'[AccountKey] ), 'Report Line Map'[LineKey] = lk )\n"
                    f"RETURN CALCULATE ( {base}, TREATAS ( accts, Account[AccountKey] ) )")
FYN = lambda d: f'( YEAR ( {d} ) + IF ( MONTH ( {d} ) >= 4, 1, 0 ) )'

# 0 Base
add('Amount', 'IF ( SELECTEDVALUE ( \'Reporting Currency\'[Currency], "CAD" ) = "USD", SUM ( GL[Amount USD] ), SUM ( GL[Amount CAD] ) )', '0 Base', F,
    'Ledger amount in the selected reporting currency (CAD default). Costs are negative.')
add('Currency Label', 'SELECTEDVALUE ( \'Reporting Currency\'[Currency], "CAD" )', '0 Base')
add('As Of Month', 'CALCULATE ( MAX ( GL[Month] ), REMOVEFILTERS (), GL[Scenario] = "Actual" )', '0 Base', 'mmm yyyy',
    'Latest month with actuals loaded (the close). Moves forward automatically when a new actuals file is added.')
add('Selected Month', 'VAR picked = CALCULATE ( MAX ( \'Date\'[Month] ), ALLSELECTED ( \'Date\' ) )\nVAR asOf = [As Of Month]\nRETURN IF ( ISBLANK ( picked ) || picked > asOf, asOf, picked )', '0 Base', 'mmm yyyy',
    'Reporting month: the latest month selected in the date slicers, capped at the close. Defaults to the close.')
add('Selected Fiscal Year', f'VAR m = [Selected Month] RETURN "FY" & {FYN("m")}', '0 Base')
add('Fiscal Month Of Selection', 'MOD ( MONTH ( [Selected Month] ) + 8, 12 ) + 1', '0 Base', '0')
add('Period Label', 'SELECTEDVALUE ( \'Period View\'[View], "YTD" ) & " " & FORMAT ( [Selected Month], "mmm yyyy" ) & " · " & [Currency Label]', '0 Base')
add('Actual', 'CALCULATE ( [Amount], GL[Scenario] = "Actual" )', '0 Base', F)
add('Budget', 'CALCULATE ( [Amount], GL[Scenario] = "Budget" )', '0 Base', F)

# 1 Period (fiscal)
def per(name, base, kind, shift=0, desc=None):
    m = 'EDATE ( [Selected Month], -12 )' if shift else '[Selected Month]'
    if kind == 'MTD': flt = "'Date'[Month] = m"
    elif kind == 'QTD': flt = "'Date'[Month] >= DATE ( YEAR ( m ), INT ( ( MONTH ( m ) - 1 ) / 3 ) * 3 + 1, 1 ) && 'Date'[Month] <= m"
    else: flt = f"'Date'[Month] >= DATE ( {FYN('m')} - 1, 4, 1 ) && 'Date'[Month] <= m"
    add(name, f"VAR m = {m}\nRETURN CALCULATE ( {base}, REMOVEFILTERS ( 'Date' ), {flt} )", '1 Period (fiscal)', F, desc)
for k in ('MTD', 'QTD', 'YTD'):
    per(f'Actual {k}', '[Actual]', k); per(f'Budget {k}', '[Budget]', k); per(f'Prior Year {k}', '[Actual]', k, 1)
add('Budget FY', f"VAR m = [Selected Month] VAR fy = {FYN('m')}\nRETURN CALCULATE ( [Budget], REMOVEFILTERS ( 'Date' ), 'Date'[Fiscal Year Number] = fy )", '1 Period (fiscal)', F,
    'Full fiscal-year budget for the year of the selected month.')
add('Outlook FY', f"VAR m = [Selected Month] VAR fy = {FYN('m')}\nRETURN [Actual YTD] + CALCULATE ( [Budget], REMOVEFILTERS ( 'Date' ), 'Date'[Fiscal Year Number] = fy && 'Date'[Month] > m )",
    '1 Period (fiscal)', F, 'Rolling fiscal-year outlook: actuals to the selected month + budget for the remaining months (Goodly level-3 pattern).')
add('Actual (Period)', "SWITCH ( SELECTEDVALUE ( 'Period View'[View], \"YTD\" ), \"MTD\", [Actual MTD], \"QTD\", [Actual QTD], [Actual YTD] )", '1 Period (fiscal)', F)
add('Budget (Period)', "SWITCH ( SELECTEDVALUE ( 'Period View'[View], \"YTD\" ), \"MTD\", [Budget MTD], \"QTD\", [Budget QTD], [Budget YTD] )", '1 Period (fiscal)', F)
add('Prior Year (Period)', "SWITCH ( SELECTEDVALUE ( 'Period View'[View], \"YTD\" ), \"MTD\", [Prior Year MTD], \"QTD\", [Prior Year QTD], [Prior Year YTD] )", '1 Period (fiscal)', F)
add('Closing Balance', "VAR m = [Selected Month]\nRETURN CALCULATE ( [Actual], REMOVEFILTERS ( 'Date' ), 'Date'[Month] = m )", '1 Period (fiscal)', F, 'Balance-sheet value at the selected month end.')
add('Prior Year-End Balance', f"VAR m = [Selected Month] VAR ye = DATE ( {FYN('m')} - 1, 3, 1 )\nRETURN CALCULATE ( [Actual], REMOVEFILTERS ( 'Date' ), 'Date'[Month] = ye )", '1 Period (fiscal)', F,
    'Balance at the previous fiscal year end (31 March).')
HV = lambda body: ("IF ( HASONEVALUE ( 'Date'[Fiscal Month Number] ),\n    VAR fm = MAX ( 'Date'[Fiscal Month Number] ) VAR fy = " + FYN('[Selected Month]') +
                   "\n    VAR d = DATE ( fy - 1, 3 + fm, 1 ) VAR sel = [Selected Month] VAR fyStart = DATE ( fy - 1, 4, 1 )\n    RETURN " + body + "\n)")
MF = '1 Period (fiscal)\\Month axis'
add('Monthly Actual (Selected FY)', HV("IF ( d <= sel, CALCULATE ( [Actual], REMOVEFILTERS ( 'Date' ), 'Date'[Month] = d ) )"), MF, F,
    'Month-axis charts: actual for each fiscal month of the selected year, up to the selected month. Independent of which years the date slicer shows.')
add('Monthly Budget (Selected FY)', HV("CALCULATE ( [Budget], REMOVEFILTERS ( 'Date' ), 'Date'[Month] = d )"), MF, F)
add('Monthly Outlook (Selected FY)', HV("IF ( d > sel, CALCULATE ( [Budget], REMOVEFILTERS ( 'Date' ), 'Date'[Month] = d ) )"), MF, F,
    'Budget shown as the outlook for months after the selected month.')
add('Monthly Prior Year (Selected FY)', HV("CALCULATE ( [Actual], REMOVEFILTERS ( 'Date' ), 'Date'[Month] = EDATE ( d, -12 ) )"), MF, F)
add('Cumulative Actual (Selected FY)', HV("IF ( d <= sel, CALCULATE ( [Actual], REMOVEFILTERS ( 'Date' ), 'Date'[Month] >= fyStart && 'Date'[Month] <= d ) )"), MF, F)
add('Cumulative Outlook (Selected FY)', HV("IF ( d >= sel, CALCULATE ( [Actual], REMOVEFILTERS ( 'Date' ), 'Date'[Month] >= fyStart && 'Date'[Month] <= sel ) + CALCULATE ( [Budget], REMOVEFILTERS ( 'Date' ), 'Date'[Month] > sel && 'Date'[Month] <= d ) )"), MF, F,
    'Actual to the selected month plus budget for later months, accumulated: where the year is heading.')
add('Cumulative Budget (Selected FY)', HV("CALCULATE ( [Budget], REMOVEFILTERS ( 'Date' ), 'Date'[Month] >= fyStart && 'Date'[Month] <= d )"), MF, F)

# 2 Statement lines
add('Line Actual', ACC('[Actual (Period)]'), '2 Statement Lines', F, 'Report-line value for the Period View; one line at a time.')
add('Line Budget', ACC('[Budget (Period)]'), '2 Statement Lines', F)
add('Line Prior Year', ACC('[Prior Year (Period)]'), '2 Statement Lines', F)
add('Line Var vs Budget', '[Line Actual] - [Line Budget]', '2 Statement Lines', F, 'Positive = favourable (costs are stored negative).')
add('Line Var % vs Budget', 'IF ( NOT ISBLANK ( [Line Budget] ), DIVIDE ( [Line Actual] - [Line Budget], ABS ( [Line Budget] ) ) )', '2 Statement Lines', P)
add('Line Var vs Prior Year', '[Line Actual] - [Line Prior Year]', '2 Statement Lines', F)
add('Line Growth %', 'IF ( NOT ISBLANK ( [Line Prior Year] ), DIVIDE ( [Line Actual] - [Line Prior Year], ABS ( [Line Prior Year] ) ) )', '2 Statement Lines', P)
add('Line % of Revenue', f"DIVIDE ( [Line Actual], {LINE(3, '[Actual (Period)]')} )", '2 Statement Lines', P)
add('Line Outlook FY', ACC('[Outlook FY]'), '2 Statement Lines', F)
add('Line Budget FY', ACC('[Budget FY]'), '2 Statement Lines', F)
add('Line Closing Balance', ACC('[Closing Balance]'), '2 Statement Lines', F)
add('Line Prior Year-End Balance', ACC('[Prior Year-End Balance]'), '2 Statement Lines', F)
add('Line Balance Change', '[Line Closing Balance] - [Line Prior Year-End Balance]', '2 Statement Lines', F)
add('Line Var Color', 'IF ( [Line Var vs Budget] < 0, "#C0392B", "#2E7D32" )', '8 Formatting')

# 3 KPIs
KPI = {'Revenue': 3, 'Cost of Sales': 4, 'Gross Profit': 5, 'Operating Expenses': 12, 'EBITDA': 13, 'EBIT': 15, 'Net Income': 20}
for n, key in KPI.items():
    fo = f'3 KPIs\\{n}'
    add(n, LINE(key, '[Actual (Period)]'), fo, F); add(f'{n} Budget', LINE(key, '[Budget (Period)]'), fo, F); add(f'{n} PY', LINE(key, '[Prior Year (Period)]'), fo, F)
    add(f'{n} Var vs Budget', f'[{n}] - [{n} Budget]', fo, F)
    add(f'{n} Var % vs Budget', f'DIVIDE ( [{n}] - [{n} Budget], ABS ( [{n} Budget] ) )', fo, P)
    add(f'{n} Growth %', f'DIVIDE ( [{n}] - [{n} PY], ABS ( [{n} PY] ) )', fo, P)
    add(f'{n} Outlook FY', LINE(key, '[Outlook FY]'), fo, F); add(f'{n} Budget FY', LINE(key, '[Budget FY]'), fo, F)
    add(f'{n} Monthly Actual', LINE(key, '[Actual]'), fo, F)
    add(f'{n} vs Budget Text', f'FORMAT ( [{n} Var % vs Budget], "▲ 0.0%;▼ 0.0%;0.0%" ) & " vs Bud  ·  " & FORMAT ( [{n} Growth %], "▲ 0.0%;▼ 0.0%;0.0%" ) & " vs PY"', fo)
    add(f'{n} Var Color', f'IF ( [{n} Var vs Budget] < 0, "#C0392B", "#2E7D32" )', '8 Formatting')
for n in ('Gross Profit', 'EBITDA', 'Net Income'):
    add(f'{n} Margin %', f'DIVIDE ( [{n}], [Revenue] )', '3 KPIs\\Margins', P)
    add(f'{n} Margin % Budget', f'DIVIDE ( [{n} Budget], [Revenue Budget] )', '3 KPIs\\Margins', P)
    add(f'{n} Margin pts vs Budget', f'[{n} Margin %] - [{n} Margin % Budget]', '3 KPIs\\Margins', PTS)
add('OpEx % of Revenue', 'DIVIDE ( -[Operating Expenses], [Revenue] )', '3 KPIs\\Margins', P)
add('Gross Margin Text', 'FORMAT ( [Gross Profit Margin pts vs Budget] * 100, "▲ 0.0;▼ 0.0;0.0" ) & " pts vs budget"', '3 KPIs\\Margins')
add('Gross Margin Var Color', 'IF ( [Gross Profit Margin pts vs Budget] < 0, "#C0392B", "#2E7D32" )', '8 Formatting')
# perimeter / organic
add('Revenue Like-for-Like', 'SUMX ( VALUES ( Entity[EntityKey] ), IF ( NOT ISBLANK ( [Revenue PY] ), [Revenue] ) )', '3 KPIs\\Perimeter', F,
    'Revenue from entities that also traded in the same period last year.')
add('Revenue New Entities', '[Revenue] - [Revenue Like-for-Like]', '3 KPIs\\Perimeter', F, 'Revenue from entities that joined the group within the last twelve months.')
add('Organic Growth %', 'DIVIDE ( [Revenue Like-for-Like] - [Revenue PY], ABS ( [Revenue PY] ) )', '3 KPIs\\Perimeter', P)
add('Revenue Unbudgeted', 'SUMX ( VALUES ( Entity[EntityKey] ), IF ( ISBLANK ( [Revenue Budget] ), [Revenue] ) )', '3 KPIs\\Perimeter', F,
    'Revenue earned by entities with no budget for the period (acquired after the budget was set).')
add('Revenue Var vs Budget (Budgeted Entities)', 'SUMX ( VALUES ( Entity[EntityKey] ), IF ( NOT ISBLANK ( [Revenue Budget] ), [Revenue] - [Revenue Budget] ) )', '3 KPIs\\Perimeter', F)
add('Revenue Var % vs Budget (Budgeted Entities)', 'DIVIDE ( [Revenue Var vs Budget (Budgeted Entities)], ABS ( [Revenue Budget] ) )', '3 KPIs\\Perimeter', P)
add('Entities Reporting', 'VAR m = [Selected Month] RETURN CALCULATE ( DISTINCTCOUNT ( GL[EntityKey] ), GL[Scenario] = "Actual", REMOVEFILTERS ( \'Date\' ), \'Date\'[Month] = m )', '3 KPIs\\Perimeter', '0')
add('Revenue TTM', f"VAR m = [Selected Month]\nRETURN CALCULATE ( {LINE(3, '[Actual]')}, REMOVEFILTERS ( 'Date' ), 'Date'[Month] > EDATE ( m, -12 ) && 'Date'[Month] <= m )", '3 KPIs\\Perimeter', F)
add('Revenue Bridge Value', "SWITCH ( SELECTEDVALUE ( 'Revenue Bridge'[Step] ), \"Organic growth\", [Revenue Like-for-Like] - [Revenue PY], \"New entities\", [Revenue New Entities] )",
    '3 KPIs\\Perimeter', F, 'Revenue growth vs prior year split into organic (like-for-like entities) and new entities; the waterfall total is the total growth.')
add('EBITDA Bridge Value', "SWITCH ( SELECTEDVALUE ( 'EBITDA Bridge'[Step] ), \"Revenue\", [Revenue Var vs Budget], \"Cost of sales\", [Cost of Sales Var vs Budget], \"Operating expenses\", [Operating Expenses Var vs Budget] )",
    '3 KPIs\\EBITDA', F, 'EBITDA variance to budget split by driver; the waterfall total is the EBITDA variance.')
# ownership
add('Net Income Attributable to Group', 'SUMX ( VALUES ( Entity[EntityKey] ), CALCULATE ( [Net Income] ) * CALCULATE ( MAX ( Entity[Effective Ownership] ) ) )', '3 KPIs\\Ownership', F)
add('Net Income Attributable to NCI', '[Net Income] - [Net Income Attributable to Group]', '3 KPIs\\Ownership', F, 'Share of profit belonging to minority partners in partly owned entities.')

add('Entity First Month', "CALCULATE ( MIN ( GL[Month] ), GL[Scenario] = \"Actual\", REMOVEFILTERS ( 'Date' ) )", '3 KPIs\\Perimeter', 'mmm yyyy',
    'First month the entity appears in the actuals ledger.')
add('Entity Joined FY', 'VAR m = [Entity First Month] RETURN IF ( NOT ISBLANK ( m ), "FY" & ' + FYN('m') + ' )', '3 KPIs\\Perimeter')
add('Entity Budget Status', 'IF ( NOT ISBLANK ( [Entity First Month] ), IF ( ISBLANK ( [Budget FY] ), "Not budgeted", "Budgeted" ) )', '3 KPIs\\Perimeter',
    None, 'Whether the entity has a budget for the selected fiscal year.')
add('Revenue Actual (in context)', LINE(3, '[Actual]'), '3 KPIs\\Revenue', F, 'Net revenue for whatever dates are on the axis (e.g. a fiscal-year column).')
add('Cash Balance (month)', LINE(101, '[Actual]'), '4 Balance Sheet KPIs', F, 'Month-end cash for each month on the axis.')
add('Working Capital (month)', LINE(102, '[Actual]') + ' + ' + LINE(103, '[Actual]') + ' - ' + LINE(109, '[Actual]'), '4 Balance Sheet KPIs', F,
    'Trade working capital at each month end: receivables + inventory - payables.')
add('Line Row Background', "IF ( HASONEVALUE ( 'Report Line'[LineKey] ), SWITCH ( SELECTEDVALUE ( 'Report Line'[LineType] ), \"Subtotal\", \"#EEF1F5\", \"Total\", \"#DCE3EC\", \"#FFFFFF\" ) )", '8 Formatting')
add('Line Growth Color', 'IF ( [Line Growth %] < 0, "#C0392B", "#2E7D32" )', '8 Formatting')
add('Balance Change Color', 'IF ( [Line Balance Change] < 0, "#C0392B", "#2E7D32" )', '8 Formatting')

# Metric selector (Budget vs Actual page)
add('Metric Name', 'SELECTEDVALUE ( Metric[Metric], "Revenue" )', '5 Metric Selector')
add('Metric Actual', MET('[Actual (Period)]'), '5 Metric Selector', F)
add('Metric Budget', MET('[Budget (Period)]'), '5 Metric Selector', F)
add('Metric PY', MET('[Prior Year (Period)]'), '5 Metric Selector', F)
add('Metric Var vs Budget', '[Metric Actual] - [Metric Budget]', '5 Metric Selector', F)
add('Metric Var % vs Budget', 'DIVIDE ( [Metric Actual] - [Metric Budget], ABS ( [Metric Budget] ) )', '5 Metric Selector', P)
add('Metric Growth %', 'DIVIDE ( [Metric Actual] - [Metric PY], ABS ( [Metric PY] ) )', '5 Metric Selector', P)
add('Metric Outlook FY', MET('[Outlook FY]'), '5 Metric Selector', F)
add('Metric Budget FY', MET('[Budget FY]'), '5 Metric Selector', F)
add('Metric Outlook Gap', '[Metric Outlook FY] - [Metric Budget FY]', '5 Metric Selector', F)
add('Metric Monthly Actual', MET('[Monthly Actual (Selected FY)]'), '5 Metric Selector', F)
add('Metric Monthly Budget', MET('[Monthly Budget (Selected FY)]'), '5 Metric Selector', F)
add('Metric Monthly Outlook', MET('[Monthly Outlook (Selected FY)]'), '5 Metric Selector', F)
add('Metric Monthly Prior Year', MET('[Monthly Prior Year (Selected FY)]'), '5 Metric Selector', F)
add('Metric Cumulative Actual', MET('[Cumulative Actual (Selected FY)]'), '5 Metric Selector', F)
add('Metric Cumulative Outlook', MET('[Cumulative Outlook (Selected FY)]'), '5 Metric Selector', F)
add('Metric Cumulative Budget', MET('[Cumulative Budget (Selected FY)]'), '5 Metric Selector', F)
add('Metric Var Color', 'IF ( [Metric Var vs Budget] < 0, "#C0392B", "#2E7D32" )', '8 Formatting')
add('Metric Gap Color', 'IF ( [Metric Outlook Gap] < 0, "#C0392B", "#2E7D32" )', '8 Formatting')

# 4 Balance sheet KPIs
B = lambda key: LINE(key, '[Closing Balance]')
add('Cash', B(101), '4 Balance Sheet KPIs', F); add('Total Assets', B(108), '4 Balance Sheet KPIs', F); add('Total Equity', B(119), '4 Balance Sheet KPIs', F)
add('Current Ratio', f'DIVIDE ( {B(105)}, {B(113)} )', '4 Balance Sheet KPIs', '0.00')
add('Debt to Equity', f'DIVIDE ( {B(111)} + {B(114)}, {B(119)} )', '4 Balance Sheet KPIs', '0.00')
add('Cost of Sales TTM', f"VAR m = [Selected Month]\nRETURN CALCULATE ( {LINE(4, '[Actual]')}, REMOVEFILTERS ( 'Date' ), 'Date'[Month] > EDATE ( m, -12 ) && 'Date'[Month] <= m )", '4 Balance Sheet KPIs', F)
add('DSO (days)', f'DIVIDE ( {B(102)}, [Revenue TTM] ) * 365', '4 Balance Sheet KPIs', '0', 'Receivables / trailing-twelve-month revenue x 365.')
add('DPO (days)', f'DIVIDE ( {B(109)}, -[Cost of Sales TTM] ) * 365', '4 Balance Sheet KPIs', '0', 'Payables / TTM cost of sales x 365.')
add('DIO (days)', f'DIVIDE ( {B(103)}, -[Cost of Sales TTM] ) * 365', '4 Balance Sheet KPIs', '0', 'Inventory / TTM cost of sales x 365.')
add('Cash Conversion Cycle (days)', '[DSO (days)] + [DIO (days)] - [DPO (days)]', '4 Balance Sheet KPIs', '0')

# 6 Narrative
M_ = lambda x: money(x)
add('Title Overview', '"Adventure Works Group · FY" & ' + FYN('[Selected Month]') + ' & " month " & [Fiscal Month Of Selection] & " of 12 (closed " & FORMAT ( [As Of Month], "mmm yyyy" ) & ") · " & [Currency Label]', '6 Narrative')
add('Title Executive', '"Executive summary · " & [Selected Fiscal Year] & " " & [Period Label]', '6 Narrative')
add('Headline',
    'VAR rv = [Revenue Var % vs Budget] VAR og = [Organic Growth %] VAR ev = [EBITDA Var % vs Budget]\n'
    'RETURN [Currency Label] & " " & ' + M_('[Revenue]') + ' & " revenue, " & FORMAT ( ABS ( rv ), "0.0%" ) & IF ( rv >= 0, " above", " below" ) & " budget ("\n'
    '    & FORMAT ( og, "+0.0%;-0.0%" ) & " organic growth). EBITDA " & ' + M_('[EBITDA]') + ' & ", " & FORMAT ( ev, "+0.0%;-0.0%" ) & " vs budget."',
    '6 Narrative', None, 'One-sentence executive headline that updates with every filter.')
add('Insight Perimeter',
    'VAR nu = [Revenue New Entities] VAR ub = [Revenue Unbudgeted]\n'
    'RETURN IF ( nu > 0 || ub > 0,\n    "Entities new to the group added " & [Currency Label] & " " & ' + M_('nu') + ' & "; " & [Currency Label] & " " & ' + M_('ub') + ' & " of revenue has no budget behind it. Excluding unbudgeted entities, revenue is "\n'
    '        & FORMAT ( [Revenue Var % vs Budget (Budgeted Entities)], "+0.0%;-0.0%" ) & " vs budget.",\n    "No change in the group perimeter versus last year." )', '6 Narrative')
add('Insight Cost Absorption',
    'VAR gp = [Gross Profit Var vs Budget] VAR ox = [Operating Expenses Var vs Budget]\n'
    'RETURN IF ( gp > 0 && ox < 0,\n    "Operating expenses ran " & [Currency Label] & " " & ' + M_('-ox') + ' & " over budget, absorbing " & FORMAT ( DIVIDE ( -ox, gp ), "0%" ) & " of the gross-profit upside.",\n'
    '    IF ( ox >= 0, "Operating expenses are within budget.", "Gross profit is below budget and operating expenses are over budget." ) )', '6 Narrative')
add('Insight Outlook',
    'VAR g = [Net Income Outlook FY] - [Net Income Budget FY]\n'
    'RETURN "Full-year outlook: net income " & [Currency Label] & " " & ' + M_('[Net Income Outlook FY]') + ' & " vs budget " & ' + M_('[Net Income Budget FY]') + '\n'
    '    & " (" & FORMAT ( g / 1e6, "+#,0.0;-#,0.0" ) & "M), assuming the remaining months land on budget."', '6 Narrative')
add('Title BvA', '[Metric Name] & " · " & [Period Label] & ": " & ' + M_('[Metric Actual]') + ' & ", " & FORMAT ( ABS ( [Metric Var % vs Budget] ), "0.0%" ) & IF ( [Metric Var vs Budget] >= 0, " favourable", " unfavourable" ) & " to budget"', '6 Narrative')
add('Title BvA Trend', '[Metric Name] & " by month, " & [Selected Fiscal Year] & ": actual to " & FORMAT ( [As Of Month], "mmm yyyy" ) & ", budget as outlook thereafter"', '6 Narrative')
add('Title BvA Outlook', '"Full-year outlook " & [Currency Label] & " " & ' + M_('[Metric Outlook FY]') + ' & " vs budget " & ' + M_('[Metric Budget FY]') + ' & " (" & FORMAT ( [Metric Outlook Gap] / 1e6, "+#,0.0;-#,0.0" ) & "M)"', '6 Narrative')
add('Title Variance by Entity', '"Where the " & LOWER ( [Metric Name] ) & " variance comes from: by entity (green = favourable)"', '6 Narrative')
add('Title Variance by Department', '"Where operating expenses landed vs budget, by department: " & FORMAT ( [Operating Expenses Var vs Budget] / 1e6, "+#,0.0;-#,0.0" ) & "M in total (red = over budget)"', '6 Narrative',
    None, 'Fixed on operating expenses: in the source ledger all revenue and cost of sales post to one department, so only opex has a meaningful department split.')

# 9 Data quality
add('DQ Balance Sheet Difference', f'{B(108)} - {B(120)}', '9 Data Quality', '#,0;(#,0);0', 'Total assets minus total liabilities and equity at the selected month. Must be 0.')
add('DQ Unmapped Accounts With Activity', "COUNTROWS ( FILTER ( VALUES ( GL[AccountKey] ), NOT ( GL[AccountKey] IN VALUES ( 'Report Line Map'[AccountKey] ) ) && LOOKUPVALUE ( Account[Statement], Account[AccountKey], GL[AccountKey] ) <> \"Statistical\" ) ) + 0", '9 Data Quality', '0')
add('DQ Accounts Missing From Chart', 'COUNTROWS ( FILTER ( VALUES ( GL[AccountKey] ), ISBLANK ( LOOKUPVALUE ( Account[AccountKey], Account[AccountKey], GL[AccountKey] ) ) ) ) + 0', '9 Data Quality', '0')
add('DQ Rows Missing FX Rate', 'COUNTROWS ( FILTER ( GL, ISBLANK ( GL[Rate to CAD] ) ) ) + 0', '9 Data Quality', '0')
add('DQ Duplicates Removed', "SUM ( 'DQ File Log'[DuplicateRows] ) + 0", '9 Data Quality', '0')
add('DQ Blank Departments Fixed', "SUM ( 'DQ File Log'[MissingDepartmentRows] ) + 0", '9 Data Quality', '0')
add('DQ Files With Schema Drift', "CALCULATE ( COUNTROWS ( 'DQ File Log' ), 'DQ File Log'[SchemaDrift] = TRUE () ) + 0", '9 Data Quality', '0')
add('DQ Files Loaded', 'DISTINCTCOUNT ( GL[SourceFile] )', '9 Data Quality', '0')
add('DQ Synthetic Budget Share', 'DIVIDE ( CALCULATE ( COUNTROWS ( GL ), GL[BudgetSource] = "Synthetic" ), CALCULATE ( COUNTROWS ( GL ), GL[Scenario] = "Budget" ) )', '9 Data Quality', P)

# 6b Page titles and KPI subtexts
add('Metric Var Text', 'FORMAT ( [Metric Var vs Budget] / 1e6, "+#,0.0;-#,0.0" ) & "M (" & FORMAT ( [Metric Var % vs Budget], "+0.0%;-0.0%" ) & ") vs budget"', '6 Narrative')
add('Metric Gap Text', 'FORMAT ( [Metric Outlook Gap] / 1e6, "+#,0.0;-#,0.0" ) & "M vs full-year budget"', '6 Narrative')
add('Metric Growth Text', 'FORMAT ( [Metric Growth %], "+0.0%;-0.0%" ) & " vs prior year"', '6 Narrative')
add('Title Income Statement', '"Income statement · " & [Period Label] & " · costs negative, positive variance = favourable"', '6 Narrative')
add('Title Balance Sheet', '"Balance sheet at " & FORMAT ( [Selected Month], "mmm yyyy" ) & " vs year end " & FORMAT ( DATE ( ' + FYN('[Selected Month]') + ' - 1, 3, 1 ), "mmm yyyy" ) & " · " & [Currency Label]', '6 Narrative')
add('Title Overview Revenue', '"Net revenue by fiscal year and region · " & [Selected Fiscal Year] & " is year to date (" & FORMAT ( [As Of Month], "mmm yyyy" ) & ")"', '6 Narrative')
add('Title Revenue Bridge', '"Revenue growth vs prior year: " & FORMAT ( [Revenue Growth %], "+0.0%;-0.0%" ) & ", of which organic " & FORMAT ( [Organic Growth %], "+0.0%;-0.0%" )', '6 Narrative')
add('Title EBITDA Bridge', '"EBITDA vs budget: " & FORMAT ( [EBITDA Var vs Budget] / 1e6, "+#,0.0;-#,0.0" ) & "M, by driver"', '6 Narrative')
add('Title DQ', '"Data quality · " & [DQ Files Loaded] & " ledger files loaded · balance-sheet difference " & FORMAT ( [DQ Balance Sheet Difference], "#,0" )', '6 Narrative')

add('Insight Text', "SWITCH ( SELECTEDVALUE ( Insight[Key] ), 1, [Insight Perimeter], 2, [Insight Cost Absorption], 3, [Insight Outlook] )", '6 Narrative',
    None, 'Narrative for the topic on the row of an insight table.')
add('Entity Budget Status Color', 'IF ( [Entity Budget Status] = "Not budgeted", "#C0392B", "#1F2A37" )', '8 Formatting')

add('Net Income Outlook Gap Text', 'FORMAT ( ( [Net Income Outlook FY] - [Net Income Budget FY] ) / 1e6, "\u25b2 +#,0.0;\u25bc -#,0.0" ) & "M vs FY budget"', '6 Narrative')
add('Net Income Outlook Gap Color', 'IF ( [Net Income Outlook FY] < [Net Income Budget FY], "#C0392B", "#2E7D32" )', '8 Formatting')
CASH_PYE = LINE(101, '[Prior Year-End Balance]')
add('Cash Change Text', 'VAR c = [Cash] - ' + CASH_PYE + ' RETURN FORMAT ( c / 1e6, "\u25b2 +#,0.0;\u25bc -#,0.0" ) & "M vs March year end"', '6 Narrative')
add('Cash Change Color', 'IF ( [Cash] < ' + CASH_PYE + ', "#C0392B", "#2E7D32" )', '8 Formatting')
add('Revenue (M)', 'DIVIDE ( [Revenue], 1e6 )', '3 KPIs\\Revenue', '#,0.0', 'Net revenue in millions, for compact tables.')


# ======================================================================== v2: theme, layout, insights
# Helpers to redefine measures declared above, so each change stays next to its reason.
def redefine(name, expr=None, fmt=None, desc=None, folder=None):
    for m in MEAS:
        if m['name'] == name:
            if expr is not None: m['expr'] = expr
            if fmt is not None: m['fmt'] = fmt
            if desc is not None: m['desc'] = desc
            if folder is not None: m['folder'] = folder
            return
    raise KeyError(name)

FK = '#,0,;(#,0,);-'          # thousands: board packs read K, not 8-digit units
MT = lambda x: money(x, 'signed')     # variance / delta text: +$0.6M, -$1.2M
MU = lambda x: money(x)               # value text: $36.2M, ($1.2M)

# ---- new tables: theme selector, narrative text, extra insight topics
M_THEME = m_table([('Mode', 'text'), ('Sort', 'Int64.Type')], [('Light', 1), ('Dark', 2)])
STORY_ROWS = [
    ('Overview', 1, 'Who we are', 'Designs and sells performance bicycles, components and riding apparel through dealers and its own online store. Canadian parent: reports in CAD; fiscal year 1 April to 31 March.'),
    ('Overview', 2, 'FY2025', 'North American core: five US sales divisions and Canada.'),
    ('Overview', 3, 'FY2026', 'European entry: France (50%) and Germany (25%) joined in April 2025, after the budget was set. An ERP migration left 3% of August 2025 postings without a department.'),
    ('Overview', 4, 'FY2027', 'Pacific entry: an Australian joint venture (37.5% group interest) began trading in April 2026, outside the budget. A Software Subscriptions account opened; September 2026 was the first ERP v2 export.'),
    ('Overview', 5, 'Four questions', '1 Is growth organic or bought?  2 Is cost growth eating the upside?  3 Where will the year land?  4 Is the balance sheet funding growth?'),
    ('Overview', 6, 'Disclosure', 'Fictional company on Microsoft AdventureWorksDW (MIT licence), re-dated. FY2026-FY2028 budgets are synthetic and generated by a documented script.'),
    ('DQ', 1, 'Distribution', 'Monthly group revenue is close to normal (Shapiro-Wilk p = 0.52); ledger lines are heavily skewed, so outliers use median and MAD, not mean and standard deviation.'),
    ('DQ', 2, 'Correlation', 'Revenue and cost of sales move almost one-for-one (Spearman 0.94); operating expenses less so (0.66), so margin is decided below gross profit.'),
    ('DQ', 3, 'Integrity', 'Every injected issue was detected and treated; the balance sheet balances in every month; no rows lack an FX rate.'),
    ('DQ', 4, 'Benford', 'First-digit distribution conforms (Nigrini MAD 0.0068, acceptable).'),
    ('DQ', 5, 'Known gaps', 'Equity roll-forward does not reconcile in the source data (retained earnings vs net income); intercompany balances are not eliminated.'),
]
M_STORY = m_table([('Page', 'text'), ('Sort', 'Int64.Type'), ('Section', 'text'), ('Text', 'text')], STORY_ROWS)
for t in TABLES:
    if t['name'] == 'Insight':
        t['m'] = m_table([('Key', 'Int64.Type'), ('Topic', 'text')],
                         [(1, 'Growth quality'), (2, 'Cost absorption'), (3, 'Full-year outlook'), (4, 'People cost')])
TABLES.insert(len(TABLES) - 1, dict(name='Theme Mode', desc='Selector for the light/dark toggle; every colour measure reads it.', m=M_THEME,
                                    cols=[('Mode', 'string', {'sortBy': 'Sort'}), ('Sort', 'int64', {'hidden': 1})]))
TABLES.insert(len(TABLES) - 1, dict(name='Story', desc='Static narrative shown in themed tables (text boxes cannot change colour with the theme).', m=M_STORY,
                                    cols=[('Page', 'string', {'hidden': 1}), ('Sort', 'int64', {'hidden': 1}), ('Section', 'string', {'sortBy': 'Sort'}), ('Text', 'string', {})]))

# ---- 10 Theme: one palette, two modes; every colour in the report comes from here
PALETTE = {  # name: (light, dark)
    'Page': ('#F4F6F9', '#0B1220'), 'Panel': ('#FFFFFF', '#162032'), 'Side': ('#E9EDF3', '#101A2C'),
    'Text': ('#1F2A37', '#E5E9F0'), 'Muted': ('#5B6676', '#9AA7B8'), 'Accent': ('#1F3A5F', '#8DB3D9'),
    'Line': ('#D5DBE3', '#2A3850'), 'Good': ('#2E7D32', '#5CC98A'), 'Bad': ('#C0392B', '#F07167'),
    'Warn': ('#B26A00', '#F2B35E'), 'Subtotal': ('#EEF1F5', '#1E2B42'), 'Total': ('#DCE3EC', '#26375A'),
    'Button': ('#FFFFFF', '#1E2B42'), 'Selected': ('#1F3A5F', '#8DB3D9'), 'Selected Text': ('#FFFFFF', '#0B1220'),
}
PALETTE.update({
    'Accent': ('#2F5D9F', '#7FB0E6'), 'Accent Soft': ('#E6EEF8', '#1E3350'), 'Track': ('#E5E9F0', '#22314A'),
    'Page': ('#F1F4F8', '#0B1220'), 'Panel': ('#FFFFFF', '#141D2E'),
    'Sidebar': ('#0F2340', '#070D1A'), 'Sidebar Text': ('#E8EDF4', '#E8EDF4'), 'Sidebar Muted': ('#8FA3BF', '#7F8EA6'),
    'Sidebar Active': ('#23497A', '#1E3350'), 'Title': ('#14213D', '#F1F5F9'),
})
add('Is Dark', 'SELECTEDVALUE ( \'Theme Mode\'[Mode], "Light" ) = "Dark"', '10 Theme', None, 'True when the Dark tile of the theme toggle is selected.')
for k, (lt, dk) in PALETTE.items():
    add(f'Col {k}', f'IF ( [Is Dark], "{dk}", "{lt}" )', '10 Theme', None, f'Theme colour "{k}": {lt} light / {dk} dark.')
# rewire every existing formatting measure to the palette
for m in MEAS:
    if m['folder'] == '8 Formatting':
        m['expr'] = m['expr'].replace('"#C0392B"', '[Col Bad]').replace('"#2E7D32"', '[Col Good]')
redefine('Line Row Background', "IF ( HASONEVALUE ( 'Report Line'[LineKey] ), SWITCH ( SELECTEDVALUE ( 'Report Line'[LineType] ), \"Subtotal\", [Col Subtotal], \"Total\", [Col Total], [Col Panel] ), [Col Panel] )")

# ---- 10 Layout: greeting, filter context, footers
add('Greeting', '''VAR u = USERPRINCIPALNAME ()
VAR a = IF ( CONTAINSSTRING ( u, "@" ), LEFT ( u, FIND ( "@", u ) - 1 ), IF ( CONTAINSSTRING ( u, "\\" ), MID ( u, FIND ( "\\", u ) + 1, 100 ), u ) )
VAR f = IF ( CONTAINSSTRING ( a, "." ), LEFT ( a, FIND ( ".", a ) - 1 ), a )
RETURN "Hello, " & IF ( LEN ( f ) = 0, "guest", UPPER ( LEFT ( f, 1 ) ) & LOWER ( MID ( f, 2, 40 ) ) )''', '10 Layout', None,
    'First name only (text before @, \\ or .); never the full sign-in, domain or machine name. Anonymous (Publish to web) viewers see "guest".')
add('Brand', '"CFO Performance Pack"', '10 Layout')
LST = lambda col, allx: f'VAR n = COUNTROWS ( VALUES ( {col} ) ) RETURN IF ( NOT ISFILTERED ( {col} ), "{allx}", IF ( n <= 2, CONCATENATEX ( VALUES ( {col} ), {col}, ", " ), n & " selected" ) )'
add('Ctx Period', '[Selected Fiscal Year] & " " & SELECTEDVALUE ( \'Period View\'[View], "YTD" ) & " " & FORMAT ( [Selected Month], "mmm yy" )', '10 Layout')
add('Ctx Currency', '[Currency Label] & IF ( [Currency Label] = "USD", " (translated via CAD)", "" )', '10 Layout')
add('Ctx Region', LST('Entity[Region]', 'All regions'), '10 Layout')
add('Ctx Entity', LST('Entity[EntityName]', 'All entities'), '10 Layout')
add('Ctx Department', LST('Department[DepartmentName]', 'All departments'), '10 Layout')
FOOT = '"Source: AdventureWorksDW (MIT), re-dated; FY2026-28 budgets synthetic · FX Bank of Canada: P&L monthly avg, BS month end, budget prior-FY avg · Closed " & FORMAT ( [As Of Month], "mmm yyyy" )'
for pg, extra in [('Overview', ' · Group % = effective ownership'), ('Executive', ' · Var % shown only when actual and budget share a sign'),
                  ('BvA', ' · Under-budgeted = actual > 2x budget'), ('IS', ' · CAD/USD thousands; costs negative, + = favourable'),
                  ('BS', ' · Equity roll-forward not reconciled in source data'), ('DQ', ' · Counts recompute on every refresh')]:
    add(f'Footer {pg}', FOOT + f' & "{extra}"', '10 Layout')

# ---- safe variance %: blank (not nonsense) when actual and base have different signs
for n in KPI:
    redefine(f'{n} Var % vs Budget', f'IF ( [{n}] * [{n} Budget] > 0, DIVIDE ( [{n}] - [{n} Budget], ABS ( [{n} Budget] ) ) )')
    redefine(f'{n} Growth %', f'IF ( [{n}] * [{n} PY] > 0, DIVIDE ( [{n}] - [{n} PY], ABS ( [{n} PY] ) ) )')
    redefine(f'{n} vs Budget Text', f'VAR v = [{n} Var % vs Budget] VAR g = [{n} Growth %] RETURN IF ( ISBLANK ( v ), "n.m.", FORMAT ( v, "▲ 0.0%;▼ 0.0%;0.0%" ) ) & " vs Bud  ·  " & IF ( ISBLANK ( g ), "n.m.", FORMAT ( g, "▲ 0.0%;▼ 0.0%;0.0%" ) ) & " vs PY"')
redefine('Line Var % vs Budget', 'IF ( [Line Actual] * [Line Budget] > 0, DIVIDE ( [Line Actual] - [Line Budget], ABS ( [Line Budget] ) ) )')
redefine('Line Growth %', 'IF ( [Line Actual] * [Line Prior Year] > 0, DIVIDE ( [Line Actual] - [Line Prior Year], ABS ( [Line Prior Year] ) ) )')
redefine('Metric Var % vs Budget', 'IF ( [Metric Actual] * [Metric Budget] > 0, DIVIDE ( [Metric Actual] - [Metric Budget], ABS ( [Metric Budget] ) ) )')
redefine('Metric Growth %', 'IF ( [Metric Actual] * [Metric PY] > 0, DIVIDE ( [Metric Actual] - [Metric PY], ABS ( [Metric PY] ) ) )')
for n in ['Line Actual', 'Line Budget', 'Line Prior Year', 'Line Var vs Budget', 'Line Outlook FY', 'Line Budget FY',
          'Line Closing Balance', 'Line Prior Year-End Balance', 'Line Balance Change']:
    redefine(n, fmt=FK)

# ---- core vs newer regions (the real headline)
add('Core Region', '''VAR t = ADDCOLUMNS ( ALL ( Entity[Region] ), "@f", VAR r = Entity[Region] RETURN CALCULATE ( MIN ( GL[Month] ), REMOVEFILTERS (), GL[Scenario] = "Actual", Entity[Region] = r ) )
RETURN MAXX ( TOPN ( 1, FILTER ( t, NOT ISBLANK ( [@f] ) ), [@f], ASC, Entity[Region], ASC ), Entity[Region] )''', '3 KPIs\\Perimeter', None,
    'The region that has reported longest: the like-for-like core against which newer regions are judged.')
for n in ('Revenue', 'EBITDA'):
    add(f'{n} Var Core', f'VAR r = [Core Region] RETURN CALCULATE ( [{n} Var vs Budget], KEEPFILTERS ( Entity[Region] = r ) )', '3 KPIs\\Perimeter', F)
    add(f'{n} Var % Core', f'VAR r = [Core Region] RETURN CALCULATE ( [{n} Var % vs Budget], KEEPFILTERS ( Entity[Region] = r ) )', '3 KPIs\\Perimeter', PTS)
redefine('Headline', '''VAR core = [Core Region] VAR rv = [Revenue Var vs Budget] VAR rc = [Revenue Var Core] VAR share = DIVIDE ( rv - rc, rv ) VAR ec = [EBITDA Var Core]
RETURN [Currency Label] & " " & ''' + MU('[Revenue]') + ''' & " revenue, " & FORMAT ( [Revenue Var % vs Budget], "+0.0%;-0.0%" ) & " vs budget. "
    & IF ( ISBLANK ( rc ), "",
        "Core " & core & " " & FORMAT ( [Revenue Var % Core], "+0.0%;-0.0%" ) & IF ( rv > 0 && share > 0.5, "; newer regions deliver " & FORMAT ( share, "0%" ) & " of the beat", "" ) & ". " )
    & "EBITDA " & FORMAT ( [EBITDA Var % vs Budget], "+0.0%;-0.0%" ) & " vs budget" & IF ( ISBLANK ( ec ), ".", ", " & core & " " & ''' + MT('ec') + ''' & "." )''',
          desc='Executive headline: total result, then the core region on its own, so newer, unbudgeted entities cannot masquerade as outperformance.')

# ---- budget credibility
redefine('Entity Budget Status', '''IF ( NOT ISBLANK ( [Entity First Month] ),
    IF ( ISBLANK ( [Revenue Budget] ), "Not budgeted", IF ( DIVIDE ( [Revenue], [Revenue Budget] ) > 2, "Under-budgeted", "Budgeted" ) ) )''',
          desc='Not budgeted = no budget for the period; Under-budgeted = actual revenue more than twice budget (budget not credible).')
redefine('Entity Budget Status Color', 'SWITCH ( [Entity Budget Status], "Not budgeted", [Col Bad], "Under-budgeted", [Col Warn], [Col Text] )')
add('Revenue Var Credible', 'SUMX ( VALUES ( Entity[EntityKey] ), IF ( NOT ISBLANK ( [Revenue Budget] ) && DIVIDE ( [Revenue], [Revenue Budget] ) <= 2, [Revenue Var vs Budget] ) )',
    '3 KPIs\\Perimeter', F, 'Revenue variance from entities whose budget is credible (actual within 2x budget).')

# ---- top-5 exceptions (entity x P&L detail line)
add('Exception Rank', '''IF ( HASONEVALUE ( Entity[EntityName] ) && HASONEVALUE ( 'Report Line'[LineKey] ) && SELECTEDVALUE ( 'Report Line'[LineType] ) = "Detail",
    VAR cur = ABS ( [Line Var vs Budget] )
    VAR grid = CROSSJOIN ( ALLSELECTED ( Entity[EntityName] ),
        CALCULATETABLE ( VALUES ( 'Report Line'[LineKey] ), REMOVEFILTERS ( 'Report Line' ), 'Report Line'[LineType] = "Detail", 'Report Line'[Statement] = "Income Statement" ) )
    RETURN IF ( NOT ISBLANK ( cur ), RANKX ( grid, CALCULATE ( ABS ( [Line Var vs Budget] ), REMOVEFILTERS ( 'Report Line'[LineName] ) ), cur, DESC, Dense ) ) )''',
    '7 Exceptions', '0', 'Rank of the absolute budget variance across every entity x P&L detail line in the current selection.')
add('Exception Var', 'IF ( [Exception Rank] <= 5, [Line Var vs Budget] )', '7 Exceptions', FK)
add('Exception Var %', 'IF ( [Exception Rank] <= 5, [Line Var % vs Budget] )', '7 Exceptions', P)
add('Exception Actual', 'IF ( [Exception Rank] <= 5, [Line Actual] )', '7 Exceptions', FK)
add('Exception Rank Shown', 'IF ( [Exception Rank] <= 5, [Exception Rank] )', '7 Exceptions', '0')
add('Exception Color', 'IF ( [Exception Var] < 0, [Col Bad], [Col Good] )', '8 Formatting')

# ---- people cost
SAL = lambda base: LINE(6, base)
add('Headcount', 'VAR m = [Selected Month] RETURN CALCULATE ( SUM ( GL[AmountLC] ), REMOVEFILTERS ( \'Date\' ), \'Date\'[Month] = m, GL[Scenario] = "Actual", Account[AccountKey] = 96 )', '3 KPIs\\People', '#,0',
    'Closing headcount at the selected month (statistical account 96).')
add('Headcount PY', 'VAR m = EDATE ( [Selected Month], -12 ) RETURN CALCULATE ( SUM ( GL[AmountLC] ), REMOVEFILTERS ( \'Date\' ), \'Date\'[Month] = m, GL[Scenario] = "Actual", Account[AccountKey] = 96 )', '3 KPIs\\People', '#,0')
add('Salaries Var vs Budget', SAL('[Actual (Period)]') + ' - ' + SAL('[Budget (Period)]'), '3 KPIs\\People', F)
add('Salary Cost per Head', 'DIVIDE ( -' + SAL('[Actual (Period)]') + ', [Headcount] )', '3 KPIs\\People', F, 'Salaries & benefits for the period / closing headcount.')
add('Salary Cost per Head PY', 'DIVIDE ( -' + SAL('[Prior Year (Period)]') + ', [Headcount PY] )', '3 KPIs\\People', F)
add('Insight People Cost', '''VAR sv = [Salaries Var vs Budget] VAR ov = [Operating Expenses Var vs Budget] VAR hc = [Headcount] VAR hp = [Headcount PY]
VAR c = [Salary Cost per Head] VAR cp = [Salary Cost per Head PY]
RETURN "Salaries & benefits ran " & ''' + MU('ABS ( sv )') + ''' & IF ( sv < 0, " over", " under" ) & " budget" & IF ( ov < 0 && sv < 0, ", " & FORMAT ( DIVIDE ( sv, ov ), "0%" ) & " of the opex overrun", "" ) & ". Headcount "
    & FORMAT ( hc, "#,0" ) & " (" & FORMAT ( DIVIDE ( hc, hp ) - 1, "+0%;-0%" ) & " vs PY); salary cost per head " & FORMAT ( DIVIDE ( c, cp ) - 1, "+0.0%;-0.0%" ) & " vs PY."''', '6 Narrative')
redefine('Insight Text', "SWITCH ( SELECTEDVALUE ( Insight[Key] ), 1, [Insight Perimeter], 2, [Insight Cost Absorption], 3, [Insight Outlook], 4, [Insight People Cost] )")

# ---- run-rate outlook (a range, not a single budget-based number)
add('Metric Outlook Run-Rate', '''VAR a = ''' + MET('[Actual YTD]') + ''' VAR b = ''' + MET('[Budget YTD]') + '''
RETURN a + ( [Metric Budget FY] - b ) * DIVIDE ( a, b )''', '5 Metric Selector', F,
    'Outlook if the remaining months beat budget by the same ratio as the year to date.')

# ---- dynamic visual titles (VT) and insight subtitles (Sub)
VT = '6 Narrative\\Visual titles'
SB = '6 Narrative\\Subtitles'
PL = '[Period Label]'
FYS = FYN('[Selected Month]')
add('VT Story', '"Adventure Works Group at a glance · " & [Selected Fiscal Year]', VT)
add('VT Revenue by FY', '"Net revenue by fiscal year and region · " & [Currency Label]', VT)
add('VT Entities', '"Group perimeter and budget coverage · " & [Selected Fiscal Year]', VT)
add('VT Insights', '"What the numbers say · " & ' + PL, VT)
add('VT Exceptions', '"Top 5 variances to budget (entity x P&L line) · " & ' + PL, VT)
add('VT Exec Entity', '"Revenue variance to budget by entity · " & ' + PL, VT)
add('VT PL', '"Management P&L · " & ' + PL + ' & " · thousands"', VT)
add('VT BS', '"Balance sheet at " & FORMAT ( [Selected Month], "mmm yyyy" ) & " vs " & FORMAT ( DATE ( ' + FYS + ' - 1, 3, 1 ), "mmm yyyy" ) & " · " & [Currency Label] & " thousands"', VT)
add('VT Cash', '"Cash and trade working capital by month end · " & [Currency Label]', VT)
add('VT DQ Injected', '"Injected vs detected source issues · " & COUNTROWS ( \'DQ Injection Log\' ) & " injections"', VT)
add('VT DQ Files', '"Every source file profiled on refresh · " & [DQ Files Loaded] & " ledger files"', VT)
add('VT EDA', '"What the exploratory analysis found"', VT)

add('Sub Story', '"Story and context behind the numbers; the CFO\'s four questions map to the next pages."', SB)
add('Sub Revenue Mix', '''VAR core = [Core Region] VAR fy = ''' + FYS + '''
VAR cur = CALCULATE ( [Revenue Actual (in context)], REMOVEFILTERS ( 'Date' ), 'Date'[Fiscal Year Number] = fy, 'Date'[IsClosed] = TRUE () )
VAR curCore = CALCULATE ( [Revenue Actual (in context)], REMOVEFILTERS ( 'Date' ), 'Date'[Fiscal Year Number] = fy, 'Date'[IsClosed] = TRUE (), KEEPFILTERS ( Entity[Region] = core ) )
VAR py = CALCULATE ( [Revenue Actual (in context)], REMOVEFILTERS ( 'Date' ), 'Date'[Fiscal Year Number] = fy - 1 )
VAR pyCore = CALCULATE ( [Revenue Actual (in context)], REMOVEFILTERS ( 'Date' ), 'Date'[Fiscal Year Number] = fy - 1, KEEPFILTERS ( Entity[Region] = core ) )
RETURN "Regions outside " & core & " are " & FORMAT ( 1 - DIVIDE ( curCore, cur ), "0%" ) & " of FY" & fy & " revenue to date (FY" & ( fy - 1 ) & ": " & FORMAT ( 1 - DIVIDE ( pyCore, py ), "0%" ) & ")."''', SB)
add('Sub Entities', '''VAR t = FILTER ( ADDCOLUMNS ( VALUES ( Entity[EntityName] ), "@s", [Entity Budget Status] ), NOT ISBLANK ( [@s] ) )
VAR nb = COUNTROWS ( FILTER ( t, [@s] = "Not budgeted" ) ) + 0 VAR ub = COUNTROWS ( FILTER ( t, [@s] = "Under-budgeted" ) ) + 0
RETURN COUNTROWS ( t ) & " reporting entities: " & nb & " not budgeted, " & ub & " under-budgeted (actual > 2x budget)."''', SB)
add('Sub Insights', '"Written by DAX from the numbers on this page; rewrites itself for every filter."', SB)
add('Sub Revenue Bridge', '''VAR o = [Revenue Like-for-Like] - [Revenue PY] VAR nw = [Revenue New Entities]
RETURN FORMAT ( DIVIDE ( o, o + nw ), "0%" ) & " of the growth is organic (entities trading in both years); " & FORMAT ( DIVIDE ( nw, o + nw ), "0%" ) & " comes from entities new this year."''', SB)
add('Sub EBITDA Bridge', '''VAR r = [Revenue Var vs Budget] VAR c = [Cost of Sales Var vs Budget] VAR o = [Operating Expenses Var vs Budget]
VAR worst = MIN ( r, MIN ( c, o ) )
VAR nm = IF ( worst = o, "Operating expenses", IF ( worst = c, "Cost of sales", "Revenue" ) )
RETURN IF ( worst < 0, nm & " are the largest drag (" & ''' + MT('worst') + ''' & ")" & IF ( worst = o, "; salaries are " & FORMAT ( DIVIDE ( [Salaries Var vs Budget], o ), "0%" ) & " of it.", "." ), "Every driver is favourable to budget." )''', SB)
add('Sub Exceptions', '''VAR t = FILTER ( ADDCOLUMNS ( CROSSJOIN ( VALUES ( Entity[EntityName] ), CALCULATETABLE ( VALUES ( 'Report Line'[LineKey] ), REMOVEFILTERS ( 'Report Line' ), 'Report Line'[LineType] = "Detail", 'Report Line'[Statement] = "Income Statement" ) ), "@v", [Line Var vs Budget] ), NOT ISBLANK ( [@v] ) )
VAR top5 = TOPN ( 5, t, ABS ( [@v] ), DESC )
VAR bad = COUNTROWS ( FILTER ( top5, [@v] < 0 ) ) + 0
RETURN bad & " of the 5 largest variances " & IF ( bad = 1, "is", "are" ) & " unfavourable; together they total " & ''' + MT('SUMX ( top5, [@v] )') + ''' & "."''', SB)
add('Metric Actual (in context)', MET('[Actual]'), '5 Metric Selector', F)
add('Metric Budget (in context)', MET('[Budget]'), '5 Metric Selector', F)
MONTHS = '''VAR sel = [Selected Month] VAR fy = ''' + FYS + '''
VAR ms = SELECTCOLUMNS ( FILTER ( ALL ( 'Date'[Month] ), 'Date'[Month] >= DATE ( fy - 1, 4, 1 ) && 'Date'[Month] <= sel ), "@m", 'Date'[Month] )
VAR t = ADDCOLUMNS ( ms, "@d", VAR m = [@m] RETURN CALCULATE ( [Metric Actual (in context)] - [Metric Budget (in context)], REMOVEFILTERS ( 'Date' ), 'Date'[Month] = m ) )
VAR beat = COUNTROWS ( FILTER ( t, [@d] > 0 ) ) + 0
VAR best = TOPN ( 1, t, [@d], DESC )
'''
add('Sub Monthly', MONTHS + '''RETURN [Metric Name] & " beat budget in " & beat & " of " & COUNTROWS ( t ) & " closed months; strongest " & FORMAT ( MAXX ( best, [@m] ), "mmm yyyy" ) & " (" & ''' + MT('MAXX ( best, [@d] )') + ''' & ")."''', SB)
add('Sub Cumulative', '''VAR g = [Metric Outlook Gap] VAR rr = [Metric Outlook Run-Rate]
RETURN "Budget-based outlook " & ''' + MT('g') + ''' & " vs full-year budget (" & FORMAT ( DIVIDE ( g, ABS ( [Metric Budget FY] ) ), "+0.0%;-0.0%" ) & "). At the year-to-date run rate it would land at " & ''' + MU('rr') + ''' & "."''', SB)
add('Sub Entity Variance', '''VAR t = FILTER ( ADDCOLUMNS ( VALUES ( Entity[EntityName] ), "@s", [Entity Budget Status] ), [@s] IN { "Not budgeted", "Under-budgeted" } )
RETURN IF ( COUNTROWS ( t ) > 0,
    CONCATENATEX ( t, Entity[EntityName], ", " ) & " have no or a non-credible budget, so their green is a budgeting gap, not outperformance. Entities with credible budgets: " & ''' + MT('[Revenue Var Credible]') + ''' & ".",
    "All entities have credible budgets." )''', SB)
add('Sub Department', '''VAR t = ADDCOLUMNS ( VALUES ( Department[DepartmentName] ), "@v", [Operating Expenses Var vs Budget] )
VAR worst2 = TOPN ( 2, FILTER ( t, [@v] < 0 ), [@v], ASC )
VAR o = [Operating Expenses Var vs Budget]
RETURN IF ( o < 0, CONCATENATEX ( worst2, Department[DepartmentName], " and " ) & " account for " & FORMAT ( DIVIDE ( SUMX ( worst2, [@v] ), o ), "0%" ) & " of the overrun.", "Operating expenses are within budget." )''', SB)
PLT = '''VAR t = ADDCOLUMNS ( CALCULATETABLE ( VALUES ( 'Report Line'[LineKey] ), REMOVEFILTERS ( 'Report Line' ), 'Report Line'[LineType] = "Detail", 'Report Line'[Statement] = "{s}" ),
    "@v", [{m}], "@n", LOOKUPVALUE ( 'Report Line'[LineName], 'Report Line'[LineKey], 'Report Line'[LineKey] ) )
'''
add('Sub PL', PLT.format(s='Income Statement', m='Line Var vs Budget') + '''VAR b = TOPN ( 1, t, [@v], DESC ) VAR w = TOPN ( 1, t, [@v], ASC )
RETURN "Largest favourable line: " & MAXX ( b, [@n] ) & " (" & ''' + MT('MAXX ( b, [@v] )') + ''' & "); largest unfavourable: " & MAXX ( w, [@n] ) & " (" & ''' + MT('MAXX ( w, [@v] )') + ''' & ")."''', SB)
add('Sub BS', PLT.format(s='Balance Sheet', m='Line Balance Change') + '''VAR top3 = TOPN ( 3, t, ABS ( [@v] ), DESC )
RETURN "Largest moves since year end: " & CONCATENATEX ( top3, [@n] & " " & ''' + MT('[@v]') + ''', ", ", ABS ( [@v] ), DESC ) & "."''', SB)
CASHCHG = LINE(101, '[Closing Balance]') + ' - ' + LINE(101, '[Prior Year-End Balance]')
ARCHG = LINE(102, '[Closing Balance]') + ' - ' + LINE(102, '[Prior Year-End Balance]')
add('Sub Cash', f'''VAR c = {CASHCHG} VAR r = {ARCHG}
RETURN "Since the March year end, cash " & ''' + MT('c') + ''' & " and receivables " & ''' + MT('r') + ''' & IF ( c < 0 && r > 0, ": growth is being financed through customer credit.", "." )''', SB)
add('Sub DQ Injected', '''VAR d = SUMX ( FILTER ( 'DQ Injection Log', 'DQ Injection Log'[Issue] = "Exact duplicate rows" ), 'DQ Injection Log'[RowsAffected] )
VAR b = SUMX ( FILTER ( 'DQ Injection Log', 'DQ Injection Log'[Issue] = "Missing DepartmentKey" ), 'DQ Injection Log'[RowsAffected] )
RETURN "Detected vs injected: duplicates " & [DQ Duplicates Removed] & "/" & d & ", blank departments " & [DQ Blank Departments Fixed] & "/" & b & ", schema drift " & [DQ Files With Schema Drift] & "/1 file."''', SB)
add('Sub DQ Files', '''"Duplicates in " & COUNTROWS ( FILTER ( 'DQ File Log', 'DQ File Log'[DuplicateRows] > 0 ) ) & " files, blank departments in " & COUNTROWS ( FILTER ( 'DQ File Log', 'DQ File Log'[MissingDepartmentRows] > 0 ) ) & ", schema drift in " & [DQ Files With Schema Drift] & "; the rest are clean."''', SB)
add('Sub EDA', '"Independent pandas analysis (docs/eda); its totals reconcile to this model to the dollar."', SB)

# ---- page headers (PT = title, PS = insight subtitle)
PH = '6 Narrative\\Page headers'
add('PT Overview', '"Company Overview · " & [Selected Fiscal Year] & " month " & [Fiscal Month Of Selection] & " of 12 · " & [Currency Label]', PH)
add('PS Overview', '''[Entities Reporting] & " entities across " & COUNTROWS ( FILTER ( VALUES ( Entity[Region] ), NOT ISBLANK ( [Revenue] ) ) ) & " regions; revenue " & ''' + MU('[Revenue]') + ''' & " " & FORMAT ( [Revenue Growth %], "+0.0%;-0.0%" ) & " vs PY, of which organic " & FORMAT ( [Organic Growth %], "+0.0%;-0.0%" ) & "."''', PH)
add('PT Executive', '"Executive Summary · " & ' + PL, PH)
add('PT BvA', '"Budget vs Actual · " & [Metric Name] & " · " & ' + PL, PH)
add('PT IS', '"Income Statement · " & ' + PL, PH)
add('PS IS', '"Gross margin " & FORMAT ( [Gross Profit Margin %], "0.0%" ) & " (" & FORMAT ( [Gross Profit Margin pts vs Budget] * 100, "+0.0;-0.0" ) & " pts vs budget) · EBITDA margin " & FORMAT ( [EBITDA Margin %], "0.0%" ) & " · opex " & FORMAT ( [OpEx % of Revenue], "0.0%" ) & " of revenue."', PH)
add('PT BS', '"Balance Sheet & Cash · " & FORMAT ( [Selected Month], "mmm yyyy" ) & " · " & [Currency Label]', PH)
add('PT DQ', '"Data Quality & About · " & [DQ Files Loaded] & " ledger files"', PH)
add('PS DQ', '"Balance-sheet difference " & FORMAT ( [DQ Balance Sheet Difference], "#,0" ) & " · rows missing FX " & [DQ Rows Missing FX Rate] & " · accounts not in chart " & [DQ Accounts Missing From Chart] & " · synthetic budget rows " & FORMAT ( [DQ Synthetic Budget Share], "0%" ) & "."', PH)

add('PS Executive', '"Revenue " & FORMAT ( [Revenue Var % vs Budget], "+0.0%;-0.0%" ) & " vs budget · EBITDA " & FORMAT ( [EBITDA Var % vs Budget], "+0.0%;-0.0%" ) & " · net income outlook " & ' + MT('[Net Income Outlook FY] - [Net Income Budget FY]') + ' & " vs FY budget"', PH)
redefine('PS Overview', '[Entities Reporting] & " entities, " & COUNTROWS ( FILTER ( VALUES ( Entity[Region] ), NOT ISBLANK ( [Revenue] ) ) ) & " regions · revenue " & ' + MU('[Revenue]') + ' & " " & FORMAT ( [Revenue Growth %], "+0.0%;-0.0%" ) & " vs PY (organic " & FORMAT ( [Organic Growth %], "+0.0%;-0.0%" ) & ")"')
add('Sub Cash Trend', """VAR ms = FILTER ( ALL ( 'Date'[Month] ), 'Date'[Month] <= [As Of Month] )
VAR t = ADDCOLUMNS ( ms, "@c", VAR m = 'Date'[Month] RETURN CALCULATE ( [Cash Balance (month)], REMOVEFILTERS ( 'Date' ), 'Date'[Month] = m ) )
VAR hi = TOPN ( 1, FILTER ( t, NOT ISBLANK ( [@c] ) ), [@c], DESC ) VAR lo = TOPN ( 1, FILTER ( t, NOT ISBLANK ( [@c] ) ), [@c], ASC )
RETURN "Month-end cash ranged " & """ + MU('MAXX ( lo, [@c] )') + """ & " (" & FORMAT ( MAXX ( lo, 'Date'[Month] ), "mmm yy" ) & ") to " & """ + MU('MAXX ( hi, [@c] )') + """ & " (" & FORMAT ( MAXX ( hi, 'Date'[Month] ), "mmm yy" ) & "); it moves with working capital, not profit." """, SB)

add('Lbl Current View', '"Current view"', '10 Layout')
for k in ['Period', 'Currency', 'Region', 'Entity', 'Department']:
    add(f'Ctx Line {k}', f'"{k}: " & [Ctx {k}]', '10 Layout')


# ======================================================================== v3: reference-style frame and KPI cards
# refresh timestamp: a one-row calculated table re-evaluated on every refresh
TABLES.insert(len(TABLES) - 1, dict(name='Refresh Info', hidden=1, desc='One row stamped with the UTC time of the last refresh.',
                                    dax='ROW ( "Refreshed At", UTCNOW () )', cols=[('Refreshed At', 'dateTime', {})]))
add('Last Refreshed', '"Refreshed " & FORMAT ( MAX ( \'Refresh Info\'[Refreshed At] ), "dd mmm yyyy hh:nn" ) & " UTC · books closed " & FORMAT ( [As Of Month], "mmm yyyy" )', '10 Layout')
add('Brand Sub', '"Adventure Works Group"', '10 Layout')
add('Tagline', '"Every number traces to the ledger."', '10 Layout')
add('Lbl Filters', '"FILTERS"', '10 Layout')
add('Year Elapsed %', 'DIVIDE ( [Fiscal Month Of Selection], 12 )', '1 Period (fiscal)', '0%', 'Share of the fiscal year closed at the selected month.')
add('Footer Note 1', '"1  One definition per metric: hover a KPI label for its definition; click it for the DAX."', '10 Layout')
add('Footer Note 2', '"2  Described in the model: every measure has a description (docs/01-semantic-model.md)."', '10 Layout')

# KPI value text (left-aligned cards need text), sparklines and full-year progress
def kv_expr(name):
    """KPI card value as text, formatted by the measure's own format string (money, percentage, ratio or count)."""
    fmt = next(m.get('fmt') for m in MEAS if m['name'] == name)
    if fmt == F:
        return money(f'[{name}]')
    if fmt in (P, '0%'):
        return f'FORMAT ( [{name}], "0.0%" )'
    if fmt == '0.00':
        return f'FORMAT ( [{name}], "0.00" ) & "x"'
    return f'FORMAT ( [{name}], "#,0" )'
KV_LIST = ['Revenue', 'Gross Profit Margin %', 'EBITDA', 'Net Income', 'Net Income Outlook FY', 'Cash', 'Organic Growth %', 'Revenue New Entities',
           'Entities Reporting', 'Metric Actual', 'Metric Budget', 'Metric PY', 'Metric Outlook FY']
for n in KV_LIST:
    add(f'KV {n}', kv_expr(n), '11 KPI Cards')
SPARK_KEYS = {'Revenue': 3, 'Gross Profit': 5, 'EBITDA': 13, 'Net Income': 20}
for n, key in SPARK_KEYS.items():
    add(f'{n} Spark', LINE(key, '[Monthly Actual (Selected FY)]'), '11 KPI Cards', F, f'Monthly {n.lower()} for the selected fiscal year (sparkline).')
add('Cash Spark', f"VAR fy = {FYS} VAR m = MAX ( 'Date'[Month] ) RETURN IF ( HASONEVALUE ( 'Date'[Fiscal Month Number] ) && m <= [Selected Month] && MAX ( 'Date'[Fiscal Year Number] ) = fy, [Cash Balance (month)] )", '11 KPI Cards', F)
add('Gross Margin Spark', "DIVIDE ( [Gross Profit Spark], [Revenue Spark] )", '11 KPI Cards', P)
for n in ('Revenue', 'EBITDA', 'Net Income'):
    key = KPI[n]
    add(f'{n} FY Progress', 'DIVIDE ( ' + LINE(key, '[Actual YTD]') + ', ' + LINE(key, '[Budget FY]') + ' )', '11 KPI Cards', '0%',
        f'{n} year to date as a share of the full-year budget.')
    add(f'{n} Progress Text', f'FORMAT ( [{n} FY Progress], "0%" ) & " of FY budget · " & FORMAT ( [Year Elapsed %], "0%" ) & " of year"', '11 KPI Cards')
add('Net Income Outlook Progress', 'DIVIDE ( [Net Income Outlook FY], [Net Income Budget FY] )', '11 KPI Cards', '0%')
add('Net Income Outlook Progress Text', 'FORMAT ( [Net Income Outlook Progress], "0%" ) & " of FY budget"', '11 KPI Cards')
add('Metric FY Progress', 'DIVIDE ( ' + MET('[Actual YTD]') + ', [Metric Budget FY] )', '11 KPI Cards', '0%')
add('Metric Progress Text', 'FORMAT ( [Metric FY Progress], "0%" ) & " of FY budget · " & FORMAT ( [Year Elapsed %], "0%" ) & " of year"', '11 KPI Cards')
add('Metric Outlook Progress', 'DIVIDE ( [Metric Outlook FY], [Metric Budget FY] )', '11 KPI Cards', '0%')
add('Metric Outlook Progress Text', 'FORMAT ( [Metric Outlook Progress], "0%" ) & " of FY budget (outlook)"', '11 KPI Cards')
add('Gross Margin Progress Text', '"Budget " & FORMAT ( [Gross Profit Margin % Budget], "0.0%" ) & " · PY " & FORMAT ( DIVIDE ( [Gross Profit PY], [Revenue PY] ), "0.0%" )', '11 KPI Cards')
add('Cash Progress Text', '"Year end " & ' + MU(LINE(101, '[Prior Year-End Balance]')) + ' & " · DSO " & FORMAT ( [DSO (days)], "0" ) & " days"', '11 KPI Cards')
for n in ('Revenue', 'EBITDA', 'Net Income', 'Net Income Outlook', 'Metric', 'Metric Outlook'):
    src = f'{n} FY Progress' if n in ('Revenue', 'EBITDA', 'Net Income', 'Metric') else f'{n} Progress'
    add(f'{n} Progress Bar', f'MIN ( MAX ( [{src}], 0 ), 1 )', '11 KPI Cards', '0%', 'Progress capped to 0-100% for the bar.')
redefine('Cash Spark', desc='Month-end cash for closed months of the selected fiscal year (sparkline).')

add('Entity Budget Status Summary', 'VAR t = FILTER ( ADDCOLUMNS ( VALUES ( Entity[EntityName] ), "@s", [Entity Budget Status] ), [@s] = "Not budgeted" ) RETURN IF ( COUNTROWS ( t ) > 0, "Unbudgeted: " & CONCATENATEX ( t, Entity[EntityName], ", " ), "All entities budgeted" )', '11 KPI Cards')
add('Sub Entities Short', 'VAR t = FILTER ( ADDCOLUMNS ( VALUES ( Entity[EntityName] ), "@s", [Entity Budget Status] ), NOT ISBLANK ( [@s] ) ) RETURN COUNTROWS ( FILTER ( t, [@s] <> "Budgeted" ) ) + 0 & " without a credible budget"', '11 KPI Cards')
add('Metric Budget FY Text', '"FY budget " & ' + MU('[Metric Budget FY]'), '11 KPI Cards')
add('Revenue Growth Short', '"Total growth " & FORMAT ( [Revenue Growth %], "+0.0%;-0.0%" ) & " vs PY"', '11 KPI Cards')


# ---- SVG sparklines and pacing bars (Image visual; scale cleanly at any size)
SVG_HEAD = '"data:image/svg+xml;utf8,<svg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 120 40\' preserveAspectRatio=\'none\'>"'
def svg_spark(name, base, full_year=False, py=False):
    d_filter = "'Date'[Month] = EDATE ( d, -12 )" if py else "'Date'[Month] = d"
    keep = 'TRUE ()' if full_year else '[@d] <= sel'
    expr = f"""VAR sel = [Selected Month] VAR fy = {FYS}
VAR t = ADDCOLUMNS ( GENERATESERIES ( 1, 12, 1 ), "@d", DATE ( fy - 1, 3 + [Value], 1 ) )
VAR t2 = FILTER ( ADDCOLUMNS ( t, "@v", VAR d = [@d] RETURN CALCULATE ( {base}, REMOVEFILTERS ( 'Date' ), {d_filter} ) ), {keep} && NOT ISBLANK ( [@v] ) )
VAR mn = MINX ( t2, [@v] ) VAR mx = MAXX ( t2, [@v] ) VAR rng = IF ( mx = mn, 1, mx - mn )
VAR pts = CONCATENATEX ( t2, FORMAT ( ( [Value] - 1 ) * 10 + 5, "0.0" ) & "," & FORMAT ( 35 - ( [@v] - mn ) / rng * 30, "0.0" ), " ", [Value], ASC )
VAR lst = TOPN ( 1, t2, [Value], DESC )
VAR lx = FORMAT ( ( MAXX ( lst, [Value] ) - 1 ) * 10 + 5, "0.0" ) VAR ly = FORMAT ( 35 - ( MAXX ( lst, [@v] ) - mn ) / rng * 30, "0.0" )
RETURN IF ( COUNTROWS ( t2 ) > 1, SUBSTITUTE ( {SVG_HEAD}
    & "<polyline points='" & pts & "' fill='none' stroke='" & [Col Accent] & "' stroke-width='2' stroke-linejoin='round' stroke-linecap='round' vector-effect='non-scaling-stroke'/>"
    & "<circle cx='" & lx & "' cy='" & ly & "' r='2.5' fill='" & [Col Accent] & "'/></svg>", "#", "%23" ) )"""
    add(name, expr, '11 KPI Cards', None, 'SVG sparkline: fiscal months of the selected year (dot = latest month).')
    MEAS[-1]['cat'] = 'ImageUrl'
def svg_bar(name, progress):
    expr = f"""VAR p = {progress} VAR e = [Year Elapsed %]
RETURN IF ( NOT ISBLANK ( p ), SUBSTITUTE ( "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 300 12' preserveAspectRatio='none'>"
    & "<rect x='0' y='3' width='300' height='6' rx='3' fill='" & [Col Track] & "'/>"
    & "<rect x='0' y='3' width='" & FORMAT ( MIN ( MAX ( p, 0 ), 1 ) * 300, "0" ) & "' height='6' rx='3' fill='" & [Col Accent] & "'/>"
    & "<rect x='" & FORMAT ( MIN ( e, 1 ) * 300 - 1, "0" ) & "' y='0' width='2' height='12' fill='" & [Col Muted] & "'/></svg>", "#", "%23" ) )"""
    add(name, expr, '11 KPI Cards', None, 'SVG pacing bar: progress to the full-year budget; the tick marks how much of the year has elapsed.')
    MEAS[-1]['cat'] = 'ImageUrl'
svg_spark('SVG Spark Revenue', LINE(3, '[Actual]'))
svg_spark('SVG Spark Gross Margin', 'DIVIDE ( ' + LINE(5, '[Actual]') + ', ' + LINE(3, '[Actual]') + ' )')
svg_spark('SVG Spark EBITDA', LINE(13, '[Actual]'))
svg_spark('SVG Spark Net Income', LINE(20, '[Actual]'))
svg_spark('SVG Spark Cash', LINE(101, '[Actual]'))
svg_spark('SVG Spark Metric', '[Metric Actual (in context)]')
svg_spark('SVG Spark Metric Budget', '[Metric Budget (in context)]', full_year=True)
svg_spark('SVG Spark Metric PY', '[Metric Actual (in context)]', full_year=True, py=True)
for n in ('Revenue', 'EBITDA', 'Net Income', 'Metric'):
    svg_bar(f'SVG Bar {n}', f'[{n} FY Progress]')
svg_bar('SVG Bar Net Income Outlook', '[Net Income Outlook Progress]')
svg_bar('SVG Bar Metric Outlook', '[Metric Outlook Progress]')


# ======================================================================== v4: formatting standard, CFO additions
import re as _re

# ---- 4.1 every remaining inline "x / 1e6 ... M" text now goes through money(), so all text follows one standard
_INLINE_M = _re.compile(r'FORMAT \( (\( \[[^\]]+\] - \[[^\]]+\] \)|\[[^\]]+\]|[A-Za-z_]\w*) / 1e6, "(\+#,0\.0;-#,0\.0|▲ \+#,0\.0;▼ -#,0\.0)" \) & "M')
for _m in MEAS:
    _m['expr'] = _INLINE_M.sub(lambda g: money(g.group(1), 'arrow' if g.group(2).startswith('▲') else 'signed') + ' & "', _m['expr'])
assert not any('/ 1e6' in _m['expr'] and 'money' not in _m['name'].lower() and '_x / 1e6' not in _m['expr'] for _m in MEAS if _m['name'] != 'Revenue (M)'), 'inline millions left'

# percentages that are not meaningful (tiny base) show blank instead of four-digit noise
redefine('Line Var % vs Budget', 'VAR p = IF ( [Line Actual] * [Line Budget] > 0, DIVIDE ( [Line Actual] - [Line Budget], ABS ( [Line Budget] ) ) ) RETURN IF ( ABS ( p ) < 10, p )',
         desc='Budget variance %. Blank (n.m.) when actual and budget have different signs or the variance exceeds 1,000% (base too small to be meaningful).')
redefine('Line Growth %', 'VAR p = IF ( [Line Actual] * [Line Prior Year] > 0, DIVIDE ( [Line Actual] - [Line Prior Year], ABS ( [Line Prior Year] ) ) ) RETURN IF ( ABS ( p ) < 10, p )',
         desc='Growth vs the same period last year. Blank (n.m.) when the signs differ or the change exceeds 1,000%.')

# ---- 4.2 conditional formatting: one rule everywhere. Green = favourable to the business, red = unfavourable, amber = caution,
#      neutral text = information only. Arrows show direction; colour shows whether that direction is good.
def tone(name, expr_good, desc):
    """Colour measure: [Col Good] when expr_good is true, [Col Bad] when false, neutral when blank."""
    add(name, f'VAR g = {expr_good} RETURN IF ( ISBLANK ( g ), [Col Muted], IF ( g, [Col Good], [Col Bad] ) )', '8 Formatting', None, desc)
redefine('Balance Change Color', '[Col Text]',
         desc='Balance-sheet movements are shown neutral: a rise in receivables or debt is not good or bad by itself. The cash bridge colours them by cash effect instead.')
tone('Metric Growth Color', 'IF ( NOT ISBLANK ( [Metric Growth %] ), [Metric Actual] >= [Metric PY] )', 'Green when the selected metric is at or above the same period last year.')
tone('Revenue Growth Color', 'IF ( NOT ISBLANK ( [Revenue Growth %] ), [Revenue Growth %] >= 0 )', 'Green when revenue grew versus the same period last year.')
add('EBITDA Margin Text', 'FORMAT ( [EBITDA Margin pts vs Budget] * 100, "▲ 0.0;▼ 0.0;0.0" ) & " pts vs budget"', '3 KPIs\\Margins', None, 'EBITDA margin versus budget margin, in percentage points.')
tone('EBITDA Margin Var Color', 'IF ( NOT ISBLANK ( [EBITDA Margin pts vs Budget] ), [EBITDA Margin pts vs Budget] >= 0 )', 'Green when EBITDA margin is at or above the budget margin.')
add('OpEx % of Revenue Budget', 'DIVIDE ( -[Operating Expenses Budget], [Revenue Budget] )', '3 KPIs\\Margins', P, 'Budgeted operating expenses as a share of budgeted revenue.')
add('OpEx Ratio Text', 'FORMAT ( ( [OpEx % of Revenue] - [OpEx % of Revenue Budget] ) * 100, "▲ 0.0;▼ 0.0;0.0" ) & " pts vs budget"', '3 KPIs\\Margins', None,
    'Operating-expense ratio versus the budget ratio, in percentage points (a rise is unfavourable).')
tone('OpEx Ratio Var Color', 'IF ( NOT ISBLANK ( [OpEx % of Revenue Budget] ), [OpEx % of Revenue] <= [OpEx % of Revenue Budget] )', 'Green when operating expenses take a smaller share of revenue than budgeted.')
add('Salary per Head Text', 'VAR g = DIVIDE ( [Salary Cost per Head], [Salary Cost per Head PY] ) - 1 RETURN IF ( NOT ISBLANK ( [Salary Cost per Head PY] ), FORMAT ( g, "▲ 0.0%;▼ 0.0%;0.0%" ) & " vs PY · headcount " & FORMAT ( [Headcount], "#,0" ) )',
    '3 KPIs\\People', None, 'Change in salary cost per head versus last year, with closing headcount.')
tone('Salary per Head Color', 'IF ( NOT ISBLANK ( [Salary Cost per Head PY] ), [Salary Cost per Head] <= [Salary Cost per Head PY] )', 'Green when salary cost per head is at or below last year.')

# ---- 4.3 balance-sheet KPIs compared with the last year end (the balance-sheet comparative used on the page)
BY = lambda key: LINE(key, '[Prior Year-End Balance]')
_YE = f'DATE ( {FYS} - 1, 3, 1 )'
BSF = '4 Balance Sheet KPIs\\Year-end comparatives'
add('Year-End Label', f'FORMAT ( {_YE}, "mmm yyyy" )', BSF, None, 'Month of the previous fiscal year end (March), used as the balance-sheet comparative.')
for _n, _k in (('Revenue', 3), ('Cost of Sales', 4)):
    add(f'{_n} TTM (year end)', f"VAR ye = {_YE}\nRETURN CALCULATE ( {LINE(_k, '[Actual]')}, REMOVEFILTERS ( 'Date' ), 'Date'[Month] > EDATE ( ye, -12 ) && 'Date'[Month] <= ye )", BSF, F,
        f'{_n} for the twelve months ending at the previous fiscal year end; denominator for the year-end working-capital days.')
add('DSO (year end)', f'DIVIDE ( {BY(102)}, [Revenue TTM (year end)] ) * 365', BSF, '0', 'Receivable days at the previous fiscal year end.')
add('DIO (year end)', f'DIVIDE ( {BY(103)}, -[Cost of Sales TTM (year end)] ) * 365', BSF, '0', 'Inventory days at the previous fiscal year end.')
add('DPO (year end)', f'DIVIDE ( {BY(109)}, -[Cost of Sales TTM (year end)] ) * 365', BSF, '0', 'Payable days at the previous fiscal year end.')
add('Cash Conversion Cycle (year end)', '[DSO (year end)] + [DIO (year end)] - [DPO (year end)]', BSF, '0', 'Cash conversion cycle at the previous fiscal year end.')
add('Current Ratio (year end)', f'DIVIDE ( {BY(105)}, {BY(113)} )', BSF, '0.00', 'Current assets / current liabilities at the previous fiscal year end.')
add('Debt to Equity (year end)', f'DIVIDE ( {BY(111)} + {BY(114)}, {BY(119)} )', BSF, '0.00', 'Short- and long-term debt / total equity at the previous fiscal year end.')
def bs_delta(short, cur, base, fmt, unit, good_when_down, neutral=False):
    add(f'{short} Change Text', f'VAR d = [{cur}] - [{base}] RETURN IF ( NOT ISBLANK ( [{base}] ), FORMAT ( d, "▲ {fmt};▼ {fmt};{fmt}" ) & "{unit} vs " & [Year-End Label] )', BSF, None,
        f'Change in {cur} since the previous fiscal year end.')
    if neutral:
        add(f'{short} Change Color', '[Col Muted]', '8 Formatting', None, 'Neutral: longer payment terms help cash but can strain suppliers, so no good/bad colour is applied.')
    else:
        op = '<=' if good_when_down else '>='
        tone(f'{short} Change Color', f'IF ( NOT ISBLANK ( [{base}] ), [{cur}] {op} [{base}] )', f'Green when {cur} moved in the favourable direction since the year end.')
bs_delta('DSO', 'DSO (days)', 'DSO (year end)', '#,0', ' days', True)
bs_delta('DIO', 'DIO (days)', 'DIO (year end)', '#,0', ' days', True)
bs_delta('DPO', 'DPO (days)', 'DPO (year end)', '#,0', ' days', True, neutral=True)
bs_delta('CCC', 'Cash Conversion Cycle (days)', 'Cash Conversion Cycle (year end)', '#,0', ' days', True)
bs_delta('Current Ratio', 'Current Ratio', 'Current Ratio (year end)', '0.00', 'x', False)
bs_delta('Debt to Equity', 'Debt to Equity', 'Debt to Equity (year end)', '0.00', 'x', True)
redefine('Cash Change Text', 'VAR c = [Cash] - ' + CASH_PYE + ' RETURN ' + money('c', 'arrow') + ' & " vs " & [Year-End Label]')

# pass / fail text for integrity checks (data-quality tiles and the balance check)
def check(name, measure, ok_text, fail_text):
    add(f'{name} Check Text', f'IF ( [{measure}] = 0, "✓ {ok_text}", "✗ {fail_text}" )', '9 Data Quality', None, f'Pass/fail label for [{measure}]: it must be 0.')
    tone(f'{name} Check Color', f'[{measure}] = 0', f'Green when [{measure}] is 0 (check passed).')
check('Balance', 'DQ Balance Sheet Difference', 'assets = liabilities + equity', 'out of balance')
check('FX', 'DQ Rows Missing FX Rate', 'every row has a rate', 'rows without a rate')
check('Chart', 'DQ Accounts Missing From Chart', 'all accounts known', 'unknown accounts')
add('DQ Detected Text', '"✓ detected and treated in Power Query"', '9 Data Quality', None, 'Static label under the injected-issue counts.')

# ---- 4.4 cash bridge: why cash moved since the year end, from the balance-sheet identity (always ties to the cash change)
M_CASH_BRIDGE = m_table([('Step', 'text'), ('Sort', 'Int64.Type')],
                        [('Receivables', 1), ('Inventory', 2), ('Other assets', 3), ('Payables', 4), ('Other liabilities', 5), ('Debt', 6), ('Equity', 7)])
TABLES.insert(len(TABLES) - 1, dict(name='Cash Bridge', desc='Axis for the cash bridge on the Balance Sheet page: one step per balance-sheet group.', m=M_CASH_BRIDGE,
                                    cols=[('Step', 'string', {'sortBy': 'Sort'}), ('Sort', 'int64', {'hidden': 1})]))
_chg = lambda keys: ' + '.join(f'( {LINE(k, "[Closing Balance]")} - {LINE(k, "[Prior Year-End Balance]")} )' for k in keys)
add('Cash Bridge Value', f'''SWITCH ( SELECTEDVALUE ( 'Cash Bridge'[Step] ),
    -- assets: an increase ties up cash, so the sign is reversed
    "Receivables", - ( {_chg([102])} ),
    "Inventory", - ( {_chg([103])} ),
    "Other assets", - ( {_chg([104, 106, 107])} ),
    -- liabilities and equity: an increase is a source of cash
    "Payables", {_chg([109])},
    "Other liabilities", {_chg([110, 112, 115])},
    "Debt", {_chg([111, 114])},
    "Equity", {_chg([117, 118])} )''', '4 Balance Sheet KPIs', F,
    'Cash effect of each balance-sheet group since the previous fiscal year end. Because assets = liabilities + equity, the steps add up exactly to the change in cash. Equity includes profit, distributions and the unreconciled retained-earnings movement in the source data.')
add('VT Cash Bridge', '"What moved cash since " & [Year-End Label] & ": " & ' + money('[Cash] - ' + CASH_PYE, 'signed') + ' & " · green = source, red = use"', VT)
add('Sub Cash Bridge', '''VAR t = ADDCOLUMNS ( VALUES ( 'Cash Bridge'[Step] ), "@v", [Cash Bridge Value] )
VAR topUse = TOPN ( 1, t, [@v], ASC ) VAR topSrc = TOPN ( 1, t, [@v], DESC )
RETURN "Largest use: " & MAXX ( topUse, 'Cash Bridge'[Step] ) & " (" & ''' + money('MAXX ( topUse, [@v] )', 'signed') + ''' & "); largest source: " & MAXX ( topSrc, 'Cash Bridge'[Step] ) & " (" & ''' + money('MAXX ( topSrc, [@v] )', 'signed') + ''' & "). Balance-sheet method, so it ties to the cash change."''', SB)

# ---- 4.5 currency effect: how much of the result is translation (actual rates) rather than trading (budget rates)
for _t in TABLES:
    if _t['name'] == 'GL':
        _t['cols'] += [
            ('Amount CAD (budget rate)', 'double', {'hidden': 1, 'fmt': '#,0', 'desc': 'Local-currency amount translated to CAD at the budget rate (prior fiscal-year average) instead of the actual rate: the constant-currency view of P&L rows.',
                'expr': 'VAR k = RELATED ( Entity[CurrencyCode] ) & "|" & FORMAT ( GL[Month], "yyyy-MM" )\nRETURN GL[AmountLC] * LOOKUPVALUE ( FX[BudgetRate], FX[FXKey], k ) * RELATED ( Account[Sign] )'}),
            ('Amount USD (budget rate)', 'double', {'hidden': 1, 'fmt': '#,0', 'desc': 'Constant-currency amount expressed in USD, using the budget USD/CAD rate.',
                'expr': 'VAR k = "USD|" & FORMAT ( GL[Month], "yyyy-MM" )\nRETURN DIVIDE ( GL[Amount CAD (budget rate)], LOOKUPVALUE ( FX[BudgetRate], FX[FXKey], k ) )'})]
FXF = '3 KPIs\\Currency effect'
add('Actual at Budget Rate', 'CALCULATE ( IF ( SELECTEDVALUE ( \'Reporting Currency\'[Currency], "CAD" ) = "USD", SUM ( GL[Amount USD (budget rate)] ), SUM ( GL[Amount CAD (budget rate)] ) ), GL[Scenario] = "Actual" )',
    FXF, F, 'Actuals translated at the budget exchange rate (constant currency). P&L only.')
add('Actual at Budget Rate (Period)', f'''VAR m = [Selected Month]
VAR winStart = SWITCH ( SELECTEDVALUE ( 'Period View'[View], "YTD" ),
    "MTD", m,
    "QTD", DATE ( YEAR ( m ), INT ( ( MONTH ( m ) - 1 ) / 3 ) * 3 + 1, 1 ),
    DATE ( {FYN('m')} - 1, 4, 1 ) )
RETURN CALCULATE ( [Actual at Budget Rate], REMOVEFILTERS ( 'Date' ), 'Date'[Month] >= winStart && 'Date'[Month] <= m )''', FXF, F,
    'Constant-currency actuals for the period chosen in the Period slicer (MTD, QTD or YTD).')
for _n in ('Revenue', 'EBITDA'):
    add(f'{_n} at Budget Rate', LINE(KPI[_n], '[Actual at Budget Rate (Period)]'), FXF, F, f'{_n} for the period, translated at budget exchange rates.')
    add(f'{_n} FX Effect', f'[{_n}] - [{_n} at Budget Rate]', FXF, F, f'Part of {_n.lower()} that comes from exchange rates differing from the budget rate (translation effect). Positive = currencies moved in the group\'s favour.')
    add(f'{_n} Var vs Budget (constant currency)', f'[{_n} at Budget Rate] - [{_n} Budget]', FXF, F, f'{_n} variance to budget with the currency effect removed: the trading variance.')
add('Revenue Var % vs Budget (constant currency)', 'DIVIDE ( [Revenue Var vs Budget (constant currency)], ABS ( [Revenue Budget] ) )', FXF, P, 'Revenue variance % to budget at constant currency.')
add('Insight Currency', '''VAR fr = [Revenue FX Effect] VAR fe = [EBITDA FX Effect] VAR rv = [Revenue Var vs Budget]
RETURN IF ( ISBLANK ( fr ), "No foreign-currency activity in this selection.",
    "Exchange rates versus budget rates " & IF ( fr >= 0, "added ", "removed " ) & ''' + money('ABS ( fr )') + ''' & " of revenue (equal to " & FORMAT ( ABS ( DIVIDE ( fr, rv ) ), "0%" ) & " of the variance) and "
        & IF ( fe >= 0, "added ", "removed " ) & ''' + money('ABS ( fe )') + ''' & " of EBITDA. At constant currency revenue is " & FORMAT ( [Revenue Var % vs Budget (constant currency)], "+0.0%;-0.0%" ) & " vs budget." )''',
    '6 Narrative', None, 'Narrative: how much of the revenue and EBITDA result is exchange-rate translation rather than trading.')
for _t in TABLES:
    if _t['name'] == 'Insight':
        _t['m'] = m_table([('Key', 'Int64.Type'), ('Topic', 'text')],
                          [(1, 'Growth quality'), (2, 'Cost absorption'), (3, 'Full-year outlook'), (4, 'People cost'), (5, 'Currency effect')])
redefine('Insight Text', "SWITCH ( SELECTEDVALUE ( Insight[Key] ), 1, [Insight Perimeter], 2, [Insight Cost Absorption], 3, [Insight Outlook], 4, [Insight People Cost], 5, [Insight Currency] )")

# ---- 4.6 KPI card values for every tile in the report (same text formatting on every page)
for _n in ['EBITDA Margin %', 'OpEx % of Revenue', 'Salary Cost per Head', 'Current Ratio', 'Debt to Equity', 'Cash Conversion Cycle (days)', 'DSO (days)', 'DIO (days)',
           'DPO (days)', 'DQ Files Loaded', 'DQ Duplicates Removed', 'DQ Blank Departments Fixed', 'DQ Files With Schema Drift', 'DQ Balance Sheet Difference',
           'DQ Rows Missing FX Rate', 'DQ Accounts Missing From Chart', 'DQ Synthetic Budget Share']:
    add(f'KV {_n}', kv_expr(_n), '11 KPI Cards')
redefine('Metric Budget FY Text', '"FY budget " & ' + money('[Metric Budget FY]'))

# ---- 4.7 notes page: assumptions, policies and definitions a reader needs before quoting a number
NOTES = [
    ('Notes', 1, 'Fiscal calendar', 'Fiscal year runs 1 April to 31 March and is named by the year it ends (FY2027 = Apr 2026 to Mar 2027). YTD, QTD and MTD are fiscal.'),
    ('Notes', 2, 'Close and as-of month', 'The reporting month is the latest month with an actuals file ("books closed"). Selecting a later month falls back to the close.'),
    ('Notes', 3, 'Sign convention', 'Revenue is positive and costs are negative, so subtotals add up. Every variance is actual minus budget: positive is favourable, on revenue and on cost lines.'),
    ('Notes', 4, 'Colour', 'Green = favourable, red = unfavourable, amber = caution (budget not credible), blue = actual, light blue = outlook, grey = budget or prior year. Arrows show direction only.'),
    ('Notes', 5, 'Number format', 'Text and cards: $ with millions to one decimal, thousands whole. Tables: thousands, negatives in brackets. Percentages to one decimal. "n.m." or blank = not meaningful.'),
    ('Notes', 6, 'Currency', 'Bank of Canada rates, CAD per unit. P&L at monthly average, balance sheet at month end, budget at the prior fiscal-year average. USD view translates the CAD result at the USD rate.'),
    ('Notes', 7, 'Currency effect', 'Constant currency = actuals translated at budget rates. The difference to reported actuals is translation, not trading. Rates after the last published month are carried forward.'),
    ('Notes', 8, 'Budget', 'FY2026 to FY2028 budgets are synthetic (prior-year actual x growth x seeded noise). Entities that joined after the budget was set have no budget and are flagged.'),
    ('Notes', 9, 'Budget credibility', 'Not budgeted = no budget for the period. Under-budgeted = actual revenue above 2x budget. Their favourable variance is a planning gap, not outperformance.'),
    ('Notes', 10, 'Outlook', 'Full-year outlook = actuals to the close + budget for the remaining months. The run-rate figure instead assumes the remaining months beat budget by the year-to-date ratio.'),
    ('Notes', 11, 'Organic growth', 'Like-for-like revenue counts only entities that also traded in the same period last year. New-entity revenue is the rest.'),
    ('Notes', 12, 'Ownership', 'Entities are consolidated at 100%. Effective ownership (multiplied down the hierarchy) splits net income between the group and non-controlling interests.'),
    ('Notes', 13, 'Cash bridge', 'Balance-sheet method: each step is the change in a balance since the year end, signed by cash effect, so the steps tie to the cash change. It is not a statutory cash-flow statement.'),
    ('Notes', 14, 'Known gaps', 'Retained earnings do not roll forward from net income in the source data; intercompany balances are not eliminated; revenue and cost of sales post to one department.'),
    ('Notes', 15, 'Data', 'Fictional company built on Microsoft AdventureWorksDW (MIT licence), re-dated. Source issues are injected on purpose and reconciled on the Data Quality page.'),
    ('Defs', 1, 'Net revenue', 'Gross sales less returns and discounts.'),
    ('Defs', 2, 'Gross margin', 'Gross profit (net revenue less cost of sales) / net revenue.'),
    ('Defs', 3, 'EBITDA', 'Gross profit less operating expenses, before depreciation, amortization, interest, other items and tax.'),
    ('Defs', 4, 'Variance %', 'Variance / absolute budget. Shown only when actual and budget share a sign and the result is below 1,000%.'),
    ('Defs', 5, 'Pacing bar', 'Year-to-date actual as a share of the full-year budget. The tick marks the share of the year elapsed: a bar beyond the tick is ahead of a straight-line year.'),
    ('Defs', 6, 'Receivable days (DSO)', 'Receivables / trailing-twelve-month revenue x 365.'),
    ('Defs', 7, 'Inventory days (DIO)', 'Inventory / trailing-twelve-month cost of sales x 365.'),
    ('Defs', 8, 'Payable days (DPO)', 'Payables / trailing-twelve-month cost of sales x 365.'),
    ('Defs', 9, 'Cash cycle', 'Receivable days + inventory days - payable days.'),
    ('Defs', 10, 'Current ratio', 'Current assets / current liabilities.'),
    ('Defs', 11, 'Debt to equity', 'Short-term + long-term debt / total equity.'),
    ('Defs', 12, 'Salary cost per head', 'Salaries and benefits for the period / closing headcount (statistical account).'),
    ('Defs', 13, 'Trade working capital', 'Receivables + inventory - payables.'),
]
STORY_ROWS += NOTES
for _t in TABLES:
    if _t['name'] == 'Story':
        _t['m'] = m_table([('Page', 'text'), ('Sort', 'Int64.Type'), ('Section', 'text'), ('Text', 'text')], STORY_ROWS)
add('PT Notes', '"Notes & Assumptions · read before quoting a number"', PH)
add('PS Notes', '"Policies, assumptions and definitions behind every page · books closed " & FORMAT ( [As Of Month], "mmm yyyy" ) & " · " & [Currency Label]', PH)
add('VT Notes', '"Assumptions and policies"', VT)
add('Sub Notes', '"What the numbers assume. Each item applies to every page unless stated."', SB)
add('VT Defs', '"Definitions"', VT)
add('Sub Defs', '"One definition per metric, identical in every visual. Full DAX: docs/01-semantic-model.md."', SB)
add('Footer Notes', FOOT + ' & " · Notes apply to all pages"', '10 Layout')
redefine('Footer Note 1', '"1  One definition per metric: hover a KPI label for its definition; assumptions and policies are on the Notes page."')

# net income belonging to the group vs minority partners (three entities are partly owned)
add('KV Net Income Attributable to Group', kv_expr('Net Income Attributable to Group'), '11 KPI Cards')
add('NCI Text', '"Minority partners (NCI) " & ' + money('[Net Income Attributable to NCI]') + ' & " · " & FORMAT ( DIVIDE ( [Net Income Attributable to NCI], [Net Income] ), "0%" ) & " of net income"',
    '3 KPIs\\Ownership', None, 'Net income belonging to non-controlling interests, as an amount and a share of total net income.')


# ======================================================================== v6: Sankey, data dictionary, statement explorer, rolling forecast
# (placed before the documentation pass so the new objects get descriptions, comments and diagram positions like everything else)

# ---- 6.1 Report Line: a section order and a flag for the expandable statement matrix (section header > detail lines)
_SEC_SORT = {}
for _l in LINES:
    _SEC_SORT.setdefault(_l[2], _l[0])
_HAS_DETAIL = {sec for sec in _SEC_SORT if any(l[2] == sec and l[3] == 'Detail' for l in LINES)}
M_REPORT_LINE = m_table([('LineKey', 'Int64.Type'), ('LineName', 'text'), ('Section', 'text'), ('LineType', 'text'), ('Statement', 'text'), ('SectionSort', 'Int64.Type'), ('MatrixRow', 'text')],
                        [l[:5] + (_SEC_SORT[l[2]], 'No' if (l[3] != 'Detail' and l[2] in _HAS_DETAIL) else 'Yes') for l in LINES])
for _t in TABLES:
    if _t['name'] == 'Report Line':
        _t['m'] = M_REPORT_LINE
        _t['cols'] = [(c[0], c[1], dict(c[2], sortBy='SectionSort')) if c[0] == 'Section' else c for c in _t['cols']] + [
            ('SectionSort', 'int64', {'hidden': 1, 'desc': 'First line number of the section; sorts sections in statement order.'}),
            ('MatrixRow', 'string', {'hidden': 1, 'desc': 'No for subtotal lines whose section already has detail lines: the matrix shows the section header as that subtotal, so the line would repeat.'})]

# ---- 6.2 selector tables
M_FOCUS = m_table([('Focus', 'text'), ('LineKey', 'Int64.Type'), ('Sort', 'Int64.Type')],
                  [('Revenue', 3, 1), ('COGS', 4, 2), ('Gross Profit', 5, 3), ('EBITDA', 13, 4), ('EBIT', 15, 5), ('Net Profit', 20, 6)])
M_UNIT = m_table([('Unit', 'text'), ('Divisor', 'Int64.Type'), ('Sort', 'Int64.Type')], [('Thousand', 1000, 1), ('Absolute', 1, 2)])
DAX_ACTUALS_UNTIL = """SELECTCOLUMNS (
    FILTER ( 'Date', 'Date'[IsClosed] ),
    "Month", 'Date'[Month],
    "Label", 'Date'[Year Month],
    "Index", 'Date'[Month Index]
)"""
DAX_DICTIONARY = """-- Data dictionary (pattern from the INFO.VIEW documentation technique): one VAR per object type, UNION at the end.
-- INFO.VIEW functions read the model's own metadata on every refresh, so the dictionary cannot drift from the model.
-- Hidden objects are left out (they are plumbing, not something a reader should use), and the dictionary leaves itself out.
VAR __Tables =
    SELECTCOLUMNS (
        FILTER ( INFO.VIEW.TABLES (), [IsHidden] = FALSE () && NOT [IsPrivate] && [Name] <> "Data Dictionary" ),
        "Object Type", "Table", "Table", [Name], "Name", [Name], "Description", [Description],
        "Expression", [Expression], "Folder", BLANK ()
    )
VAR __Columns =
    SELECTCOLUMNS (
        FILTER ( INFO.VIEW.COLUMNS (), [IsHidden] = FALSE () && [Table] <> "Data Dictionary" ),
        "Object Type", "Column", "Table", [Table], "Name", [Name], "Description", [Description],
        "Expression", [Expression], "Folder", [DisplayFolder]
    )
VAR __Measures =
    SELECTCOLUMNS (
        FILTER ( INFO.VIEW.MEASURES (), [IsHidden] = FALSE () ),
        "Object Type", "Measure", "Table", [Table], "Name", [Name], "Description", [Description],
        "Expression", [Expression], "Folder", [DisplayFolder]
    )
VAR __Relationships =
    SELECTCOLUMNS (
        INFO.VIEW.RELATIONSHIPS (),
        "Object Type", "Relationship", "Table", [FromTable], "Name", [Relationship],
        "Description", "From " & [FromTable] & " to " & [ToTable] & IF ( [IsActive], "", " (inactive)" ),
        "Expression", [Relationship], "Folder", BLANK ()
    )
RETURN
    UNION ( __Tables, __Columns, __Measures, __Relationships )"""
_ins = len(TABLES) - 1
TABLES[_ins:_ins] = [
    dict(name='PL Focus', desc='Slicer on the Income Statement Explorer page: which headline line the summary and the trend describe.', m=M_FOCUS,
         cols=[('Focus', 'string', {'sortBy': 'Sort', 'desc': 'Headline P&L line.'}), ('LineKey', 'int64', {'hidden': 1, 'desc': 'Report line the focus maps to.'}), ('Sort', 'int64', {'hidden': 1, 'desc': 'Display order.'})]),
    dict(name='Display Unit', desc='Slicer on the Income Statement Explorer page: show amounts in thousands or in full.', m=M_UNIT,
         cols=[('Unit', 'string', {'sortBy': 'Sort', 'desc': 'Thousand or Absolute.'}), ('Divisor', 'int64', {'hidden': 1, 'desc': 'Number the amounts are divided by.'}), ('Sort', 'int64', {'hidden': 1, 'desc': 'Display order.'})]),
    dict(name='Actuals Until', desc='Slicer on the Rolling Forecast page: the last month to treat as actual. Disconnected on purpose, so it moves the actual/budget cut-over without filtering the calendar.',
         dax=DAX_ACTUALS_UNTIL,
         cols=[('Month', 'dateTime', {'fmt': 'mmm yyyy', 'hidden': 1, 'desc': 'First day of a closed month.'}), ('Label', 'string', {'sortBy': 'Index', 'desc': 'Month shown in the slicer, e.g. Jun 2026.'}),
               ('Index', 'int64', {'hidden': 1, 'desc': 'Running month number, for sorting.'})]),
    dict(name='Data Dictionary', desc='Self-documenting catalogue of the model: every table, column, measure and relationship with its description and expression, read from the model itself with the INFO.VIEW functions on each refresh.',
         dax=DAX_DICTIONARY,
         cols=[('Object Type', 'string', {'desc': 'Table, Column, Measure or Relationship.'}), ('Table', 'string', {'desc': 'Table the object belongs to (for a relationship: the many side).'}),
               ('Name', 'string', {'desc': 'Object name.'}), ('Description', 'string', {'desc': 'Business description stored on the object.'}),
               ('Expression', 'string', {'desc': 'DAX of a measure, calculated column or calculated table; the join for a relationship.'}),
               ('Folder', 'string', {'desc': 'Display folder.'})]),
]

# ---- 6.3 data dictionary counts
DDF = '12 Data Dictionary'
add('DD Objects', "COUNTROWS ( 'Data Dictionary' )", DDF, '0', 'Number of model objects in the current dictionary selection.')
for _n in ('Table', 'Column', 'Measure', 'Relationship'):
    add(f'DD {_n}s', f"CALCULATE ( COUNTROWS ( 'Data Dictionary' ), KEEPFILTERS ( 'Data Dictionary'[Object Type] = \"{_n}\" ) ) + 0", DDF, '0', f'Number of {_n.lower()}s in the current dictionary selection.')
    add(f'KV DD {_n}s', kv_expr(f'DD {_n}s'), '11 KPI Cards')
add('DD Documented %', "DIVIDE ( COUNTROWS ( FILTER ( 'Data Dictionary', NOT ISBLANK ( 'Data Dictionary'[Description] ) ) ), COUNTROWS ( 'Data Dictionary' ) )", DDF, P,
    'Share of the selected objects that carry a description.')
add('DD Documented Text', 'FORMAT ( [DD Documented %], "0%" ) & " of the selection has a description"', DDF, None, 'Card text: documentation coverage of the current selection.')
add('PT DD', '"Data Dictionary · explore the model without opening it"', PH)
add('PS DD', 'FORMAT ( [DD Objects], "#,0" ) & " objects in the selection · " & [DD Documented Text] & " · built from the model itself on every refresh"', PH)
add('VT DD', '"Model objects: name, description and calculation"', VT)
add('Sub DD', '"Type in a slicer search box to find any table, column or measure by part of its name. Clear the slicers to see everything."', SB)
add('Footer DD', '"Source: INFO.VIEW.TABLES, COLUMNS, MEASURES and RELATIONSHIPS, unioned in the calculated table Data Dictionary · refreshed with the model"', '10 Layout')

# ---- 6.4 Income Statement Explorer (after Goodly's dynamic P&L): six cards, focus summary and trend, section > line matrix
ISF = '13 Statement Explorer'
SECT = lambda base: ("IF ( HASONEVALUE ( 'Report Line'[Section] ),\n    VAR accts = CALCULATETABLE ( VALUES ( 'Report Line Map'[AccountKey] ), TREATAS ( VALUES ( 'Report Line'[LineKey] ), 'Report Line Map'[LineKey] ) )\n"
                     f"    RETURN CALCULATE ( {base}, TREATAS ( accts, Account[AccountKey] ) )\n)")
_REV_CY, _REV_PY = LINE(3, '[Actual (Period)]'), LINE(3, '[Prior Year (Period)]')
add('Unit Divisor', "SELECTEDVALUE ( 'Display Unit'[Divisor], 1000 )", ISF, '0', 'Divisor chosen with the Thousand / Absolute toggle (thousand by default).')
add('IS CY Raw', SECT('[Actual (Period)]'), ISF, F, "Current period for the section or line on the row. A section header shows the union of its lines' accounts, i.e. the section total.")
add('IS PY Raw', SECT('[Prior Year (Period)]'), ISF, F, 'Same period last year for the section or line on the row.')
add('IS CY', 'DIVIDE ( [IS CY Raw], [Unit Divisor] )', ISF, '#,0;(#,0);-', 'Current period, in the unit chosen with the toggle.')
add('IS PY', 'DIVIDE ( [IS PY Raw], [Unit Divisor] )', ISF, '#,0;(#,0);-', 'Prior year, in the unit chosen with the toggle.')
add('IS CY % Rev', f'DIVIDE ( [IS CY Raw], {_REV_CY} )', ISF, '0.00%', 'Current period as a share of net revenue (common size).')
add('IS PY % Rev', f'DIVIDE ( [IS PY Raw], {_REV_PY} )', ISF, '0.00%', 'Prior year as a share of prior-year net revenue.')
add('IS Chg PY', 'DIVIDE ( [IS CY Raw] - [IS PY Raw], [Unit Divisor] )', ISF, '#,0;(#,0);-', 'Change versus prior year, in the chosen unit. Positive = favourable, because costs are stored negative.')
add('IS Chg % PY', 'VAR p = IF ( [IS CY Raw] * [IS PY Raw] > 0, DIVIDE ( [IS CY Raw] - [IS PY Raw], ABS ( [IS PY Raw] ) ) ) RETURN IF ( ABS ( p ) < 10, p )', ISF, P,
    'Change versus prior year in %. Blank when the signs differ or the change exceeds 1,000%.')
add('IS Chg Rev bps', '( [IS CY % Rev] - [IS PY % Rev] ) * 10000', ISF, '#,0.0', 'Change in the share of revenue, in basis points (100 bps = 1 percentage point).')
tone('IS Chg Color', 'IF ( NOT ISBLANK ( [IS CY Raw] ) && NOT ISBLANK ( [IS PY Raw] ), [IS CY Raw] >= [IS PY Raw] )', 'Green when the row is favourable to prior year (higher revenue or profit, lower cost).')
add('IS Row Background', "IF ( ISINSCOPE ( 'Report Line'[LineName] ), [Col Panel], [Col Subtotal] )", '8 Formatting', None, 'Matrix shading: section headers tinted, detail lines on the panel colour.')
add('IS Range', f"""VAR m = [Selected Month]
VAR winStart = SWITCH ( SELECTEDVALUE ( 'Period View'[View], "YTD" ), "MTD", m, "QTD", DATE ( YEAR ( m ), INT ( ( MONTH ( m ) - 1 ) / 3 ) * 3 + 1, 1 ), DATE ( {FYN('m')} - 1, 4, 1 ) )
RETURN FORMAT ( winStart, "dd-mmm-yy" ) & " to " & FORMAT ( EOMONTH ( m, 0 ), "dd-mmm-yy" )""", ISF, None, 'Date range covered by the current Period view, e.g. 01-Apr-26 to 31-Oct-26.')
_CARDS = [('Revenue', 'Revenue'), ('Cost of Sales', 'COGS'), ('Gross Profit', 'Gross Profit'), ('EBITDA', 'EBITDA'), ('EBIT', 'EBIT'), ('Net Income', 'Net Profit')]
for _n, _lab in _CARDS:
    if not any(m['name'] == f'KV {_n}' for m in MEAS):
        add(f'KV {_n}', kv_expr(_n), '11 KPI Cards')
    add(f'IS {_n} PY Text', '"PY   " & ' + money(f'[{_n} PY]'), ISF, None, f'Card row: {_lab} for the same period last year.')
    add(f'IS {_n} Chg Text', '"Change ($)   " & ' + money(f'[{_n}] - [{_n} PY]', 'signed'), ISF, None, f'Card row: {_lab} change versus last year, as an amount.')
    add(f'IS {_n} Pct Text', f'"% Change   " & FORMAT ( DIVIDE ( [{_n}] - [{_n} PY], ABS ( [{_n} PY] ) ), "▲ 0.0%;▼ 0.0%;0.0%" )', ISF, None, f'Card row: {_lab} change versus last year, in %.')
    tone(f'IS {_n} PY Color', f'IF ( NOT ISBLANK ( [{_n} PY] ), [{_n}] >= [{_n} PY] )', f'Green when {_lab} is favourable to last year.')
FOC = lambda base: ("VAR lk = SELECTEDVALUE ( 'PL Focus'[LineKey], 3 )\nVAR accts = CALCULATETABLE ( VALUES ( 'Report Line Map'[AccountKey] ), 'Report Line Map'[LineKey] = lk )\n"
                    "VAR flip = IF ( lk = 4, -1, 1 )   -- cost of sales is stored negative; the trend shows its size\n"
                    f"RETURN flip * CALCULATE ( {base}, TREATAS ( accts, Account[AccountKey] ) )")
add('Focus Name', "SELECTEDVALUE ( 'PL Focus'[Focus], \"Revenue\" )", ISF, None, 'Headline line picked in the Focus slicer (Revenue by default).')
add('Focus Monthly CY', FOC('[Monthly Actual (Selected FY)]'), ISF, F, 'Trend chart: focus line by fiscal month, current year, up to the selected month.')
add('Focus Monthly PY', FOC('[Monthly Prior Year (Selected FY)]'), ISF, F, 'Trend chart: focus line by fiscal month, prior year.')
add('Focus Actual (in context)', FOC('[Actual]'), ISF, F, 'Focus line for whatever dates are in filter context (used inside the summary iterators).')
_FT = f"""VAR sel = [Selected Month] VAR fy = {FYS}
VAR t = FILTER ( ADDCOLUMNS ( GENERATESERIES ( 1, 12, 1 ), "@d", DATE ( fy - 1, 3 + [Value], 1 ) ), [@d] <= sel )
VAR t2 = ADDCOLUMNS ( t, "@cy", VAR d = [@d] RETURN CALCULATE ( [Focus Actual (in context)], REMOVEFILTERS ( 'Date' ), 'Date'[Month] = d ),
                         "@py", VAR d = [@d] RETURN CALCULATE ( [Focus Actual (in context)], REMOVEFILTERS ( 'Date' ), 'Date'[Month] = EDATE ( d, -12 ) ) )
VAR n = COUNTROWS ( t2 )
"""
add('Focus Bullet 1', _FT + """VAR last3 = AVERAGEX ( FILTER ( t2, [Value] > n - 3 ), [@cy] ) VAR prev3 = AVERAGEX ( FILTER ( t2, [Value] > n - 6 && [Value] <= n - 3 ), [@cy] )
VAR chg = DIVIDE ( last3 - prev3, ABS ( prev3 ) )
RETURN "• " & IF ( n < 6, "Fewer than six months closed: no trend statement yet.",
    [Focus Name] & IF ( chg >= 0.02, " strengthened", IF ( chg <= -0.02, " softened", " held steady" ) ) & " toward period end: last 3 months " & FORMAT ( chg, "+0%;-0%" ) & " vs the 3 before." )""",
    ISF, None, 'Summary bullet 1: direction toward period end (average of the last three months versus the three before; within 2% counts as steady).')
add('Focus Bullet 2', _FT + """VAR pk = TOPN ( 1, t2, [@cy], DESC )
RETURN "• Peak month was " & FORMAT ( MAXX ( pk, [@d] ), "mmm yyyy" ) & " (" & """ + money('MAXX ( pk, [@cy] )') + """ & ")." """, ISF, None, 'Summary bullet 2: month with the highest value in the year to date.')
add('Focus Bullet 3', _FT + """VAR cy = SUMX ( t2, [@cy] ) VAR py = SUMX ( t2, [@py] ) VAR g = DIVIDE ( cy - py, ABS ( py ) )
RETURN "• Year to date " & IF ( ISBLANK ( py ), "has no prior-year comparison.", IF ( cy >= py, "is above", "is below" ) & " prior year by " & FORMAT ( ABS ( g ), "0.0%" ) & "; "
    & COUNTROWS ( FILTER ( t2, [@cy] >= [@py] ) ) + 0 & " of " & n & " months beat their prior-year month." )""", ISF, None, 'Summary bullet 3: year to date versus prior year, and how many months beat their prior-year month.')
add('Focus Bullet 4', _FT + """VAR cv = DIVIDE ( STDEVX.P ( t2, [@cy] ), ABS ( AVERAGEX ( t2, [@cy] ) ) )
RETURN "• Monthly pattern is " & IF ( cv > 0.2, "volatile", "steady" ) & ": months vary by " & FORMAT ( cv, "0%" ) & " around the average." """, ISF, None,
    'Summary bullet 4: volatility, as the coefficient of variation of the monthly values (above 20% is called volatile).')
add('PT ISX', '"Income Statement Explorer · " & [IS Range]', PH)
add('PS ISX', '"Current year against prior year, by section and line · " & [Period Label] & " · costs shown negative, so a positive change is always favourable"', PH)
add('VT Focus Summary', '"Summary for " & [Focus Name]', VT)
add('VT Focus Trend', '[Focus Name] & " by month: current year vs prior year · " & [Currency Label]', VT)
add('Sub Focus Trend', '"Pick a line in the Focus slicer; the summary and this trend follow it."', SB)
add('VT ISX', '"Income statement · CY vs PY · " & [Currency Label] & IF ( [Unit Divisor] = 1000, " thousands", "" )', VT)
add('Sub ISX', '"Click + on a section to see its lines. % Rev = share of net revenue; bps = change in that share (100 bps = 1 pt)."', SB)
add('VT ISX Method', '"Method, assumptions and trade-offs"', VT)
add('Sub ISX Method', '"How this page is built and what to keep in mind when reading it."', SB)
add('Footer ISX', FOOT + ' & " · Layout after the Goodly dynamic P&L; comparison is prior year, not budget"', '10 Layout')

# ---- 6.5 Rolling Forecast (after Goodly's Budget vs Actual, level 3): actual to a chosen month, budget after it, checked against the target
RFF = '14 Rolling Forecast'
PALETTE.update({'Actual Tint': ('#DCE8F7', '#1E3350'), 'Budget Tint': ('#FBE3E0', '#4A2622')})
for _k in ('Actual Tint', 'Budget Tint'):
    add(f'Col {_k}', f'IF ( [Is Dark], "{PALETTE[_k][1]}", "{PALETTE[_k][0]}" )', '10 Theme', None, f'Theme colour "{_k}": cell shading on the Rolling Forecast page.')
add('RF Cutoff', "VAR picked = SELECTEDVALUE ( 'Actuals Until'[Month] )\nRETURN IF ( ISBLANK ( picked ), [Selected Month], picked )", RFF, 'mmm yyyy',
    'Last month treated as actual on the Rolling Forecast page: the Actuals Until slicer, or the reporting month when nothing is picked.')
_RF = f"""VAR cut = [RF Cutoff] VAR fy = {FYN('cut')}
VAR t = ADDCOLUMNS ( GENERATESERIES ( 1, 12, 1 ), "@d", DATE ( fy - 1, 3 + [Value], 1 ) )   -- the twelve months of the cut-off's fiscal year
"""
_ACT = "CALCULATE ( [Metric Actual (in context)], REMOVEFILTERS ( 'Date' ), 'Date'[Month] = d )"
_BUD = "CALCULATE ( [Metric Budget (in context)], REMOVEFILTERS ( 'Date' ), 'Date'[Month] = d )"
add('RF Value', f"""VAR cut = [RF Cutoff] VAR fy = {FYN('cut')}
-- months on the column (one month in a cell, all twelve in the Total column)
VAR t = ADDCOLUMNS ( VALUES ( 'Date'[Fiscal Month Number] ), "@d", DATE ( fy - 1, 3 + 'Date'[Fiscal Month Number], 1 ) )
RETURN SUMX ( t, VAR d = [@d] RETURN IF ( d <= cut, {_ACT}, {_BUD} ) )""", RFF, FK,
    'Rolling forecast cell: actual for months up to the cut-off, budget for later months. The Total column adds both, which is the rolling forecast for the year.')
add('RF Cell Color', f"""VAR cut = [RF Cutoff] VAR fy = {FYN('cut')}
RETURN IF ( HASONEVALUE ( 'Date'[Fiscal Month Number] ),
    IF ( DATE ( fy - 1, 3 + MAX ( 'Date'[Fiscal Month Number] ), 1 ) <= cut, [Col Actual Tint], [Col Budget Tint] ),
    [Col Subtotal] )""", '8 Formatting', None, 'Cell shading on the Rolling Forecast matrix: blue = actual month, red tint = budget month, grey = total.')
add('RF Actual to Date', _RF + f'RETURN SUMX ( FILTER ( t, [@d] <= cut ), VAR d = [@d] RETURN {_ACT} )', RFF, F, 'Actual from the start of the fiscal year to the cut-off month, for the selected metric.')
add('RF Remaining Budget', _RF + f'RETURN SUMX ( FILTER ( t, [@d] > cut ), VAR d = [@d] RETURN {_BUD} )', RFF, F, 'Budget for the months after the cut-off.')
add('RF Total', '[RF Actual to Date] + [RF Remaining Budget]', RFF, F, 'Rolling forecast for the fiscal year: actual to the cut-off plus budget for the remaining months.')
add('RF Target', _RF + f'RETURN SUMX ( t, VAR d = [@d] RETURN {_BUD} )', RFF, F, "Target = the full-year budget of the cut-off's fiscal year.")
add('RF Gap', 'IF ( NOT ISBLANK ( [RF Target] ), [RF Total] - [RF Target] )', RFF, F, 'Rolling forecast minus target. Positive = on track (also for cost metrics, which are stored negative). Blank when there is no target.')
add('RF Attainment %', 'DIVIDE ( [RF Total], [RF Target] )', RFF, P, 'Rolling forecast as a share of the target.')
add('RF Months Elapsed', "VAR cut = [RF Cutoff] RETURN MOD ( MONTH ( cut ) + 8, 12 ) + 1", RFF, '0', 'Fiscal months closed at the cut-off (April = 1).')
add('RF Months Left', '12 - [RF Months Elapsed]', RFF, '0', 'Fiscal months after the cut-off.')
add('RF Required per Month', 'IF ( NOT ISBLANK ( [RF Target] ), DIVIDE ( [RF Target] - [RF Actual to Date], [RF Months Left] ) )', RFF, F, 'What each remaining month must deliver to land exactly on target.')
add('RF Average per Month', 'DIVIDE ( [RF Actual to Date], [RF Months Elapsed] )', RFF, F, 'Average actual per closed month.')
add('RF Run-Rate Total', '[RF Actual to Date] + [RF Average per Month] * [RF Months Left]', RFF, F, 'Cross-check (average-month projection): the year if the remaining months repeat the year-to-date average month. Not the same as the run-rate on tab 3, which scales the remaining budget by the year-to-date beat.')
add('RF Run-Rate Gap', 'IF ( NOT ISBLANK ( [RF Target] ), [RF Run-Rate Total] - [RF Target] )', RFF, F, 'Average-month projection minus target.')
add('RF Status', 'IF ( NOT ISBLANK ( [RF Total] ), IF ( NOT ISBLANK ( [RF Target] ), IF ( [RF Gap] >= 0, "✓ On track", "✗ Short" ), "No target" ) )', RFF, None, 'On track when the rolling forecast is at or above target.')
tone('RF Status Color', 'IF ( NOT ISBLANK ( [RF Target] ), [RF Gap] >= 0 )', 'Green when the rolling forecast reaches the target.')
add('RF Run-Rate Status', 'IF ( NOT ISBLANK ( [RF Total] ), IF ( NOT ISBLANK ( [RF Target] ), IF ( [RF Run-Rate Gap] >= 0, "✓ Reaches", "✗ Misses" ), "No target" ) )', RFF, None, 'Whether the average-month projection reaches the target.')
tone('RF Run-Rate Color', 'IF ( NOT ISBLANK ( [RF Target] ), [RF Run-Rate Gap] >= 0 )', 'Green when the average-month projection reaches the target.')
for _n in ('RF Total', 'RF Target', 'RF Required per Month', 'RF Run-Rate Total'):
    add(f'KV {_n}', kv_expr(_n), '11 KPI Cards')
add('RF Total Text', '[RF Status] & " · " & ' + money('[RF Gap]', 'signed') + ' & " vs target (" & FORMAT ( [RF Attainment %], "0%" ) & ")"', RFF, None, 'Card text: status, gap and attainment of the rolling forecast.')
add('RF Target Text', '"Full-year budget FY" & ' + FYN('[RF Cutoff]') + ' & " · " & [Metric Name]', RFF, None, 'Card text: which target is used.')
add('RF Required Text', '"needed in each of " & [RF Months Left] & " months · average so far " & ' + money('[RF Average per Month]'), RFF, None, 'Card text: required monthly amount next to the average achieved so far.')
tone('RF Required Color', 'IF ( [RF Months Left] > 0 && NOT ISBLANK ( [RF Target] ), [RF Average per Month] >= [RF Required per Month] )', 'Green when the average month so far is at least what the remaining months require.')
add('RF Run-Rate Text', '[RF Run-Rate Status] & " target · " & ' + money('[RF Run-Rate Gap]', 'signed') + ' & " if the average month repeats"', RFF, None, 'Card text: verdict of the average-month projection.')
add('PT RF', '"Rolling Forecast · " & [Metric Name] & " · actuals until " & FORMAT ( [RF Cutoff], "mmm yyyy" )', PH)
add('PS RF', '"Will we reach the target? Rolling forecast " & ' + money('[RF Total]') + ' & " vs target " & ' + money('[RF Target]') + ' & ": " & [RF Status] & " (" & ' + money('[RF Gap]', 'signed') + ' & "). Average-month view: " & [RF Run-Rate Status] & "."', PH)
add('VT RF Matrix', '[Metric Name] & " by entity and month · blue = actual, red tint = budget · " & [Currency Label] & " thousands"', VT)
add('Sub RF Matrix', '"Move the Actuals Until slicer to replay any month end: months up to it show actuals, later months show budget, and Total is the rolling forecast."', SB)
add('VT RF Table', '"Can each entity reach its target?"', VT)
add('Sub RF Table', """VAR t = FILTER ( ADDCOLUMNS ( VALUES ( Entity[EntityName] ), "@g", [RF Gap], "@t", [RF Target] ), NOT ISBLANK ( [@t] ) )
RETURN COUNTROWS ( FILTER ( t, [@g] >= 0 ) ) + 0 & " of " & COUNTROWS ( t ) + 0 & " budgeted entities are on track. Required = what each remaining month must deliver; compare it with the average so far." """, SB)
add('VT RF Method', '"Method, assumptions and trade-offs"', VT)
add('Sub RF Method', '"How the forecast is built and where it can mislead."', SB)
add('Footer RF', FOOT + ' & " · Layout after the Goodly Budget vs Actual; forecast = actual + remaining budget"', '10 Layout')

# ---- 6.6 Sankey: how net revenue flows to net income, drawn as one SVG image (no custom visual to install)
def _sankey():
    N = lambda e: f'FORMAT ( {e}, "0.0" )'
    def link(xa, ya, xb, yb, h, col):
        xm = (xa + xb) / 2
        return (f'"<path d=\'M{xa}," & {N(ya)} & " C{xm}," & {N(ya)} & " {xm}," & {N(yb)} & " {xb}," & {N(yb)} & " L{xb}," & {N(f"{yb} + {h}")} & " C{xm}," & {N(f"{yb} + {h}")} & " {xm}," & {N(f"{ya} + {h}")} '
                f'& " {xa}," & {N(f"{ya} + {h}")} & " Z\' fill=\'" & {col} & "\' fill-opacity=\'0.30\'/>"')
    def node(x, y, h, col):
        return f'"<rect x=\'{x}\' y=\'" & {N(y)} & "\' width=\'14\' height=\'" & {N(f"MAX ( {h}, 1 )")} & "\' rx=\'2\' fill=\'" & {col} & "\'/>"'
    def label(x, y, h, anchor, name, val):
        return (f'"<text x=\'{x}\' y=\'" & {N(f"{y} + {h} / 2 - 2")} & "\' text-anchor=\'{anchor}\' font-family=\'DIN, Segoe UI, sans-serif\' font-size=\'13\' font-weight=\'700\' fill=\'" & [Col Title] & "\'>{name}</text>"'
                f' & "<text x=\'{x}\' y=\'" & {N(f"{y} + {h} / 2 + 13")} & "\' text-anchor=\'{anchor}\' font-family=\'DIN, Segoe UI, sans-serif\' font-size=\'12\' fill=\'" & [Col Muted] & "\'>" & {money(val)} & " (" & FORMAT ( DIVIDE ( {val}, rev ), "0%" ) & ")</text>"')
    X1, X2, X3, X4, X5 = 160, 370, 580, 790, 1000   # last column leaves ~260 px for its labels
    A, G, B = '[Col Accent]', '[Col Good]', '[Col Bad]'
    parts = []
    for r, y, tgt, nm in (('r1', 'yR1', 'y0', 'North America'), ('r2', 'yR2', 'y0 + hR1', 'Europe'), ('r3', 'yR3', 'y0 + hR1 + hR2', 'Pacific')):
        h = f'{r} * k'
        parts += [link(X1 + 14, y, X2, tgt, h, A), node(X1, y, h, A), label(X1 - 8, y, h, 'end', nm, r)]
    parts += [node(X2, 'y0', 'rev * k', A), label(X2 + 7, 'y0 - 34', '0', 'middle', 'Net revenue', 'rev'),
              link(X2 + 14, 'y0', X3, 'y0', 'gp * k', G), link(X2 + 14, 'y0 + gp * k', X3, 'yC', 'cgs * k', B),
              node(X3, 'y0', 'gp * k', G), label(X3 + 22, 'y0', 'gp * k', 'start', 'Gross profit', 'gp'),
              node(X3, 'yC', 'cgs * k', B), label(X3 + 22, 'yC', 'cgs * k', 'start', 'Cost of sales', 'cgs'),
              link(X3 + 14, 'y0', X4, 'y0', 'eb * k', G), link(X3 + 14, 'y0 + eb * k', X4, 'yO', 'ox * k', B),
              node(X4, 'y0', 'eb * k', G), label(X4 + 22, 'y0', 'eb * k', 'start', 'EBITDA', 'eb'),
              node(X4, 'yO', 'ox * k', B), label(X4 + 22, 'yO', 'ox * k', 'start', 'Operating expenses', 'ox'),
              link(X4 + 14, 'y0', X5, 'y0', 'ni * k', G), link(X4 + 14, 'y0 + ni * k', X5, 'yB', 'bl * k', B),
              node(X5, 'y0', 'ni * k', G), label(X5 + 22, 'y0', 'ni * k', 'start', 'Net income', 'ni'),
              node(X5, 'yB', 'bl * k', B), label(X5 + 22, 'yB', 'bl * k', 'start', 'Depreciation, interest, tax', 'bl')]
    body = '\n    & '.join(parts)
    return f"""-- flows, all as positive sizes (costs are stored negative in the model)
VAR rev = [Revenue] VAR gp = [Gross Profit] VAR cgs = rev - gp VAR eb = [EBITDA] VAR ox = gp - eb VAR ni = [Net Income] VAR bl = eb - ni
VAR r1 = CALCULATE ( [Revenue], KEEPFILTERS ( Entity[Region] = "North America" ) ) + 0
VAR r2 = CALCULATE ( [Revenue], KEEPFILTERS ( Entity[Region] = "Europe" ) ) + 0
VAR r3 = CALCULATE ( [Revenue], KEEPFILTERS ( Entity[Region] = "Pacific" ) ) + 0
-- a Sankey can only draw positive flows: fall back to a message when a profit level is negative in the selection
VAR ok = rev > 0 && gp > 0 && eb > 0 && ni > 0 && cgs >= 0 && ox >= 0 && bl >= 0 && r1 >= 0 && r2 >= 0 && r3 >= 0
-- layout: 330 px of height for net revenue; every other node uses the same scale, so widths are comparable
VAR k = DIVIDE ( 330, rev ) VAR y0 = 56 VAR vgap = 16
VAR hR1 = r1 * k VAR hR2 = r2 * k VAR yR1 = y0 VAR yR2 = yR1 + hR1 + vgap VAR yR3 = yR2 + hR2 + vgap
VAR yC = y0 + gp * k + 30 VAR yO = y0 + eb * k + 30 VAR yB = y0 + ni * k + 30
VAR svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1280 470'>"
    & {body}
    & "</svg>"
VAR msg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1280 470'><text x='640' y='230' text-anchor='middle' font-family='DIN, Segoe UI, sans-serif' font-size='18' fill='" & [Col Muted] & "'>A Sankey needs positive flows: revenue or a profit level is negative for this selection.</text></svg>"
RETURN "data:image/svg+xml;utf8," & SUBSTITUTE ( SUBSTITUTE ( IF ( ok, svg, msg ), "%", "%25" ), "#", "%23" )"""
add('SVG Sankey', _sankey(), '15 Sankey', None,
    'Income-statement Sankey as an SVG image: revenue by region flows into net revenue, then splits into cost of sales, operating expenses, items below EBITDA and net income. Band width is proportional to the amount.')
MEAS[-1]['cat'] = 'ImageUrl'
add('PT Sankey', '"Where the revenue goes · " & [Period Label]', PH)
add('PS Sankey', '"Of every $100 of net revenue, $" & FORMAT ( DIVIDE ( [Net Income], [Revenue] ) * 100, "0" ) & " reaches net income: $" & FORMAT ( DIVIDE ( -[Cost of Sales], [Revenue] ) * 100, "0" ) & " goes to cost of sales and $" & FORMAT ( DIVIDE ( -[Operating Expenses], [Revenue] ) * 100, "0" ) & " to operating expenses."', PH)
add('VT Sankey', '"From revenue to net income · band width = amount · " & [Currency Label]', VT)
add('Sub Sankey', '"Blue = revenue, green = what is kept at each level, red = what is spent. Percentages are shares of net revenue. Follows every slicer."', SB)
add('Footer Sankey', FOOT + ' & " · Drawn by a DAX measure as SVG; no custom visual"', '10 Layout')

# ---- 6.7 method notes shown on the two replica pages (also in docs/04-methodology.md)
STORY_ROWS += [
    ('ISX Method', 1, 'What it shows', 'The P&L for the period against the same period last year: amount, share of revenue, change, change % and the shift in share of revenue in basis points.'),
    ('ISX Method', 2, 'How it is built', 'Sections and lines are rows of the Report Line table; each line lists its accounts in Report Line Map. A section header sums the distinct accounts of its lines, so no subtotal is hard-coded.'),
    ('ISX Method', 3, 'Assumptions', 'Period = the Period slicer (YTD by default) to the selected month. Prior year = same months one year earlier. Costs are negative, so a positive change is favourable on every row.'),
    ('ISX Method', 4, 'Strengths', 'Adding or re-ordering a line is a data change, not a DAX change. Every column uses one definition, so cards, trend and matrix always agree.'),
    ('ISX Method', 5, 'Limits', 'Compares with prior year only (budget is on page 3). Change % is blank when signs differ or the base is tiny. The summary bullets are rules (thresholds 2% and 20%), not judgement.'),
    ('ISX Method', 6, 'Consider', 'New entities inflate growth: check the organic figure on page 2. Basis points are computed on net revenue of each year, so mix shifts move them even when costs are flat.'),
    ('RF Method', 1, 'What it shows', 'For each entity: actuals up to the Actuals Until month, budget after it, and the total. That total is the rolling forecast, compared with the full-year budget (the target).'),
    ('RF Method', 2, 'How it is built', 'Actuals Until is a disconnected slicer. One measure returns actual or budget per month depending on the cut-off; totals, gap, attainment and required run-rate derive from it.'),
    ('RF Method', 3, 'Assumptions', 'Remaining months land exactly on budget. Target = original full-year budget. Actual and budget share the same grain (month x entity x account), so no allocation is needed.'),
    ('RF Method', 4, 'Strengths', 'Simple, auditable and replayable: move the slicer to see what the forecast said at any month end. No statistical model to explain or maintain.'),
    ('RF Method', 5, 'Limits', 'It carries the year-to-date variance forward but assumes it stops growing. Seasonality lives only in the budget. Entities without a budget have no target and show blank.'),
    ('RF Method', 6, 'Cross-check', 'The average-month projection assumes the average month so far repeats (tab 3 uses a different run-rate: remaining budget scaled by the year-to-date beat). When the two methods disagree, the truth is usually between them: read Required per month against the average so far.'),
    ('RF Method', 7, 'If grains differ', 'If budget were yearly or by region only, allocate it to months with a seasonality key (prior-year share) before using this page; never compare a monthly actual with an unallocated annual budget.'),
]
for _t in TABLES:
    if _t['name'] == 'Story':
        _t['m'] = m_table([('Page', 'text'), ('Sort', 'Int64.Type'), ('Section', 'text'), ('Text', 'text')], STORY_ROWS)


# ======================================================================== v5: documentation pass (TOM descriptions, DAX and M comments, query groups, diagram)
# ---- 5.1 remove presentation leftovers that no visual or measure uses (analytical KPI measures are kept as reusable building blocks)
DROP = [r' Spark$', r' Progress Bar$', r'^Title (Overview|Executive|Income Statement|Balance Sheet|Overview Revenue|DQ)$', r'^Lbl Current View$',
        r'^Col (Selected|Selected Text|Side)$', r'^DQ Detected Text$', r'^(Cost of Sales|EBIT|Gross Profit|Operating Expenses) vs Budget Text$',
        r'^(Cost of Sales|EBIT|Gross Profit) Var Color$', r'^(Revenue|Cost of Sales|Gross Profit|Operating Expenses|EBITDA|EBIT|Net Income) Monthly Actual$']
MEAS[:] = [m for m in MEAS if not (any(_re.search(p, m['name']) for p in DROP) and not m['name'].startswith('SVG '))]

# ---- 5.2 a description for every measure. Families share one sentence pattern; everything else is written out.
_KPI_DEF = {'Revenue': 'Net revenue (gross sales less returns and discounts)', 'Cost of Sales': 'Cost of sales (negative)', 'Gross Profit': 'Gross profit (net revenue less cost of sales)',
            'Operating Expenses': 'Total operating expenses (negative)', 'EBITDA': 'EBITDA (gross profit less operating expenses)', 'EBIT': 'Operating profit (EBITDA less depreciation and amortization)',
            'Net Income': 'Net income after interest, other items and tax'}
_PERIOD = 'for the period chosen in the Period slicer (MTD, QTD or YTD) ending at the selected month'
_WINDOW = {'MTD': 'the selected month only', 'QTD': 'the calendar quarter to the selected month', 'YTD': 'the fiscal year (from 1 April) to the selected month'}
_PAGE = {'Overview': 'Overview', 'Executive': 'Executive', 'BvA': 'Budget vs Actual', 'IS': 'P&L', 'BS': 'Balance Sheet', 'DQ': 'Data Quality', 'Notes': 'Notes'}
_MANUAL = {
    'Currency Label': 'Reporting currency code chosen in the Currency slicer (CAD when nothing is selected).',
    'Selected Fiscal Year': 'Fiscal-year label of the selected month, e.g. FY2027.',
    'Fiscal Month Of Selection': 'Fiscal month number of the selected month (April = 1, March = 12).',
    'Period Label': 'Text such as "YTD Oct 2026 · CAD" used in titles.',
    'Actual': 'Amount for the Actual scenario. Base of every actual measure.',
    'Budget': 'Amount for the Budget scenario. Base of every budget measure.',
    'Actual (Period)': f'Actual {_PERIOD}.', 'Budget (Period)': f'Budget {_PERIOD}.', 'Prior Year (Period)': f'Actual for the same period one year earlier ({_PERIOD}).',
    'Monthly Budget (Selected FY)': 'Month-axis charts: budget for each fiscal month of the selected year.',
    'Monthly Prior Year (Selected FY)': 'Month-axis charts: actual for the same fiscal month one year earlier.',
    'Cumulative Actual (Selected FY)': 'Month-axis charts: actual accumulated from 1 April to each month, up to the selected month.',
    'Cumulative Budget (Selected FY)': 'Month-axis charts: budget accumulated from 1 April to each month.',
    'Line Budget': 'Budget for the report line on the row, for the Period view.', 'Line Prior Year': 'Same period last year for the report line on the row.',
    'Line Var vs Prior Year': 'Line actual minus the same period last year.', 'Line % of Revenue': 'Report line as a share of net revenue (common-size P&L).',
    'Line Outlook FY': 'Full-year outlook (actual to date + remaining budget) for the report line.', 'Line Budget FY': 'Full fiscal-year budget for the report line.',
    'Line Closing Balance': 'Balance at the selected month end for the balance-sheet line on the row.',
    'Line Prior Year-End Balance': 'Balance at the previous fiscal year end (31 March) for the balance-sheet line.',
    'Line Balance Change': 'Closing balance minus the previous year-end balance.',
    'Line Var Color': 'Text colour for line variances: green when favourable (variance >= 0), red when unfavourable.',
    'Line Row Background': 'Row shading for statement tables: subtotal and total rows are tinted, detail rows use the panel colour.',
    'Line Growth Color': 'Text colour for growth vs prior year on statement lines: green when favourable.',
    'Metric Var Color': 'Green when the selected metric is favourable to budget, red when unfavourable.',
    'Metric Gap Color': 'Green when the full-year outlook for the selected metric is at or above the full-year budget.',
    'Gross Margin Var Color': 'Green when gross margin is at or above the budget margin.',
    'Net Income Outlook Gap Color': 'Green when the full-year net income outlook is at or above the full-year budget.',
    'Cash Change Color': 'Green when cash is at or above the previous year-end balance, red when it fell.',
    'Exception Color': 'Text colour in the top-5 exception table: green favourable, red unfavourable.',
    'Entity Budget Status Color': 'Red for entities with no budget, amber for under-budgeted entities, neutral otherwise.',
    'OpEx % of Revenue': 'Operating expenses as a share of net revenue (shown positive).',
    'Gross Margin Text': 'Gross margin versus budget margin, in percentage points.',
    'Organic Growth %': 'Growth of like-for-like revenue versus the same period last year (entities that traded in both periods).',
    'Revenue Var vs Budget (Budgeted Entities)': 'Revenue variance to budget counting only entities that have a budget for the period.',
    'Revenue Var % vs Budget (Budgeted Entities)': 'Revenue variance % to budget counting only entities that have a budget.',
    'Entities Reporting': 'Number of entities with actuals in the selected month.',
    'Revenue TTM': 'Net revenue for the twelve months ending at the selected month (denominator for receivable days).',
    'Entity Joined FY': 'Fiscal year in which the entity first reported actuals.',
    'Revenue Var Core': 'Revenue variance to budget for the core region only.', 'Revenue Var % Core': 'Revenue variance % to budget for the core region only.',
    'EBITDA Var Core': 'EBITDA variance to budget for the core region only.', 'EBITDA Var % Core': 'EBITDA variance % to budget for the core region only.',
    'Net Income Attributable to Group': 'Net income multiplied by the group\'s effective ownership of each entity: the share belonging to the parent.',
    'Metric Name': 'Name of the P&L measure picked in the Metric slicer (Revenue when nothing is selected).',
    'Metric Outlook Gap': 'Full-year outlook minus full-year budget for the selected metric.',
    'Metric Actual (in context)': 'Selected metric, actual, for whatever dates are in filter context (used inside iterators over months).',
    'Metric Budget (in context)': 'Selected metric, budget, for whatever dates are in filter context.',
    'Cash': 'Cash and cash equivalents at the selected month end.', 'Total Assets': 'Total assets at the selected month end.', 'Total Equity': 'Total equity at the selected month end.',
    'Current Ratio': 'Current assets / current liabilities at the selected month end.', 'Debt to Equity': 'Short- and long-term debt / total equity at the selected month end.',
    'Cost of Sales TTM': 'Cost of sales for the twelve months ending at the selected month (denominator for inventory and payable days).',
    'Cash Conversion Cycle (days)': 'Receivable days + inventory days - payable days: days of trading the group must finance.',
    'Insight Perimeter': 'Narrative: revenue from new entities, revenue without a budget, and the variance excluding unbudgeted entities.',
    'Insight Cost Absorption': 'Narrative: how much of the gross-profit upside the operating-expense overrun absorbed.',
    'Insight Outlook': 'Narrative: full-year net income outlook versus budget.',
    'Insight People Cost': 'Narrative: salaries versus budget, share of the opex overrun, headcount and cost per head versus last year.',
    'Title BvA': 'Subtitle of the Budget vs Actual page: selected metric, amount and variance % to budget.',
    'Title BvA Trend': 'Title of the monthly actual / outlook / budget chart.', 'Title BvA Outlook': 'Title of the cumulative chart: full-year outlook versus budget.',
    'Title Variance by Entity': 'Title of the variance-by-entity bar chart.', 'Title Revenue Bridge': 'Title of the revenue growth bridge: total and organic growth.',
    'Title EBITDA Bridge': 'Title of the EBITDA variance bridge.',
    'Metric Var Text': 'Card text: variance of the selected metric to budget, amount and %.', 'Metric Gap Text': 'Card text: full-year outlook minus full-year budget.',
    'Metric Growth Text': 'Card text: growth of the selected metric versus last year.', 'Metric Budget FY Text': 'Card text: full-year budget for the selected metric.',
    'Net Income Outlook Gap Text': 'Card text: full-year net income outlook minus budget.', 'Cash Change Text': 'Card text: change in cash since the previous fiscal year end.',
    'DQ Unmapped Accounts With Activity': 'Accounts with postings that no report line includes (excluding statistical accounts). Must be 0.',
    'DQ Accounts Missing From Chart': 'Account keys in the ledger that are not in the chart of accounts. Must be 0.',
    'DQ Rows Missing FX Rate': 'Ledger rows for which no exchange rate was found. Must be 0.',
    'DQ Duplicates Removed': 'Exact duplicate rows found in source files and removed by Power Query.',
    'DQ Blank Departments Fixed': 'Rows with a blank department in the source, mapped to department 0 "Unassigned".',
    'DQ Files With Schema Drift': 'Source files whose columns were reordered or extended; columns are matched by name.',
    'DQ Files Loaded': 'Number of ledger files (actuals and budget) currently loaded.',
    'DQ Synthetic Budget Share': 'Share of budget rows generated synthetically rather than taken from the source ledger.',
    'Brand': 'Report name shown at the top of the sidebar.', 'Brand Sub': 'Company name shown under the report name.', 'Tagline': 'Tagline at the bottom of the sidebar.',
    'Lbl Filters': 'Heading above the slicers in the sidebar.', 'Last Refreshed': 'Refresh time (UTC) and the close month, shown top right on every page.',
    'Footer Note 1': 'Numbered footer note 1 (same on every page).', 'Footer Note 2': 'Numbered footer note 2 (same on every page).',
    'Ctx Period': 'Fiscal year, period view and month currently in effect.', 'Ctx Currency': 'Reporting currency currently in effect.',
    'Ctx Region': 'Regions selected: "All regions", the names (up to two) or a count.', 'Ctx Entity': 'Entities selected: all, the names (up to two) or a count.',
    'Ctx Department': 'Departments selected: all, the names (up to two) or a count.',
    'Exception Var': 'Budget variance for rows ranked in the top 5 exceptions; blank otherwise, which keeps the table to five rows.',
    'Exception Var %': 'Budget variance % for the top-5 exception rows.', 'Exception Actual': 'Actual for the top-5 exception rows.',
    'Exception Rank Shown': 'Rank 1 to 5 for the exception rows; blank for everything else.',
    'Headcount PY': 'Closing headcount twelve months before the selected month.', 'Salaries Var vs Budget': 'Salaries and benefits: actual minus budget (negative = over budget).',
    'Salary Cost per Head PY': 'Salary cost per head for the same period last year.',
    'Net Income Outlook Progress': 'Full-year net income outlook as a share of the full-year budget.', 'Metric FY Progress': 'Selected metric year to date as a share of its full-year budget.',
    'Metric Outlook Progress': 'Full-year outlook of the selected metric as a share of its full-year budget.',
    'Gross Margin Progress Text': 'Card text: budget and prior-year gross margin for reference.', 'Cash Progress Text': 'Card text: previous year-end cash and receivable days.',
    'Entity Budget Status Summary': 'Card text listing entities without a budget.', 'Sub Entities Short': 'Card text: number of entities without a credible budget.',
    'Revenue Growth Short': 'Card text: total revenue growth versus last year.',
    'Net Income Outlook Progress Text': 'Card text: full-year net income outlook as a share of the full-year budget.',
}
def describe(m):
    n = m['name']
    if n in _MANUAL: return _MANUAL[n]
    g = _re.match(r'^(Actual|Budget|Prior Year) (MTD|QTD|YTD)$', n)
    if g:
        what = {'Actual': 'Actual', 'Budget': 'Budget', 'Prior Year': 'Actual one year earlier'}[g.group(1)]
        return f'{what} for {_WINDOW[g.group(2)]}. Ignores the date slicer except to find the selected month.'
    for k, d in _KPI_DEF.items():
        if n == k: return f'{d} {_PERIOD}.'
        if n == f'{k} Budget': return f'Budget for {k.lower()}, {_PERIOD}.'
        if n == f'{k} PY': return f'{k} for the same period one year earlier.'
        if n == f'{k} Var vs Budget': return f'{k}: actual minus budget. Positive = favourable (costs are stored negative).'
        if n == f'{k} Var % vs Budget': return f'{k} variance as % of absolute budget. Blank when actual and budget have different signs.'
        if n == f'{k} Growth %': return f'{k} growth versus the same period last year. Blank when the signs differ.'
        if n == f'{k} Outlook FY': return f'{k} full-year outlook: actual to the selected month + budget for the remaining months.'
        if n == f'{k} Budget FY': return f'{k} budget for the full fiscal year of the selected month.'
        if n == f'{k} vs Budget Text': return f'Card text for {k.lower()}: variance % to budget and growth % versus last year, with direction arrows.'
        if n == f'{k} Var Color': return f'Green when {k.lower()} is favourable to budget, red when unfavourable.'
        if n == f'{k} Margin %': return f'{k} as a share of net revenue.'
        if n == f'{k} Margin % Budget': return f'Budgeted {k.lower()} as a share of budgeted net revenue.'
        if n == f'{k} Margin pts vs Budget': return f'{k} margin minus budget margin, in percentage points.'
        if n == f'{k} Progress Text': return f'Card text: {k.lower()} year to date as a share of the full-year budget, next to the share of the year elapsed.'
    g = _re.match(r'^Metric (Actual|Budget|PY|Var vs Budget|Var % vs Budget|Growth %|Outlook FY|Budget FY|Monthly Actual|Monthly Budget|Monthly Outlook|Monthly Prior Year|Cumulative Actual|Cumulative Outlook|Cumulative Budget|Progress Text|Outlook Progress Text)$', n)
    if g: return f'"{g.group(1)}" for the P&L measure picked in the Metric slicer on the Budget vs Actual page (Revenue by default).'
    if n.startswith('KV '): return f'KPI card value: [{n[3:]}] as text in the report number format ($ M/K for money, % for rates, x for ratios, whole numbers for counts).'
    if n.startswith('VT '): return 'Dynamic visual title: updates with the period, currency and selection.'
    if n.startswith('Sub '): return 'Insight subtitle: one sentence computed from the data behind the visual; rewrites itself with every filter.'
    if n.startswith('PT '): return f'Page title of the {_PAGE.get(n[3:], n[3:])} page.'
    if n.startswith('PS '): return f'Page subtitle of the {_PAGE.get(n[3:], n[3:])} page: the key figures in one line.'
    if n.startswith('Footer '): return f'Footer of the {_PAGE.get(n[7:], n[7:])} page: sources, exchange-rate policy, close month and page-specific caveats.'
    if n.startswith('Ctx Line '): return f'Header chip text: "{n[9:]}: <current selection>".'
    return None
for _m in MEAS:
    if not _m.get('desc'):
        _m['desc'] = describe(_m)
_missing = [m['name'] for m in MEAS if not m['desc']]
assert not _missing, f'measures without a description: {_missing}'

# ---- 5.3 a description for every column
COL_DESC = {
    'Account': {'AccountKey': 'Surrogate key of the account; joins to GL.', 'ParentAccountKey': 'Parent account in the chart-of-accounts hierarchy.', 'AccountCode': 'Account code as used in the ledger.',
                'AccountName': 'Account name.', 'AccountType': 'Revenue, Expenditures, Assets, Liabilities or Statistical; drives the sign.', 'UnaryOperator': 'Roll-up operator from the source chart (not used by the measures).',
                'Statement': 'Income Statement, Balance Sheet or Statistical; decides which exchange rate applies.'},
    'Entity': {'EntityKey': 'Surrogate key of the reporting entity; joins to GL.', 'ParentEntityKey': 'Parent in the group hierarchy (group > region > entity).', 'EntityName': 'Entity name.',
               'OwnershipPct': 'Share of this entity owned by its direct parent.', 'CurrencyCode': 'Local (functional) currency of the entity.'},
    'Department': {'DepartmentKey': 'Surrogate key of the department; 0 = Unassigned.', 'ParentDepartmentKey': 'Parent department group.', 'DepartmentName': 'Department name.'},
    'GL': {'Month': 'First day of the posting month.', 'EntityKey': 'Entity that posted the amount.', 'DepartmentKey': 'Department; 0 when blank in the source.', 'AccountKey': 'Account posted to.',
           'AmountLC': 'Amount in the entity\'s local currency, as posted (always positive in the source; closing balance for balance-sheet accounts).', 'Scenario': 'Actual or Budget.',
           'BudgetSource': 'Ledger (from the source data) or Synthetic (generated budget).', 'SourceFile': 'CSV file the row came from; used for data-quality counts.',
           'Rate Type': 'Which exchange rate the row uses: End (balance sheet), Budget (budget rows) or Avg (P&L actuals).', 'Rate to CAD': 'CAD per unit of the entity currency for the row\'s month and rate type.',
           'Rate USD to CAD': 'CAD per USD for the row\'s month and rate type; used to present results in USD.', 'Amount CAD': 'Amount in CAD with the reporting sign applied (costs negative). Base of [Amount].',
           'Amount USD': 'Amount in USD: the CAD amount divided by the USD rate.'},
    'FX': {'FXKey': 'Currency code | yyyy-MM; lookup key used by the GL rate columns.', 'CurrencyCode': 'Currency the rate converts from.', 'Month': 'First day of the month.',
           'AvgRate': 'Monthly average rate, CAD per unit (P&L actuals).', 'EndRate': 'Month-end rate, CAD per unit (balance sheet).', 'BudgetRate': 'Average rate of the previous fiscal year (budget and constant currency).',
           'RateStatus': 'Observed (published by the Bank of Canada) or Carried forward (after the last published month).'},
    'Report Line': {'LineKey': 'Line number; also the display order. 1-20 income statement, 101-120 balance sheet.', 'LineName': 'Line caption shown in statements.', 'Section': 'Statement section the line belongs to.',
                    'LineType': 'Detail, Subtotal or Total; drives row shading.', 'Statement': 'Income Statement or Balance Sheet.'},
    'Report Line Map': {'LineKey': 'Report line.', 'AccountKey': 'Account included in that line.'},
    'Date': {'Month': 'First day of the month; key of the calendar.', 'Year': 'Calendar year.', 'Fiscal Year Number': 'Fiscal year as a number (the year in which it ends).', 'Fiscal Year': 'Fiscal year label, e.g. FY2027.',
             'Fiscal Month Number': 'April = 1 ... March = 12.', 'Fiscal Quarter': 'Fiscal quarter, Q1 = April to June.', 'Month Name': 'Three-letter month, sorted in fiscal order.', 'Year Month': 'Month and year, e.g. Oct 2026.',
             'Month Index': 'Running month number, for sorting.', 'IsClosed': 'True for months up to the latest actuals month.', 'Period Status': 'Actual for closed months, Outlook for later months.'},
    'DQ File Log': {'Name': 'Source file name.', 'Folder': 'actuals or budget.', 'RawRows': 'Rows in the file before cleaning.', 'DuplicateRows': 'Exact duplicate rows found (and removed).',
                    'MissingDepartmentRows': 'Rows with a blank department.', 'SchemaDrift': 'True when the columns differ from the expected order or set.', 'Columns': 'Column names found in the file.'},
    'DQ Injection Log': {'Month': 'Month or range the injected issue affects.', 'Issue': 'Type of issue injected by the data generator.', 'RowsAffected': 'Rows affected.',
                         'Cause': 'Realistic cause the issue imitates.', 'Treatment': 'How the model handles it.'},
    'Story': {'Page': 'Page the row belongs to (Overview, DQ, Notes, Defs).', 'Sort': 'Display order within the page.', 'Section': 'Topic shown in the first column.', 'Text': 'Narrative text.'},
    'Refresh Info': {'Refreshed At': 'UTC time of the last refresh.'},
    'Insight': {'Key': 'Topic number; selects the narrative measure in [Insight Text].', 'Topic': 'Topic caption.'},
    'Metric': {'Metric': 'P&L measure offered by the Metric slicer.', 'LineKey': 'Report line the metric maps to.', 'Sort': 'Display order.'},
    '_Measures': {'Placeholder': 'Empty column: a table needs one column to exist.'},
}
_GENERIC = {'Sort': 'Display order.', 'Step': 'Step shown on the bridge axis.', 'Currency': 'Presentation currency.', 'View': 'Period view: YTD, QTD or MTD.', 'Mode': 'Light or Dark.'}
for _t in TABLES:
    for _c in _t['cols']:
        if not _c[2].get('desc'):
            _c[2]['desc'] = COL_DESC.get(_t['name'], {}).get(_c[0]) or _GENERIC[_c[0]]

# ---- 5.4 comments inside the DAX: each recurring pattern is explained once, at the top of every measure that uses it
PATTERN_NOTES = [
    ("TREATAS ( CALCULATETABLE ( VALUES ( 'Report Line Map'[AccountKey] )", 'Report-line pattern: the accounts mapped to a report line (Report Line Map) are applied to Account with TREATAS, so a line is data, not hard-coded DAX.'),
    ("TREATAS ( accts, Account[AccountKey] )", 'Template pattern: the report line (or metric) in context decides which accounts are summed, via TREATAS.'),
    ("REMOVEFILTERS ( 'Date' )", 'Date pattern: the date slicers are removed and replaced by an explicit month window built from [Selected Month], so every visual agrees on the period.'),
    ('_x / 1e6', 'Money-text pattern: each ( VAR _x = ... ) block returns an amount as text: $ with one decimal in millions, whole thousands below 1M.'),
    ('data:image/svg+xml', 'SVG pattern: the measure returns an image as text (data category Image URL); # is written %23 so colours survive URL encoding.'),
    ('[Col ', 'Theme pattern: colours come from the [Col ...] measures, which switch with the Light/Dark toggle.'),
    ('SUMX ( VALUES ( Entity[EntityKey] )', 'Per-entity pattern: evaluated entity by entity and then summed, because the rule applies to each entity separately.'),
]
for _m in MEAS:
    _notes = [txt for key, txt in PATTERN_NOTES if key in _m['expr']]
    if _notes and ('\n' in _m['expr'] or len(_m['expr']) > 110):
        _m['expr'] = '\n'.join('// ' + t for t in _notes) + '\n' + _m['expr']

# ---- 5.5 Power Query: step comments, and query groups so the Queries pane reads like the model
def _mnote(code, notes):
    """Insert a // comment line above each named step of an M query (keeps the step's indentation)."""
    for step, text in notes.items():
        hit = _re.search(r'^(\s*)' + _re.escape(step) + r' = ', code, _re.M)
        assert hit, f'M step {step!r} not found'
        code = code[:hit.start()] + f'{hit.group(1)}// {text}\n' + code[hit.start():]
    return code
FN_READ_CSV = _mnote(FN_READ_CSV, {
    'Target': 'Folder path to match, lower-cased. An empty subfolder means DataRoot itself.',
    'Hit': 'One static source for the whole model (Folder.Files(DataRoot)), filtered to the file: no gateway or privacy prompt.',
    'Source': 'Parse as UTF-8 CSV (65001).', 'Blanks': 'Empty strings become null so type conversion and null checks behave.'})
FN_LOAD_LEDGER = _mnote(FN_LOAD_LEDGER, {
    'Target': 'Folder to load, e.g. DataRoot\\actuals\\.', 'Csvs': 'Only ledger files: GL_*.csv. Dropping a file in adds a period; removing it removes the period.',
    'Parsed': 'Per file: promote headers, pick the six columns BY NAME (survives reordered or extra columns; a missing column becomes null), drop exact duplicate rows.',
    'DeptFixed': 'Blank department (ERP migration gap) is mapped to key 0 = "Unassigned" so no row is lost in the Department relationship.',
    'WithScenario': 'Tag every row with the scenario of the folder it came from (Actual or Budget).'})
M_GL = _mnote(M_GL, {'Actuals': 'One file per month in actuals\\, one file per fiscal year in budget\\.',
                     'Source': 'Rows from the source ledger have no BudgetSource: label them "Ledger" (synthetic budget rows already say "Synthetic").',
                     'Typed': 'Types are set with the en-US culture because the files use a point as the decimal separator.'})
M_FX = _mnote(M_FX, {
    'FY': 'Fiscal year of a date: April to March, named by the year it ends.', 'Observed': 'Rates published by the Bank of Canada (CAD per unit).',
    'GridEnd': 'Build a complete currency x month grid to the end of the fiscal year after the last published rate, so budget months always find a rate.',
    'Status': 'Months with no published rate are flagged, then filled with the last published rate (FillDown below).',
    'FYAvg': 'Budget rate = average of the PREVIOUS fiscal year, so budget variances are not distorted by currency moves.',
    'BudgetFix': 'First fiscal year has no previous year: fall back to the month\'s average rate.',
    'Keyed': 'Text key "CCY|yyyy-MM" used by LOOKUPVALUE in the GL rate columns.'})
M_DQ_FILES = _mnote(M_DQ_FILES, {
    'Expected': 'Column order of a clean export. Anything else is reported as schema drift.',
    'Profile': 'Profile every ledger file in one subfolder: raw rows, exact duplicates, blank departments and schema drift, measured BEFORE cleaning.',
    'Combined': 'Profile both folders so the Data Quality page can reconcile detected issues with the injection log.'})
for _t in TABLES:   # the helper tables above were captured before the comments were added
    _t.update({k: v for k, v in (('m', {'GL': M_GL, 'FX': M_FX, 'DQ File Log': M_DQ_FILES}.get(_t['name'])),) if v})
    if 'm' in _t and not _t['m'].lstrip().startswith('//'):
        _t['m'] = f"// {_t['desc']}\n" + _t['m']
QUERY_GROUPS = ['Parameters and functions', 'Dimensions', 'Facts', 'Report helpers', 'Data quality']
QUERY_GROUP_OF = {'Account': 'Dimensions', 'Entity': 'Dimensions', 'Department': 'Dimensions', 'Report Line': 'Dimensions', 'Report Line Map': 'Dimensions',
                  'GL': 'Facts', 'FX': 'Facts', 'DQ File Log': 'Data quality', 'DQ Injection Log': 'Data quality'}
for _t in TABLES:
    if 'm' in _t:
        _t['group'] = QUERY_GROUP_OF.get(_t['name'], 'Report helpers')

# ---- 5.6 model diagram: fact in the middle, dimensions around it, lookups beside the tables they serve, helpers in rows below
DIAGRAM = {  # table: (x, y, width, height)
    'GL': (620, 300, 250, 330), 'Date': (620, 20, 250, 250), 'Entity': (260, 300, 250, 220), 'Account': (980, 300, 250, 250), 'Department': (620, 660, 250, 150),
    'FX': (260, 20, 250, 220), 'Report Line Map': (1340, 300, 220, 120), 'Report Line': (1340, 450, 220, 190), '_Measures': (980, 20, 250, 250),
    'Reporting Currency': (0, 880, 200, 110), 'Period View': (220, 880, 200, 110), 'Metric': (440, 880, 200, 130), 'Theme Mode': (660, 880, 200, 110),
    'Revenue Bridge': (880, 880, 200, 110), 'EBITDA Bridge': (1100, 880, 200, 110), 'Cash Bridge': (1320, 880, 200, 110),
    'Insight': (0, 1040, 200, 110), 'Story': (220, 1040, 200, 150), 'Refresh Info': (440, 1040, 200, 100),
    'DQ File Log': (880, 1040, 220, 210), 'DQ Injection Log': (1120, 1040, 220, 170),
    'PL Focus': (660, 1040, 200, 130), 'Display Unit': (0, 1200, 200, 130), 'Actuals Until': (220, 1220, 200, 130), 'Data Dictionary': (1360, 1040, 240, 260),
}
assert set(DIAGRAM) == {t['name'] for t in TABLES}, set(DIAGRAM) ^ {t['name'] for t in TABLES}
