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
MT = lambda x: 'FORMAT ( ( ' + x + ' ) / 1e6, "+#,0.0;-#,0.0" ) & "M"'      # signed millions text
MU = lambda x: 'FORMAT ( ( ' + x + ' ) / 1e6, "#,0.0" ) & "M"'              # unsigned millions text

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
RETURN COUNTROWS ( FILTER ( top5, [@v] < 0 ) ) & " of the 5 largest variances are unfavourable; together they total " & ''' + MT('SUMX ( top5, [@v] )') + ''' & "."''', SB)
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
    fmt = next(m.get('fmt') for m in MEAS if m['name'] == name)
    if fmt == F:
        return (f'VAR v = [{name}] RETURN IF ( NOT ISBLANK ( v ), IF ( ABS ( v ) >= 1e6, FORMAT ( v / 1e6, "#,0.0;(#,0.0)" ) & "M", '
                f'FORMAT ( v / 1e3, "#,0.0;(#,0.0)" ) & "K" ) )')
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
