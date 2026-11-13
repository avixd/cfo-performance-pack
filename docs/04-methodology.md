# Methodology of the hidden analysis pages

Three pages are hidden from report readers and exist to show technique. This document states how each is modelled, what it assumes, and where the method is strong or weak. The same notes appear in short form on pages H2 and H3.

## H1 · Revenue Flow (Sankey)

**Model.** One measure, `SVG Sankey`, returns an SVG image as text (data category *Image URL*) and is shown in an Image visual.
- Flows are taken from existing measures: `Revenue`, `Gross Profit`, `EBITDA`, `Net Income`, and revenue by `Entity[Region]`. Costs are stored negative, so each cost flow is a difference (cost of sales = revenue - gross profit).
- One scale for the whole chart: net revenue is 330 units high and every other band uses the same factor, so widths are comparable.
- Colours come from the theme measures, so the chart follows the Light/Dark toggle.

| | |
|---|---|
| **Assumptions** | Three regions (North America, Europe, Pacific); five levels (regions, net revenue, gross profit, EBITDA, net income). Items below EBITDA are one band. |
| **Strengths** | No custom visual to install, certify or keep updated; works in Publish to web; follows every slicer; fully reviewable as DAX. |
| **Weaknesses** | It is a picture: no tooltips, drill or cross-highlighting. Nodes are fixed in the measure, so a new region needs a code change. Long labels can overlap when a band is very thin. |
| **Considerations** | A Sankey cannot show negative flows; the measure returns a message when revenue or a profit level is negative for the selection. For interactive use, a certified custom Sankey visual is the alternative, at the cost of a dependency. |

## H2 · Income Statement Explorer (after Goodly, "How to create a Dynamic Profit and Loss Statement in Power BI")

**Components replicated.** Title with date range; six KPI cards with PY, change and % change; summary bullets for a selected KPI; CY vs PY monthly line; Thousand/Absolute toggle; statement matrix with expandable heads and the columns CY, CY % Rev, PY, PY % Rev, Δ PY, Δ% PY and Δ % Rev (bps).

**Model.**
- **Rows are data.** `Report Line` holds sections and lines; `Report Line Map` lists the accounts of each line. Measures apply the account list with `TREATAS`. A section header is the union of the distinct accounts of its lines, so no subtotal is hard-coded and nothing is double-counted. Lines flagged `MatrixRow = No` are subtotals that the section header already shows.
- **Periods.** CY = the Period slicer (YTD by default) ending at the selected month; PY = the same months one year earlier.
- **Units.** `Display Unit` is a disconnected table; `Unit Divisor` divides amounts by 1,000 or 1.
- **Focus.** `PL Focus` is a disconnected table that maps six headline names to report lines; the summary and trend read it. Cost of sales is flipped to a positive size for the trend only.
- **Summary bullets** are rules, not text generation: direction (average of the last three months vs the three before, ±2% counts as steady), peak month, year to date vs prior year with the count of months that beat prior year, and volatility (coefficient of variation above 20% is "volatile").

| | |
|---|---|
| **Assumptions** | Costs are negative, so a positive change is favourable on every row. % Rev uses net revenue of the same year. Change % is blank when signs differ or the change exceeds 1,000%. |
| **Strengths** | Adding, renaming or re-ordering a line is a data change. Cards, trend and matrix share one definition. The summary is explainable: each bullet has a stated rule. |
| **Weaknesses** | Prior-year comparison only (budget is on tab 3). Rule-based bullets cannot explain *why*. The matrix needs one click to expand a section. |
| **Considerations** | New entities inflate growth versus prior year; read organic growth on tab 2. Basis points move with revenue mix even when a cost is flat. |
| **Differences from the reference** | Year/Quarter slicers are replaced by the report's Fiscal year, Month and Period filters. Clickable cards are replaced by a Focus slicer, because a card cannot filter other visuals without bookmarks. The reference uses a calendar year; this model uses an April to March fiscal year. |

## H3 · Rolling Forecast (after Goodly, "The Budget vs Actual Dashboard Every CFO Asks For")

**Components replicated.** "Actuals Until" selector; month matrix with actual cells (blue) up to the selected month and budget cells (red tint) after it; total column. Added on top: the target test the page exists for.

**Model.**
- `Actuals Until` is a disconnected table of closed months. `RF Cutoff` is the picked month, or the reporting month when nothing is picked.
- `RF Value` returns, per fiscal month, actual when the month is on or before the cut-off and budget otherwise. Summed over twelve months it is the rolling forecast (`RF Total`).
- Target = full-year budget of the cut-off's fiscal year (`RF Target`). `RF Gap` = forecast - target; `RF Attainment %` = forecast / target.
- `RF Required per Month` = (target - actual to date) / months left. Compare it with `RF Average per Month`.
- Cross-check: `RF Run-Rate Total` assumes the remaining months repeat the year-to-date average instead of the budget.

The three levels in the reference video and how they map here:

| Level | Question | Here |
|---|---|---|
| 1 | Compare actuals to budget | Tab 3 and the target table on this page. |
| 2 | Budget and actuals at different grains | Not needed: both are stored by month, entity, department and account. If a budget arrives yearly or by region, allocate it to months with a seasonality key (for example prior-year share) in Power Query before it reaches the model. |
| 3 | Actuals vs rolling budget | The matrix: actual to the cut-off, budget after it. |

| | |
|---|---|
| **Assumptions** | Remaining months land exactly on budget. The target is the original budget, not a reforecast. Cost metrics are negative, so a positive gap is always "on track". |
| **Strengths** | Simple and auditable; no statistical model to maintain. Replayable: move the selector to see what the forecast said at any month end. Two methods side by side show the range. |
| **Weaknesses** | The year-to-date variance is carried forward but assumed to stop growing. Seasonality exists only in the budget. The run-rate method ignores seasonality entirely. Entities without a budget have no target and show blank. |
| **Considerations** | When forecast and run-rate disagree, the answer usually lies between them. In this data three entities have no or a non-credible budget, so their "on track" status reflects a planning gap; read tab 1's budget status first. A driver-based or statistical forecast is the next step if more accuracy is needed. |
