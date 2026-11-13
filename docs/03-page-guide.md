# Page guide (one section per tab)

Tab numbers match the report. Tabs 1 to 8 are visible; H1 to H3 are hidden analysis pages (visible in Power BI Desktop, hidden from report readers).
Each section is written so it can be read out as a walkthrough: what the page is for, what is on it, and what to click.

Every page shares one frame: sidebar (numbered page navigation, filters, Reset all filters), header (dynamic title, one-line summary, current-filter chips, greeting, Report an issue / Request support, Light/Dark toggle, refresh stamp) and a footer with numbered notes. Filters in the sidebar apply to every page.

| Tab | Name | Question it answers |
|---|---|---|
| 1 | Overview | Who is the group and what changed this year? |
| 2 | Executive | Are we on plan, and is the headline as good as it looks? |
| 3 | Budget vs Actual | Where are the variances and where will the year land? |
| 4 | P&L | How did each line perform? |
| 5 | Balance Sheet | Is growth turning into cash? |
| 6 | Data Quality | Can the numbers be trusted? |
| 7 | Data Dictionary | What is in the model and how is it calculated? |
| 8 | Notes | What do the numbers assume? |
| H1 | Revenue Flow (Sankey) | Where does each dollar of revenue go? |
| H2 | Income Statement Explorer | How does this year compare with last year, line by line? |
| H3 | Rolling Forecast | Will we reach the target? |

---

## 1 · Overview
**Purpose.** Context before numbers: the company, its history, and the four questions the pack answers.
**On the page.** Story table (who we are, FY2025 to FY2027, the four questions, disclosure); four KPI cards (net revenue, organic growth, new-entity revenue, entities reporting); revenue by fiscal year and region; group perimeter table with ownership and budget status; "What the numbers say".
**How to read it.** Start with the perimeter table: entities marked *Not budgeted* or *Under-budgeted* explain why a revenue beat can be a planning gap.
**Walkthrough.** 1) Read the four questions. 2) Point at the regional mix shift in the stacked columns. 3) Show the amber and red budget statuses. 4) Use the sidebar to move to tab 2.
**Key measures.** `Revenue`, `Organic Growth %`, `Revenue New Entities`, `Entity Budget Status`.

## 2 · Executive
**Purpose.** One page for the board: on plan or not, and why.
**On the page.** Headline sentence written by DAX; six KPI cards (value, comparison to budget and prior year, sparkline, pacing bar with year-elapsed tick); revenue growth bridge (organic vs new entities); EBITDA variance bridge by driver; narrative insights (growth quality, cost absorption, currency effect); top five variances; revenue variance by entity.
**How to read it.** Green is favourable, red unfavourable. A pacing bar past its tick is ahead of a straight-line year.
**Walkthrough.** 1) Read the headline. 2) Revenue is +22% to budget but EBITDA only +7%: open the EBITDA bridge. 3) Read "Currency effect": the beat is trading, not exchange rates. 4) Switch Currency to USD and Period to MTD to show every title and sentence rewriting itself. 5) Toggle Dark.
**Key measures.** `Headline`, `Revenue Var % vs Budget`, `Insight Cost Absorption`, `Insight Currency`, `SVG Spark ...`, `SVG Bar ...`.

## 3 · Budget vs Actual
**Purpose.** Locate the variance and project the year.
**On the page.** Metric selector (Revenue, Gross Profit, Operating Expenses, EBITDA, Net Income); four cards (actual, budget, prior year, full-year outlook); monthly actual / outlook / budget / prior year; cumulative outlook vs budget; variance by entity; operating-expense variance by department.
**How to read it.** Outlook = actual to the close + budget for the remaining months. The subtitle also gives the run-rate landing.
**Walkthrough.** 1) Pick EBITDA in the selector and watch every visual change. 2) Read the entity chart subtitle: entities without a credible budget are named. 3) Show the department overrun.
**Key measures.** `Metric Actual`, `Metric Outlook FY`, `Metric Outlook Run-Rate`, `Sub Entity Variance`.

## 4 · P&L
**Purpose.** Line-by-line management P&L.
**On the page.** Statement table (actual, budget, variance, variance %, prior year, growth, % of revenue, full-year outlook and budget); five tiles (gross margin, EBITDA margin, opex ratio, salary cost per head, net income attributable to the group); insights on cost absorption and people cost.
**How to read it.** Costs are negative, so a positive variance is favourable on every row. Subtotals are shaded.
**Walkthrough.** 1) Largest favourable and unfavourable lines are named in the subtitle. 2) Salaries drive the opex overrun: read the people-cost insight. 3) Point at the minority-interest share on the last tile.
**Key measures.** `Line Actual`, `Line Var vs Budget`, `Salary Cost per Head`, `Net Income Attributable to Group`.

## 5 · Balance Sheet
**Purpose.** Liquidity, working capital and where the cash went.
**On the page.** Balance sheet at the close vs the March year end; eight tiles with change since year end (cash, current ratio, debt to equity, cash cycle, receivable, inventory and payable days, balance check); cash bridge; cash and trade working capital by month.
**How to read it.** In the cash bridge, green is a source of cash and red a use; the steps add up exactly to the change in cash.
**Walkthrough.** 1) Cash is down while profit is up. 2) The bridge shows receivables as the largest use. 3) Receivable days confirm it.
**Key measures.** `Cash Bridge Value`, `DSO (days)`, `Current Ratio`, `Balance Check Text`.

## 6 · Data Quality
**Purpose.** Evidence that the numbers can be trusted.
**On the page.** Eight tiles (files, duplicates removed, blank departments fixed, schema drift, and three integrity checks with pass/fail); injected vs detected issues; per-file profile; findings from the independent analysis.
**Walkthrough.** 1) Every injected issue is detected: 30/30, 30/30, 1/1. 2) The three checks pass. 3) 76% of budget rows are synthetic, stated openly.
**Key measures.** `DQ Duplicates Removed`, `DQ Balance Sheet Difference`, `DQ Synthetic Budget Share`.

## 7 · Data Dictionary
**Purpose.** Explore the model without downloading it.
**On the page.** Counts of tables, columns, measures and relationships; five slicers (object type tiles, searchable Table, Folder and Name dropdowns, and a free-text "contains" search); one table with type, table, name, description, expression and folder.
**How it works.** The calculated table `Data Dictionary` unions `INFO.VIEW.TABLES`, `COLUMNS`, `MEASURES` and `RELATIONSHIPS`, so it is rebuilt from the model on every refresh and cannot drift.
**Walkthrough.** 1) Click *Measure*. 2) Type "cash" in the name search. 3) Read the description and the DAX of `Cash Bridge Value`. 4) Click *Relationship* to see the star schema as rows.
**Key measures.** `DD Objects`, `DD Documented %`.

## 8 · Notes
**Purpose.** Assumptions, policies and definitions in one place.
**On the page.** Fifteen assumptions and policies (calendar, sign convention, colour, number format, currency, budget, outlook, ownership, known gaps) and thirteen metric definitions.
**Walkthrough.** Use it as the reference when a viewer asks "how is that calculated?".

## H1 · Revenue Flow (Sankey) (hidden)
**Purpose.** One picture of the income statement: revenue by region flows into net revenue, which splits into cost of sales, operating expenses, items below EBITDA and net income.
**How it is built.** Power BI has no built-in Sankey. The chart is one DAX measure (`SVG Sankey`) that returns an SVG image; band width is proportional to the amount. No custom visual has to be installed or trusted.
**Trade-offs.** It follows every slicer and the Light/Dark toggle, but it is an image: no tooltips or cross-highlighting, and the node list is fixed in the measure. A Sankey cannot draw negative flows, so the measure shows a message when a profit level is negative.
**Walkthrough.** 1) Read the subtitle: of every $100 of revenue, how much reaches net income. 2) Filter to one region and watch the bands resize.

## H2 · Income Statement Explorer (hidden)
**Purpose.** Current year against prior year, by section and line. Same components as the Goodly dynamic P&L page, in this report's look.
**On the page.** Six cards (Revenue, COGS, Gross Profit, EBITDA, EBIT, Net Profit) each with prior year, change and % change; Focus selector; rule-based summary for the focus line; current vs prior year trend; Thousand/Absolute toggle; expandable matrix (CY, CY % Rev, PY, PY % Rev, Δ PY, Δ% PY, Δ % Rev in bps); method notes.
**Differences from the reference.** Year and Quarter slicers are the sidebar's Fiscal year, Month and Period; the reference's clickable cards are a Focus slicer here. See [04-methodology.md](04-methodology.md).
**Walkthrough.** 1) Pick EBITDA in Focus. 2) Read the four summary bullets. 3) Expand Operating Expenses in the matrix. 4) Switch to Absolute.

## H3 · Rolling Forecast (hidden)
**Purpose.** Will we reach the target? Same components as the Goodly Budget vs Actual page: an "Actuals Until" selector and a month matrix showing actuals up to that month and budget after it.
**On the page.** Actuals Until and Metric selectors; four cards (rolling forecast, target, required per remaining month, run-rate projection); entity by month matrix (blue = actual, red tint = budget, Total = rolling forecast); target table per entity (gap, attainment, required vs average per month, status); method notes.
**Walkthrough.** 1) Move Actuals Until back to June and watch blue months turn red. 2) Compare "required per month" with "average so far". 3) Sort the table by gap to find entities that will miss.
**Method and limits.** See [04-methodology.md](04-methodology.md).
