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
    def lit(v): return f'"{v}"' if isinstance(v, str) else str(v)
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
M_ = lambda x: f'FORMAT ( {x} / 1e6, "#,0.0" ) & "M"'
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
add('Title BvA', '[Metric Name] & " · " & [Period Label] & ": " & [Currency Label] & " " & ' + M_('[Metric Actual]') + ' & ", " & FORMAT ( ABS ( [Metric Var % vs Budget] ), "0.0%" ) & IF ( [Metric Var vs Budget] >= 0, " favourable", " unfavourable" ) & " to budget"', '6 Narrative')
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
add('Title Income Statement', '"Income statement · " & [Period Label] & " · costs shown negative, so a positive variance is favourable"', '6 Narrative')
add('Title Balance Sheet', '"Balance sheet at " & FORMAT ( [Selected Month], "mmm yyyy" ) & " vs year end " & FORMAT ( DATE ( ' + FYN('[Selected Month]') + ' - 1, 3, 1 ), "mmm yyyy" ) & " · " & [Currency Label]', '6 Narrative')
add('Title Overview Revenue', '"Net revenue by fiscal year and region · " & [Selected Fiscal Year] & " is year to date (" & FORMAT ( [As Of Month], "mmm yyyy" ) & ")"', '6 Narrative')
add('Title Revenue Bridge', '"Revenue growth vs prior year: " & FORMAT ( [Revenue Growth %], "+0.0%;-0.0%" ) & ", of which organic " & FORMAT ( [Organic Growth %], "+0.0%;-0.0%" )', '6 Narrative')
add('Title EBITDA Bridge', '"EBITDA vs budget: " & FORMAT ( [EBITDA Var vs Budget] / 1e6, "+#,0.0;-#,0.0" ) & "M, by driver"', '6 Narrative')
add('Title DQ', '"Data quality · " & [DQ Files Loaded] & " ledger files loaded · balance-sheet difference " & FORMAT ( [DQ Balance Sheet Difference], "#,0" )', '6 Narrative')

add('Insight Text', "SWITCH ( SELECTEDVALUE ( Insight[Key] ), 1, [Insight Perimeter], 2, [Insight Cost Absorption], 3, [Insight Outlook] )", '6 Narrative',
    None, 'Narrative for the topic on the row of an insight table.')
add('Entity Budget Status Color', 'IF ( [Entity Budget Status] = "Not budgeted", "#C0392B", "#1F2A37" )', '8 Formatting')
