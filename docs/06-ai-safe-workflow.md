# AI-safe Power BI: work with an AI assistant without exposing real data

This project was built with an AI coding assistant (Claude) driving Power BI Desktop. That is only acceptable if the assistant never sees data it should not see. This page shows how the project applies the four-step method from Fernan's video **[Use Claude Code on Power BI Without Exposing Client Data](https://www.youtube.com/watch?v=t9qOBDrlSZM)** (Fernan | Power BI), and how to reuse it when you point the model at a real source.

| Video step | What it means | How this project does it |
|---|---|---|
| 1. Anonymise your data | Strip or replace anything identifying before an AI or a shared file sees it | `scripts/anonymise_data.py` writes a masked copy of any source folder, with a validation report; the in-model **MaskData** switch masks on load |
| 2. Generate fake data | Work on realistic but fictitious data with the same structure | `scripts/build_data.py`: seeded, deterministic build from Microsoft's public AdventureWorksDW sample; checked byte for byte on every push |
| 3. Swap to sample data | Point the model at the sample (or masked) source, and back to the real one, without touching the model | One parameter, **DataRoot**, holds the folder; every query reads through it |
| 4. Get the real schema | Give the AI the structure (tables, columns, measures), not the rows | The PBIP files (TMDL + PBIR) hold only schema, logic and layout; data caches and local settings are git-ignored |

The steps below map to the video's chapters. The method is credited to the video; the scripts, parameters and checks are this project's own.

---

## The data in this repository is fictitious

**Every company figure in this repository and in the report is fictitious.** None of it comes from a real company, a client or the author's employer.

| Source | What it is | Evidence |
|---|---|---|
| Ledger, chart of accounts, entities, departments | Microsoft's **AdventureWorksDW** sample, a fictional bicycle company (MIT licence), re-dated to April 2024 to March 2027 | Rebuilt from the public download by `scripts/build_data.py` |
| FY2026 to FY2028 budgets | **Synthetic**: prior-year actual x growth x seeded noise, tagged `BudgetSource = Synthetic` | Same seeded build (seed `20261111`) |
| Data-quality issues (duplicates, blank departments, schema drift, new account) | **Injected on purpose**, seeded and logged in `data/dq_injection_log.csv` | Same seeded build |
| Exchange rates (`data/fx/FX_Rates.csv`) | **Real public data**: Bank of Canada Valet API monthly averages and month-end rates (CAD per unit). Not company data | A 33-value sample was checked against the Bank of Canada on 2026-11-12 |
| Narrative (company story, Notes page) | Written for this portfolio piece | `scripts/model_def.py` |

### Validate it yourself

`data/MANIFEST.sha256` holds a SHA-256 hash of each of the 44 generated files. Rebuilding from the public sample reproduces every file byte for byte:

```bash
# 1. Download Microsoft's public sample (about 16 MB) and unzip it into a folder, e.g. aw/
#    https://github.com/microsoft/sql-server-samples/releases/download/adventureworks/AdventureWorksDW-data-warehouse-install-script.zip
# 2. Rebuild the data with the fixed seed
python -I scripts/build_data.py aw rebuilt
# 3. Compare the rebuild, then the committed data, with the manifest
python -I scripts/verify_data.py rebuilt   # "44 generated files match the seeded build byte for byte"
python -I scripts/verify_data.py           # the same check on data/ itself
```

The **replicate-data** job in `.github/workflows/checks.yml` runs exactly these steps on every push, so the claim is checked automatically and publicly. On Windows, use `py` instead of `python`. Line endings are normalised, so a Windows checkout gives the same result.

To check the exchange rates, compare any row with the Bank of Canada series, e.g. `https://www.bankofcanada.ca/valet/observations/FXUSDCAD/csv` (daily rates; the file holds monthly averages and month-end values).

> **Note:** the live demo (moving `inbox/GL_Actual_2026-11.csv` into `actuals/`) changes `data/`, so `verify_data.py` will then report the moved file until you put it back.

---

## Step 1: Anonymise your data (`scripts/anonymise_data.py`)

Use this before a real export reaches Power BI, a shared file or an AI assistant. It reads any folder in this project's layout (`reference/`, `actuals/`, `budget/`, `fx/`, `inbox/`) and writes a masked copy:

```bash
python -I scripts/anonymise_data.py <real_source_dir> <masked_dir> --seed 42
# options: --scale 0.73 (choose the factor), --mask-regions, --mask-accounts
```

| Masked | How | Why it stays useful |
|---|---|---|
| Group and operating-entity names | `Group`, `Entity 03`, … (keyed, stable) | Hierarchy and keys are unchanged |
| Region names (optional `--mask-regions`) | `Region 01`, … | Kept by default because the sample RLS roles and region logic use them |
| Department names | `Department 05`, … | Cost-centre analysis still works by key |
| Account names (optional `--mask-accounts`) | `Account 4100` | Report lines map by key, so the P&L layout is intact |
| Every ledger amount | x one private scale factor | Every ratio, %, margin, variance %, growth % and day-count (DSO, DIO, DPO) is unchanged |
| Data-quality log free text | `masked` | Counts and months kept |

The scale factor is never written to the output. Without `--scale` or `--seed`, a random factor is printed once to the console only.

**Validation is built in** (non-zero exit on failure; report in `<masked_dir>/MASKING_REPORT.md`): same files and row counts, unchanged keys, every amount exactly `source x scale`, and no masked source name anywhere in the output. Run on this repository's data, it checks 45 files, 65,044 rows and 64,734 amounts:

```
| Same files and row counts | pass |
| Keys unchanged (relationships intact) | pass |
| Every amount = source x one private scale (ratios, % and trends preserved) | pass |
| No masked source name appears in the output (17 names checked) | pass |
```

## Step 2: Generate fake data (`scripts/build_data.py`)

The sample data is fictitious, seeded and reproducible (see above). It deliberately carries real-world problems (duplicate re-exports, blank departments after an ERP migration, reordered columns, a new account mid-year), so the cleaning logic and the Data Quality page are tested against realistic mess rather than a perfect sample. The AI assistant built and tested the whole model against this data.

## Step 3: Swap to sample data, and back (`DataRoot`, `MaskData`, `MaskScale`)

Three Power Query parameters control the source (**Home → Transform data → Edit parameters**):

| Parameter | Default | Purpose |
|---|---|---|
| `DataRoot` | `<YOUR-LOCAL-PATH>\data\` | Folder the model reads. Point it at `…\data\` (fictitious sample), `…\masked\` (output of step 1) or a real export in the same layout |
| `MaskData` | `false` | `true` masks while loading: group and entity names become pseudonyms, departments become `Department NN`, every amount x `MaskScale` |
| `MaskScale` | `1` | Amount multiplier used when `MaskData = true` (for example `0.73`); keep the value private |

A typical sequence:

1. **Build and test on the sample:** `DataRoot = …\data\`, `MaskData = false`.
2. **Try a real source safely:** run step 1 into `…\masked\` and point `DataRoot` there, or point `DataRoot` at the real export and set `MaskData = true` with a private `MaskScale`. Refresh. The footer of every page then reads *"MASKED DATA: entity and department names are pseudonyms; amounts are scaled…"* and the brand line says *Masked group*, so nobody mistakes a masked screenshot for real figures.
3. **Go live:** set `MaskData = false`, point `DataRoot` at the real source, refresh, and stop sharing screenshots or AI sessions from that file.

**Tested end to end (17 Nov 2026, live model):**

| Test | Revenue (CAD) | Gross margin | Revenue vs budget | Names |
|---|---|---|---|---|
| Sample data, `MaskData = false` | 36,185,471 | 69.32% | +22.2% | Sample names |
| Sample data, `MaskData = true`, `MaskScale = 0.5` | 18,092,735 | 69.32% | +22.2% | `Group`, `Entity NN`, `Department NN`; footer notice on |
| `DataRoot` swapped to a step-1 masked copy (seed 3, scale 0.738) | 26,703,597 | 69.32% | +22.2% | `Entity NN`, `Department NN` |
| `DataRoot` and `MaskData` back to defaults | 36,185,471 | 69.32% | +22.2% | Sample names |

Masking happens inside Power Query, before rows reach the model. An assistant that queries the model (for example through the Power BI Modeling MCP server) then only ever receives masked names and scaled amounts. Power Query itself still reads the real files on your machine, so for the strictest setting use step 1 and never give the real folder to the AI at all.

## Step 4: Give the AI the real schema, not the rows

The project is saved as a **Power BI Project (PBIP)**, a folder of text files:

| Shareable (schema, logic, layout) | Never share (data or personal) |
|---|---|
| `*.SemanticModel/definition/` TMDL: tables, columns, relationships, 539 measures, Power Query, roles | `**/.pbi/cache.abf`: the imported data rows |
| `*.Report/definition/` PBIR: pages, visuals, theme | `**/.pbi/localSettings.json`: local settings |
| `scripts/`, `tests/`, `docs/` | Your real `DataRoot` path (it names your user folder) |
| | Screenshots or PDFs showing the "Hello, …" greeting (it shows the sign-in name, or the Windows user name when signed out) |

`.gitignore` excludes the cache and local settings. `scripts/privacy_check.sh` (also run in CI) blocks real Windows user paths, OneDrive folder paths, tenant domains and personal e-mail addresses. `scripts/build_pbip.py` always writes the `DataRoot` placeholder unless a local path is already in place, and the copy on GitHub is generated with the placeholder.

So an assistant can read and change every measure, query and visual from the TMDL/PBIR text without receiving a single data row. This is how this project was built: the assistant edited `scripts/model_def.py` and `scripts/build_pbip.py`, and only ever saw the fictitious sample.

---

## Sharing checklist

- [ ] Data is the fictitious sample, a masked copy (step 1), or `MaskData = true` with a private `MaskScale`
- [ ] `DataRoot` set back to `<YOUR-LOCAL-PATH>\data\` before committing or zipping
- [ ] No `.pbi` folders, `.pbix` files or exports in what you share
- [ ] Greeting cropped out of screenshots, or `Greeting` temporarily set to `"Hello"` for PDF exports (signing out is not enough: it falls back to the Windows user name)
- [ ] `bash scripts/privacy_check.sh` and `python tests/test_model.py` pass

## Limits: pseudonymisation, not anonymity

- Masking hides names and absolute size. Anyone who knows the company well could still recognise it from the shape of its hierarchy, its currency mix or its growth pattern. For regulated or client data, follow your organisation's data-handling policy; this is not a legal anonymisation standard.
- Anyone who knows `MaskScale` can convert scaled amounts back. Choose a new value per sharing and keep it private.
- Static narrative (Overview and Notes text, the sample RLS role names) describes the fictitious company. Replace it before using a real source.
- Account names are kept by default because they are usually generic (Revenue, Salaries). Use `--mask-accounts` if your chart of accounts names clients or projects.
- Desktop shows the previously loaded data until you refresh after changing a parameter.
