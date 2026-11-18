# Reviewing and sharing the project

How to hand this project to a reviewer or collaborator so that they see **exactly** the report we built, securely and at no cost.

## Why a reviewer sees the same output

| What decides the output | Where it lives | Same for every reviewer? |
|---|---|---|
| Model: tables, relationships, 539 measures, row-level security roles | `CFO-Performance-Pack.SemanticModel/` (TMDL text) | Yes, versioned in Git |
| Report: pages, visuals, layout, theme, light/dark | `CFO-Performance-Pack.Report/` (PBIR JSON + theme) | Yes |
| Data | `data/` CSV files, closed at October 2026 | Yes: fixed, fictitious, checked against `data/MANIFEST.sha256` |
| Font | DIN, which ships with Power BI | Yes, nothing to install |
| Number formats, colours, titles | DAX measures in the model | Yes |
| The "Hello, …" greeting and *Refreshed* time stamp | Computed at view time | No: shows the viewer's own name and refresh time |

Nothing in the model or report runs Python or R: every table is loaded by Power Query from the CSV files or calculated in DAX. Python is used only by the optional build and check scripts in `scripts/`.

## Sharing options (secure, cost-free first)

| Option | Reviewer needs | Interactive | Cost | Security | Use it for |
|---|---|---|---|---|---|
| **1. GitHub repository + Power BI Desktop** (recommended) | Free Power BI Desktop on Windows; a GitHub account to comment or contribute | Yes, every slicer and page | Free | Public, read-only for everyone; only invited collaborators can push, and only through reviewed pull requests | Technical review and collaboration |
| **2. ZIP download** | Free Power BI Desktop | Yes | Free | Same files as the repo; no account needed | Reviewers without Git ([05-download-zip-guide.md](05-download-zip-guide.md)) |
| **3. PDF** (`docs/CFO-Performance-Pack.pdf`) | A PDF reader | No (static pages) | Free | Nothing executable | Executives who only need to read |
| 4. Power BI service, workspace or app sharing | Power BI Pro or Premium Per User licence for **both** people (or Fabric capacity) | Yes, in a browser | Recurring licence cost | Strong (Microsoft Entra sign-in, workspace roles, row-level security) | Only if a paid licence is already available |
| ~~Publish to web~~ | Nothing | Yes | Free | **Not secure:** anyone with the link can see the report, and the link can be found and shared | Do not use |

Option 4 is not used here because the project rule is no recurring cost; a free (Fabric free) licence cannot share content with other people. Row-level security only applies in the Power BI service; in Desktop a reviewer can test it with **Modeling → View as**.

## Recommended setup for collaboration on GitHub (free)

1. **Invite collaborators**, not "anyone": repository **Settings → Collaborators → Add people**. Give *Read* or *Triage* to reviewers and *Write* only to people who will open pull requests. Ask every collaborator to turn on two-factor authentication.
2. **Protect `main`**: **Settings → Branches → Add branch ruleset** for `main`: require a pull request with at least one approving review, require the status checks `checks` and `replicate-data` to pass, and block force pushes and deletions.
3. **Work through pull requests**: every change goes on its own branch and is merged after review. CI then runs the privacy check (no user paths, tenant domains or e-mail addresses), the model and report checks, and rebuilds the data from Microsoft's public sample.
4. **Discuss in Issues** (bugs, questions) and **review in pull requests** (line comments on TMDL, PBIR and docs; all are plain text, so diffs are readable).
5. **Never share** tenant credentials, the `.pbi` folders (`cache.abf` holds data, `localSettings.json` local settings), `.pbix` exports, or your local `DataRoot` path. `.gitignore` already excludes the first three, and a test rejects a committed local path.

## Reviewer workflow

1. Clone the repository (or download the ZIP: [05-download-zip-guide.md](05-download-zip-guide.md)) to a short local path such as `C:\PBI\cfo-pack\`.
2. Open `CFO-Performance-Pack.pbip` in Power BI Desktop. Signing in is not needed.
3. **Home → Transform data → Edit parameters**: set `DataRoot` to the full path of the `data` folder, ending with `\`. Click **Refresh**.
4. Review the pages against [03-page-guide.md](03-page-guide.md); open the Notes and Data Dictionary pages for definitions.
5. Optional checks in **DAX query view**: paste `tests/live_checks.dax` and run it; every row must show `Pass = TRUE`.
6. Leave feedback as GitHub Issues or pull-request comments. If you take screenshots, sign out of Desktop first or crop the greeting, because it shows your Windows or sign-in name.

## If the reviewer cannot run Python

Python is never needed to **view** or **review** the report. For the tasks that use Python, these alternatives work without it:

| Task | With Python | Without Python |
|---|---|---|
| Open, refresh and explore the report | Not needed | Power BI Desktop only |
| Get the source data | `scripts/build_data.py` | Use the CSV files already in `data/` (they are the seeded build, byte for byte) |
| Prove the data is the fictitious seeded build | `python -I scripts/verify_data.py` | Read the **replicate-data** job result on GitHub (Actions tab): GitHub's own runner rebuilds the data on every push and compares all 44 files. Or compare file hashes in PowerShell: `Get-FileHash .\data\actuals\GL_Actual_2024-04.csv -Algorithm SHA256` against the matching line in `data/MANIFEST.sha256` (use the GitHub ZIP: a Git clone on Windows usually converts line endings, which changes the hash; `verify_data.py` ignores line endings) |
| Mask a real source before sharing | `scripts/anonymise_data.py` | Use the in-model switch: **Edit parameters → `MaskData` = true**, private **`MaskScale`**, Refresh ([06-ai-safe-workflow.md](06-ai-safe-workflow.md)) |
| Change a measure, visual or page | Edit `scripts/model_def.py` / `scripts/build_pbip.py`, run `scripts/build_pbip.py` | Make the change in Power BI Desktop and save (PBIP writes TMDL/PBIR text), or edit the TMDL in Tabular Editor 2 (free) or VS Code with the TMDL extension. Open a pull request: the CI check "generated files in sync" will flag that the scripts need the same change, and the maintainer ports it before merging |
| Run the model checks | `python tests/test_model.py` | Let CI run them on the pull request |

No table in the model uses a Python or R data source. If a future change needs one, prefer Power Query (M), DAX calculated tables, or pre-computed CSV files in `data/`. Python and R sources do not refresh in the Power BI service without a personal gateway, and many organisations block them.

## Before you share: checklist

- [ ] `main` is the version you mean to share, and the latest CI run on it is green (checks + replicate-data).
- [ ] `DataRoot` in the committed TMDL is the placeholder `<YOUR-LOCAL-PATH>\data\` (CI test enforces it).
- [ ] `MaskData = false` in the committed model (the live checks confirm it), unless you deliberately share masked output.
- [ ] Screenshots and PDF show no personal name (greeting) or tenant account.
- [ ] Collaborators are invited individually; `main` is protected; Publish to web is not used.
