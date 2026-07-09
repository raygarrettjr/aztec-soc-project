# Aztec H-2B Project -- Status Handoff

Paste this whole file into a new chat if the current thread runs out of room,
so Claude can pick up without re-deriving context.

## Goal

Aztec Labor (H-2B seasonal labor filings business) is building a database of DOL
H-2B case data to eventually auto-suggest prefill values for its own filings:
ETA-9141 (prevailing wage), the SWA job order, and ETA-9142B (H-2B application).
Currently in a beta-testing phase for the first concrete product: given an SOC
code, produce a clean, "amalgamated" job duties description built from real
filings under that code (most common duties, in simple clean language) --
intended for the 9141.

## Where everything lives

- **Local project folder**: `C:\Users\rayga\Dev\aztec_soc_project\`
- **GitHub repo**: `https://github.com/raygarrettjr/aztec-soc-project` (main branch)
  - NOTE: there is ALSO an unrelated repo called `h2b-petition-data` under the
    same account -- this project is NOT that one. Don't confuse them; this has
    bitten us twice already (secret added to wrong repo, workflow not found).
- **Supabase project**: `aztec-h2b-data`, project ref `dduydmlrcmdzktqsnfuj`,
  table `h2b_cases`. Accessed in-session via the Supabase MCP connector
  (`execute_sql`, `apply_migration`, etc.) -- no need for local psycopg2 access
  just to query/inspect data, only for local script runs.

## Files (all in the repo/local folder)

- `schema.sql` -- current live Postgres schema (~130 columns + naics_code index).
  Always keep this in sync with actual `apply_migration` calls made in-session.
- `full_reload.py` -- full rebuild: reads disclosure XLSX + feed zips from
  `C:\Users\rayga\Downloads`, maps every field, truncates `h2b_cases`, reloads
  fresh. Safe to re-run anytime. **Must be run locally** (needs local file access
  to Downloads + DB write access).
- `update_from_feed.py` -- weekly incremental updater. Now runs automatically
  via GitHub Actions (see below), not manually.
- `.github/workflows/weekly-update.yml` -- GitHub Actions workflow, cron
  `0 8 * * 1` (Monday 08:00 UTC) + manual `workflow_dispatch`. Needs repo secret
  `SUPABASE_DB_URL` set on the **aztec-soc-project** repo specifically.
- `load_to_supabase.py`, `backfill_zip_and_duties.py` -- obsolete one-time
  scripts, kept for history only, not used anymore.
- `README.md` -- full documentation of sources, schema highlights, automation
  setup, and full-reload instructions.
- Skill file: `h2b-wage-lookup` -- SKILL.md drafted and packaged as a `.skill`
  zip, presented to the user for install (installs via Cowork's "Save skill").
  Covers SOC+zip wage lookup, job duties/special_requirements/temporary_need_statement
  synthesis, and now includes a NAICS-clustering caveat (see below). This skill
  is broader than the specific beta product currently being tested (see
  "Current focus" below) -- may need to fold in or be superseded by whatever
  the job-duties-only tool becomes.

## Schema highlights worth remembering

- `job_duties` -- **feed-only** (`source = 'seasonaljobs_feed'`). Disclosure
  files never include this by design. ~3,197 rows have it (all feed rows).
- `special_requirements` -- available from **both** sources, ~99.98% coverage.
  Richest, most reliable field (physical requirements, schedule notes, drug
  testing policy).
- `temporary_need_statement` -- feed-only, optional even within feed (~1,604
  of 3,197 feed rows have it). Distinct from short `nature_of_need` category.
- `naics_code` -- newly leveraged (previously unused). Confirmed useful for
  splitting SOC codes that span multiple business contexts -- e.g. 39-3091.00
  (Amusement and Recreation Attendants) spans traveling carnivals (NAICS 71399
  family), hotels/resorts (721110), event/party equipment rental (532289), and
  performing arts companies (711190). Duty language differs meaningfully by
  context, so **check NAICS clustering before amalgamating duties for a SOC
  code that might span industries.**
- 26 target SOC codes (full list in README.md and hardcoded in all scripts).

## Bugs fixed (don't reintroduce)

1. **Empty-string-in-NUMERIC bug**: blank Excel cells came through as `""` not
   `None`, which Postgres rejects for NUMERIC/DATE columns. Fixed in
   `full_reload.py` via a `clean()` pass converting `""` to `None` before insert.
2. **`.0` float-suffix bug**: `python_calamine` reads bare-numeric Excel cells
   (no letters/hyphens, e.g. NAICS codes, phone numbers) as Python floats. When
   stored in TEXT columns this left a stray `.0` (e.g. `"71399.0"` instead of
   `"71399"`), silently splitting what should be one value into two. Fixed via
   `clean_disclosure_value()` / `NUMERIC_COLUMNS` set in `full_reload.py` --
   only columns actually NUMERIC in schema.sql are left as floats; everything
   else gets converted to a clean int string. **Confirmed zip codes were NOT
   affected** (already stored as text in the source). Already re-run and
   verified fixed as of this handoff.
3. **Feed date fallback**: the weekly feed URL is dated (e.g. `.../h2b/2026-07-08`),
   but "today" (UTC, in GitHub Actions) doesn't always match what DOL has
   actually published (midnight-Eastern cutover, publish lag, weekends). Fixed
   `fetch_today_feed()` in `update_from_feed.py` to walk backward up to 10 days
   until it finds a file that actually exists.

## Automation status: LIVE

GitHub Actions runs `update_from_feed.py` every Monday 08:00 UTC automatically,
no dependency on any local machine. Confirmed working end-to-end (manual test
run succeeded, found the 2026-07-08 feed via the date-fallback logic, upserted
37 matching records). If a run ever fails, GitHub emails the repo owner and the
Actions tab shows the error.

## Current focus: job duties amalgam beta (in progress)

Testing whether "enter a SOC code, get back a clean amalgamated list of the most
commonly-filed job duties" is good enough to launch as the first beta product.
Method being validated: pull all `job_duties` text for a SOC code, count
frequency of individual duty keywords/phrases across filings (via SQL
`count(*) filter (where job_duties ilike '%x%')` per candidate term), and also
check for a dominant near-verbatim reused paragraph (often the O*NET official
task summary for that SOC, which filers/attorneys reuse as known-safe language).

**Tested so far:**
- **37-3011.00 (Landscaping/Groundskeeping)**: 1,179 of 5,276 filings have
  duties text. Strong, clean result -- top duties (mowing 84%, planting 83%,
  trimming 78%, sod laying 63%, watering 61%, etc.) produced a coherent amalgam
  paragraph. One dominant O*NET-style paragraph reused 41+ times verbatim.
- **39-3091.00 (Amusement and Recreation Attendants)**: 116 of 262 filings have
  duties text (44% coverage, lower than landscaping). Initial amalgam (cleaning
  80%, assisting patrons 78%, inspect/repair 75%, etc.) worked, BUT this SOC
  code spans multiple NAICS-distinct business contexts (carnival vs. hotel vs.
  party rental vs. performing arts) with materially different duty emphasis.
  This is what led to adding `naics_code` to the analysis (see Schema
  highlights above) and fixing the `.0` bug that was corrupting NAICS grouping.

**Immediate next step** (not yet done): redo the 39-3091.00 job duties amalgam
split out by the now-clean NAICS clusters (71399-family = carnival, 721110 =
hotel/resort, 532289 = equipment rental, 711190 = performing arts, 561320 =
staffing agency placement) to see whether NAICS-segmented amalgams are
meaningfully better/cleaner than one blended amalgam, and whether that's worth
building into the beta tool (e.g., tool asks "carnival, resort, or rental
context?" when a SOC code's filings cluster into multiple NAICS groups above
some threshold).

**Open product question not yet resolved**: should this become its own
dedicated skill (SOC-code-in, clean duties-list-out, no zip needed since duties
don't vary much geographically) separate from the existing `h2b-wage-lookup`
skill (which is SOC+zip, and bundles wages + duties + special_requirements +
temp_need together)? Leaning toward yes but hasn't been decided with the user.

## Verification queries used repeatedly (handy reference)

```sql
-- Row/field coverage check
select count(*) as total, count(job_duties) as has_duties,
       count(special_requirements) as has_special_req,
       count(temporary_need_statement) as has_temp_need
from h2b_cases;

-- Duty keyword frequency for a SOC code (adapt keyword list per occupation)
select count(*) filter (where job_duties ilike '%mow%') as mow, ...
from h2b_cases where soc_code = 'XX-XXXX.XX' and job_duties is not null;

-- NAICS clustering check before amalgamating duties
select naics_code, count(*) as n, count(job_duties) as with_duties
from h2b_cases where soc_code = 'XX-XXXX.XX'
group by naics_code order by n desc;
```
