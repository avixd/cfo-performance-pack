# Using the project from a GitHub ZIP download

This guide is for someone who downloads the repository as a ZIP (no Git, no Python) and wants to open, refresh and explore the report in Power BI Desktop. It takes about 10 minutes.

## What you need

| Requirement | Notes |
|---|---|
| Windows 10/11 with **Power BI Desktop** (current release, free) | From the Microsoft Store or microsoft.com/power-bi. The report uses the new card visual and the PBIR report format, so older Desktop builds may not open it. |
| About 50 MB of free disk space | The project itself is small; Desktop adds a local data cache after the first refresh. |
| No Power BI account or licence | Everything runs locally. Signing in to Desktop is optional (see *Sharing safely* below). |

All company data in the project is **fictitious** (Microsoft's AdventureWorksDW sample plus seeded synthetic budgets); [06-ai-safe-workflow.md](06-ai-safe-workflow.md) shows how to verify that.

Python is **not** needed to use the report. It is only needed to regenerate the model or the data (see the end of this guide).

## 1. Download the right branch

The latest report lives on the branch **`feature/standard-layout-theme`** until it is merged into `main` (`main` currently holds the first verified version).

1. Open the repository on GitHub, click the branch selector (it shows `main`) and choose `feature/standard-layout-theme`.
2. Click **Code → Download ZIP**.

Direct link to the same file: `https://github.com/avixd/cfo-performance-pack/archive/refs/heads/feature/standard-layout-theme.zip`

## 2. Unblock and extract to a short local path

1. Right-click the ZIP → **Properties** → tick **Unblock** (if shown) → OK. Files extracted from a blocked ZIP keep the "downloaded from the internet" mark, which can trigger security warnings in Desktop.
2. Extract to a **short folder on a local drive**, for example `C:\PBI\`. Avoid `Downloads` and avoid OneDrive or other synced folders:
   - **Path length:** the deepest file in the project is 106 characters long and the ZIP adds a 51-character top folder. Windows' default extract path (`C:\Users\<you>\Downloads\<zip name>\<zip name>\…`) gets close to the 260-character Windows limit, and Desktop fails with "path too long" or missing-file errors when it is crossed.
   - **Sync clients** (OneDrive, Dropbox) can lock files while Desktop writes them.
3. Optional: rename the extracted folder to something short, e.g. `C:\PBI\cfo-pack\`.

You should now have:

```
C:\PBI\cfo-pack\
  CFO-Performance-Pack.pbip          <- open this
  CFO-Performance-Pack.SemanticModel\
  CFO-Performance-Pack.Report\
  data\                              <- the CSV source files
  docs\  scripts\  tests\  README.md  LICENSE
```

## 3. Open the report

1. Double-click **`CFO-Performance-Pack.pbip`** (or File → Open in Desktop and pick it). Always open the `.pbip` file, never a file inside the two sub-folders.
2. If Desktop says it cannot open the project: **File → Options and settings → Options → Preview features**, tick **Power BI Project (.pbip) save option** and **Store reports using enhanced metadata format (PBIR)**, restart Desktop and open it again. (In recent releases both are on by default.)
3. The first open shows empty visuals and a refresh error. That is expected: the model does not yet know where your `data` folder is.

## 4. Point the model at your data folder

1. **Home → Transform data (arrow) → Edit parameters**.
2. Set **DataRoot** to the full path of the `data` folder **ending with a backslash**, e.g. `C:\PBI\cfo-pack\data\`.
3. Click OK, then **Apply changes** if prompted, then **Home → Refresh**.

The first refresh can take a few minutes. All queries read through a single folder source, so there are no privacy-level prompts and no gateway is needed.

## 5. Explore

| Page | What to try |
|---|---|
| 1 Overview to 8 Notes | Use the left-hand slicers: Fiscal year, Month, Period (YTD/QTD/MTD), Currency (CAD/USD), Region, Entity. Titles, headlines and KPI cards rewrite themselves. |
| KPI cards | Each card shows the value, the comparison (vs budget or prior year, green = favourable) and, on headline cards, the target and % of target with a sparkline and attainment bar. |
| Sun / moon toggle (top right) | Switches the whole report between light and dark themes. |
| Charts and tables | Click a bar, entity or month to cross-filter the rest of the page; click again to clear. |
| H1 to H3 | Revenue flow (Sankey), income statement explorer and rolling forecast. They are hidden from the left-hand navigation; open them from the page tabs at the bottom of Desktop. |
| Row-level security | **Modeling → View as →** `Europe`, `North America` or `Pacific` to see the report as a regional user would. `Group` sees everything. |

### Live demo: close the next month

The pack is "closed" at October 2026. Move `data\inbox\GL_Actual_2026-11.csv` into `data\actuals\` and click Refresh: the as-of month, titles, YTD figures and outlook all move to November with no model change. Put it back to return to October.

## Sharing safely

When you save, Desktop writes your local data path into `CFO-Performance-Pack.SemanticModel\definition\expressions.tmdl` (the DataRoot parameter) and creates a `.pbi` folder with local settings and a data cache. Before you share or publish your copy:

- Set **DataRoot** back to the placeholder `<YOUR-LOCAL-PATH>\data\` (or edit that line in `expressions.tmdl`) so your user name and folder structure are not shared.
- Do not share the `.pbi` folders (`localSettings.json`, `cache.abf`); the repo's `.gitignore` already excludes them.
- The greeting at the top of each page ("Hello, …") is built from the signed-in user of whoever opens the report. **Sign out of Power BI Desktop** (top-right account menu) before taking screenshots or exporting a PDF you intend to share.
- To show or share figures from a different (real) source, turn on privacy mode first: **Edit parameters → MaskData = true** and a private **MaskScale**, then Refresh. Names become pseudonyms, amounts are scaled and every page footer says so. See [06-ai-safe-workflow.md](06-ai-safe-workflow.md).
- If you use Git, run `bash scripts/privacy_check.sh` before committing; it blocks real Windows user paths, OneDrive folder paths, tenant domains and e-mail addresses.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "The path is too long" or files reported missing | Extract to a shorter path (step 2). |
| Refresh error mentioning `DataRoot` or "folder not found" | DataRoot must be the full path to `data\` and **end with a backslash**. |
| Visuals show "Couldn't load the data" after opening | Run Home → Refresh once DataRoot is set. |
| A yellow bar "This project's files were changed externally" | Shown when the files change while Desktop is open (e.g. after regenerating with Python). Click **Apply external changes**. |
| Desktop warns about content from the internet | Close Desktop, unblock the ZIP (step 2) and extract again. |
| Cards or slicers look unformatted | Update Power BI Desktop to the current release. |

## Optional: regenerate from Python

Only needed if you want to change measures, pages or the data. Requires Python 3.10+ with `pandas`, `numpy`, `scipy` and `matplotlib`.

```bash
python scripts/build_pbip.py .            # rewrite the TMDL model and PBIR report from scripts/model_def.py
python scripts/document_model.py .        # rewrite docs/01-semantic-model.md
python tests/test_model.py                # model and report consistency checks
```

Then click **Apply external changes** in Desktop. `scripts/build_data.py` rebuilds the `data` folder from the public AdventureWorksDW CSVs (see the README).
