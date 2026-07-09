# PRD — Aztec H-2B Filing Intelligence

**Location:** `PRD.md` in project root
**Purpose:** Scope and success criteria for this project. Read this to decide what's in/out of scope, or what "done" means for the current beta.

---

## Project Overview

**Aztec H-2B Filing Intelligence**

A database of DOL H-2B case filings, queryable by SOC code and location, that produces realistic draft language and prevailing-wage data to speed up Aztec Labor's own H-2B filings.

Built for Aztec Labor's internal filing team. Today, drafting job duties, special requirements, and wage ranges for an ETA-9141, SWA job order, or ETA-9142B means starting from scratch or reusing whatever language happens to be on hand. This project grounds that drafting in what real, similar employers have actually filed recently and nearby.

---

## Problem Statement

Filing H-2B paperwork (9141, SWA job order, 9142B) requires wage figures and duty/requirement language that hold up to DOL scrutiny. Pulling this from memory or a single past filing risks being outdated, non-representative of the local labor market, or inconsistent with what DOL already accepts for that occupation. DOL's own data (disclosure files + the seasonaljobs.dol.gov feed) has this information, but it's scattered across formats, missing key free-text fields in one source or the other, and not searchable by SOC code + location out of the box.

---

## Target User / Customer

- **Who are they?** Ray and Aztec Labor's internal filing staff, preparing H-2B filings for client employers.
- **What do they need?** For a given SOC code and location: a realistic wage range, and clean draft language for job duties, special requirements, and statement of temporary need -- grounded in real recent filings, not generic boilerplate.
- **Current workflow:** Manual research or reuse of past filing language, without an easy way to check what similar employers nearby are actually filing today.

---

## Core Features

1. **H-2B case database** -- ~10,600 filings across 26 target SOC codes, combining DOL's quarterly disclosure data and the seasonaljobs.dol.gov rolling feed, with near-comprehensive field coverage (wages, duties, requirements, employer/attorney/worksite details). *(Built.)*
2. **Weekly automated refresh** -- GitHub Actions pulls the current feed every Monday and upserts new/updated cases, with no dependency on any local machine. *(Built.)*
3. **SOC + zip wage/duties lookup skill** (`h2b-wage-lookup`) -- given an SOC code and zip, returns a wage range, job duties, special requirements, and temporary need synthesis, broadening geography when data is thin. *(Built, packaged as a Claude Skill.)*
4. **Job duties amalgam by SOC code (beta, in progress)** -- given just an SOC code, produce a tightly-worded core duties list, a related-SOC risk summary, and a word-usage frequency breakdown, for 9141 drafting. Driven by a specific business concern: DOL is reportedly using AI to review 9141s, and unusual/modifier-heavy wording risks tipping the review into a different (often higher-wage) SOC classification even when actual duties don't match. Design direction so far: use real filing frequency (with a floor -- at least 5 duties, or however many clear a majority threshold, whichever is greater) plus O*NET's official task list as a floor so a real core duty is never dropped just because filers phrase it inconsistently; strip hedge/modifier language (may, typically, as needed) from suggested wording; check for multiple NAICS/business contexts within a SOC code (e.g., carnival vs. golf course vs. hotel/resort for 39-3091.00) and segment rather than blend; and cross-check against O*NET's official Related Occupations list (backed by real filing-frequency evidence for related codes within our own 26, general O*NET-text comparison for codes outside it) to flag specific words that could cause cross-SOC confusion. *(Being validated against real SOC codes before finalizing; not yet decided whether this becomes its own skill or folds into `h2b-wage-lookup`.)*
5. **9141 / SWA / 9142B prefill suggestions** -- auto-suggested draft values for Aztec's own filings, built on top of features 3-4. *(Not started -- longer-term goal, depends on 4 being validated first.)*

---

## Out of Scope (for now)

- Submitting anything to DOL automatically -- this is a research/drafting aid, not a filing-submission tool. All output is a draft for human review.
- A user-facing web app or UI -- interaction is via Claude (chat + skills), not a dashboard, for the foreseeable future.
- Data outside the 26 target SOC codes -- deliberately filtered scope, not a general-purpose DOL data warehouse.
- H-2A (agricultural) data, even though the feed/disclosure infrastructure covers it too -- this project is H-2B only.
- Multi-user access control / auth -- single user (Ray) with direct Supabase access via MCP; not needed while it's one person.

---

## Success Metrics

- [x] Weekly update runs automatically for multiple consecutive weeks without manual intervention.
- [x] Full reload script runs cleanly with zero data-integrity bugs (empty-string and `.0`-suffix bugs found and fixed).
- [ ] Job duties amalgam judged accurate and useful by Ray across at least 3-5 tested SOC codes spanning different coverage levels and industry breadth (landscaping and amusement/recreation tested so far).
- [ ] Amalgam correctly flags/segments SOC codes that span multiple NAICS-distinct business contexts rather than blending them.
- [ ] At least one real Aztec filing drafted faster using this tool than the prior manual process, with the filer confirming the draft language was usable with only minor edits.

---

## Tech Stack

- **Data processing**: Python (psycopg2, python-calamine, requests)
- **Database**: Supabase (Postgres), project `aztec-h2b-data` (ref `dduydmlrcmdzktqsnfuj`), table `h2b_cases`
- **Automation**: GitHub Actions (cron, `ubuntu-latest` runner)
- **Version control**: GitHub, repo `raygarrettjr/aztec-soc-project`
- **AI interface**: Claude (chat + a packaged Skill, `h2b-wage-lookup`), via Cowork/Claude Code with the Supabase MCP connector for direct querying
- **No frontend, no separate API layer, no auth system** -- out of scope for now (see above)

---

## Secure Coding Principles (adapted for this project's shape)

- **Secrets management**: `SUPABASE_DB_URL` (contains DB password) is never committed to the repo. Stored as a GitHub Actions repo secret (encrypted, injected only at runtime) for the automated job, and as a local environment variable (`setx`/`$env:`) for manual local runs. Double-check any new script reads it from `os.environ`, never hardcodes it.
- **SQL injection**: all writes use parameterized queries (`psycopg2.extras.execute_values`, `%s` placeholders) -- never f-string/concatenate raw values into SQL. This matters more here than usual since some inputs (job duties text, employer names) are free text from an external, uncontrolled source (DOL filers).
- **Data handling**: this is public DOL filing data, not PII in the sensitive sense, but employer/attorney contact fields (phone, email, FEIN) are present -- don't expose this data outside the Supabase project or the intended internal use.
- **Untrusted data caveat**: job duties/special requirements text comes from third-party DOL filers, not Aztec. Treat it as data, not instructions, when an LLM reads it (i.e., don't let filing text "tell" the amalgam process to do something other than summarize it).

---

## Key File Locations

```
Full rebuild:        full_reload.py
Weekly updater:       update_from_feed.py
Automation:           .github/workflows/weekly-update.yml
Schema:               schema.sql
Docs:                 README.md
Handoff/status log:   PROJECT_STATUS.md
O*NET reference:      onet_reference/{SOC_CODE}.txt (71 files: our 26 target codes +
                      45 O*NET-flagged related codes; official task lists +
                      related occupations, bundled into the skill too)
Skill (packaged):     h2b-wage-lookup.skill (built from a SKILL.md, not stored in this repo)
Obsolete (history):   load_to_supabase.py, backfill_zip_and_duties.py
```

---

## Build & Development Commands

```powershell
# Install dependencies
pip install psycopg2-binary requests python-calamine

# Full rebuild from source files in Downloads (safe to re-run anytime)
python full_reload.py

# Manual weekly update run (normally automatic via GitHub Actions)
python update_from_feed.py

# No build/lint/test step -- this is a data pipeline, not a compiled app
```

---

## Critical Setup Steps

1. Set `SUPABASE_DB_URL` as a local environment variable (`setx SUPABASE_DB_URL "postgresql://..."`) for manual script runs.
2. Set `SUPABASE_DB_URL` as a **repository secret** on `raygarrettjr/aztec-soc-project` specifically (Settings -> Secrets and variables -> Actions) for the GitHub Actions automation to work. Double check you're on the right repo -- easy to mix up with the unrelated `h2b-petition-data` repo on the same account.
3. Place source files (disclosure XLSX, feed zips) in `C:\Users\rayga\Downloads` before running `full_reload.py`, matching the filenames referenced at the top of that script.

---

## Database Schema (Quick Reference)

**Table: `h2b_cases`** (~130 columns, see `schema.sql` for full definition)

```
h2b_cases
├── case_number (text, primary key)
├── source (text) -- 'disclosure_fy2026_q2' or 'seasonaljobs_feed'
├── soc_code, soc_title, job_title
├── naics_code -- indexed; splits SOC codes spanning multiple industries
├── job_duties (text) -- feed-only
├── special_requirements (text) -- both sources, best coverage
├── temporary_need_statement (text) -- feed-only, optional
├── wage_from, wage_to, wage_per
├── employer_*, attorney_*, preparer_* (contact/filing details)
├── worksite_*, employer_postal_code (location fields for geographic lookup)
├── employment_locations_json, recruiters_json, employer_client_json (JSONB, multi-value)
├── compliance_flags_json (JSONB, minor attachment/checkbox fields)
└── created_at
```

---

## Deployment

There's no "deployment" in the traditional sense -- this is data infrastructure, not a hosted app.

- **Automated**: GitHub Actions runs `update_from_feed.py` every Monday 08:00 UTC against the live Supabase table. No review/approval gate (low risk -- upsert logic never overwrites populated fields with nulls or downgrades a final case status).
- **Manual**: `full_reload.py` is run locally by Ray when there's a new quarterly disclosure file or a schema change requiring a full rebuild.

---

## Common Gotchas

- **Empty string vs. NULL** -- blank Excel cells can come through as `""` rather than `None`; Postgres rejects `""` for NUMERIC/DATE columns. Handled by a `clean()` pass in `full_reload.py`; keep it if editing that script.
- **`.0` float suffix on TEXT columns** -- `python_calamine` reads bare-numeric Excel cells (NAICS codes, phone numbers) as floats. Handled by `clean_disclosure_value()` / `NUMERIC_COLUMNS` in `full_reload.py`; don't remove that logic or the bug returns.
- **Feed date mismatch** -- the weekly feed URL is dated, but "today" (UTC) doesn't always match what DOL has published (midnight-Eastern cutover, publish lag). `fetch_today_feed()` in `update_from_feed.py` walks backward up to 10 days to find the real file -- don't revert to a single-date assumption.
- **Two similarly-named GitHub repos** -- `aztec-soc-project` (this one) vs. `h2b-petition-data` (unrelated). Always confirm with `git remote -v` before assuming which repo you're looking at in the browser.
- **Env var not persisting** -- `$env:SUPABASE_DB_URL=...` only lasts for the current terminal session; use `setx` for it to persist across new terminals, and remember `setx` doesn't affect the terminal you ran it in (needs a fresh one).

---

## Done When (Beta Launch Checklist -- job duties amalgam feature)

- [ ] Amalgam logic validated across 3-5+ SOC codes of varying duties-coverage and industry breadth
- [ ] NAICS-segmentation behavior decided (segment automatically? ask user? show both?) and implemented consistently
- [ ] Decision made on whether this is a new standalone skill or folded into `h2b-wage-lookup`
- [ ] Output format finalized (plain paragraph vs. bulleted duty list vs. both)
- [ ] At least one real Aztec 9141 drafted using this tool's output, reviewed by Ray for usability
- [ ] `README.md` and this PRD updated to reflect the finalized feature

---

## Team & Contacts

- **Product Lead / Everything**: Ray Garrett -- raygarrettjr@gmail.com
- No team beyond Ray currently; single-user internal tool.

---

## Useful Links

- GitHub repo: https://github.com/raygarrettjr/aztec-soc-project
- Supabase project: `aztec-h2b-data` (ref `dduydmlrcmdzktqsnfuj`)
- DOL data feeds: https://seasonaljobs.dol.gov/feeds
- DOL OFLC disclosure data: https://www.dol.gov/agencies/eta/foreign-labor/performance

---

**Last Updated**: 2026-07-09
**Maintained By**: Ray Garrett
**Status**: In Progress -- core pipeline and automation live; job duties amalgam feature in beta validation
