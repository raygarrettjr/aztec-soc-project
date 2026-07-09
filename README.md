# Aztec H-2B SOC Data

H-2B case data filtered to 26 target SOC codes, covering January 1, 2026 through July 8, 2026.
Captures nearly every field DOL provides across both source formats, not just wages --
the goal is to have enough data on hand to eventually auto-suggest prefill values for
ETA-9141 (prevailing wage), the SWA job order, and ETA-9142B (H-2B application) filings.

## Files

- `schema.sql` -- Postgres table definition used in Supabase (~130 columns)
- `full_reload.py` -- full rebuild script: reads the disclosure XLSX and all feed
  zips from Downloads, maps every available field, truncates `h2b_cases`, and
  reloads it fresh. Replaces the older `load_to_supabase.py` +
  `backfill_zip_and_duties.py` one-time scripts (kept in the repo for history,
  no longer used).
- `update_from_feed.py` -- weekly incremental updater, run automatically via GitHub Actions (see below)
- `.github/workflows/weekly-update.yml` -- the GitHub Actions workflow that runs
  `update_from_feed.py` on a weekly schedule, in GitHub's cloud
- `h2b_soc_data_2026.csv` -- original 10,593-row export from the first pass (25 columns);
  kept as a historical snapshot, superseded by the live table

## Sources

1. **DOL OFLC Disclosure Data, FY2026 Q2** (`source = 'disclosure_fy2026_q2'`)
   Cumulative final determinations for Oct 1, 2025 - Mar 31, 2026, filtered to records
   received or decided on/after Jan 1, 2026.
   https://www.dol.gov/agencies/eta/foreign-labor/performance

2. **SeasonalJobs.dol.gov rolling feed** (`source = 'seasonaljobs_feed'`)
   NOA-issued (Notice of Acceptance) cases pulled from 20-day-window snapshots,
   used to bridge the gap until the next quarterly disclosure file is published
   (Q3 FY2026 expected ~mid-August 2026), and to capture the free-text fields
   (`job_duties`, `temporary_need_statement`) that disclosure data never includes.
   Deduplicated against the disclosure set by case number.
   https://seasonaljobs.dol.gov/feeds

## Target SOC codes (26)

35-3023.00, 35-9021.00, 47-2051.00, 35-2011.00, 37-3012.00, 53-7062.00, 35-2021.00,
47-2061.00, 53-7064.00, 39-3091.00, 37-3011.00, 35-2014.00, 37-2012.00, 35-3031.00,
37-2011.00, 45-4011.00, 39-2021.00, 43-4081.00, 53-3032.00, 49-9098.00, 51-3022.00,
35-9011.00, 35-3011.00, 47-3016.00, 35-1012.00, 35-2015.00

## Known limitation

Records dated April 1, 2026 onward reflect NOA-issuance only (`case_status = 'NOA Issued'`),
not final certification/denial outcomes, until OFLC publishes Q3 disclosure data.
Re-run `full_reload.py` with the new disclosure file once it's out (mid-August 2026)
to backfill final statuses for that window.

## Supabase

- Project: `aztec-h2b-data` (ref `dduydmlrcmdzktqsnfuj`)
- Table `h2b_cases` -- see `schema.sql` for the full column list. Highlights relevant
  to filing automation:
  - `job_duties` -- feed-only, needed for ETA-9141 prevailing wage requests
  - `special_requirements` -- available from **both** sources, the main SWA job-order
    relevant text (physical requirements, schedule notes, drug testing, etc.)
  - `temporary_need_statement` -- feed-only long-form narrative (distinct from the
    short `nature_of_need` category like "Seasonal"/"Peakload")
  - `employment_locations_json`, `recruiters_json`, `employer_client_json` -- raw
    nested feed data for cases with multiple worksites/recruiters, stored as JSONB
  - `compliance_flags_json` -- minor attachment/checkbox fields from both sources
    (Appendix A/B/C/D attached, MSPA attached, etc.), consolidated rather than
    given individual columns
  - `employer_postal_code` / `worksite_postal_code` -- zip codes for wage lookups

## Why the weekly update job matters

The seasonaljobs.dol.gov feed only shows a rolling 20-day window of NOA-issued cases.
`job_duties` and `temporary_need_statement` only ever exist in that feed -- never in
the quarterly disclosure files (though `special_requirements` is in both). That means
the weekly pull isn't just a status refresh: it's the only way this project accumulates
that free-text over time. A missed pull means any case that aged out of the 20-day
window before being captured has lost that text permanently (it'll still eventually
show up via the next disclosure release, just without the feed-only fields). Running
the update weekly, rather than every 20 days, gives a safety margin -- even if a single
run fails, the next one 7 days later still falls inside the previous case's window.

The upsert logic in `update_from_feed.py` never overwrites a final `case_status` back
to "NOA Issued", and never clears out a populated field just because a later pull
doesn't have that value (`COALESCE(new, old)` on every column).

## Setting up the weekly update (GitHub Actions)

Runs in GitHub's cloud on a schedule, so it fires every week regardless of whether
your PC is on. The workflow file is already in the repo at
`.github/workflows/weekly-update.yml`; you just need to add one secret and push.

1. Add your Supabase connection string as a repo secret (this keeps the password
   out of the code entirely -- GitHub encrypts it and only exposes it to the
   workflow run, never in logs or the repo itself):
   - Go to the repo on github.com -> **Settings** -> **Secrets and variables** ->
     **Actions** -> **New repository secret**
   - Name: `SUPABASE_DB_URL`
   - Value: the same connection string you used locally, e.g.
     `postgresql://postgres.dduydmlrcmdzktqsnfuj:YOUR-PASSWORD@aws-1-us-east-2.pooler.supabase.com:5432/postgres`

2. Commit and push the workflow file:
   ```powershell
   git add .github/workflows/weekly-update.yml
   git commit -m "Add weekly update GitHub Action"
   git push
   ```

3. Test it manually: on github.com, go to the **Actions** tab -> **Weekly H-2B Feed
   Update** in the left sidebar -> **Run workflow** button -> **Run workflow**.
   Watch the run; expand the "Run weekly update" step to see the same printed row
   counts you'd see running it locally.

4. It will otherwise run automatically every Monday at 08:00 UTC. To change the
   schedule, edit the `cron:` line in `.github/workflows/weekly-update.yml` --
   cron times are in UTC, not your local time zone.

If a run ever fails, GitHub emails the account that owns the repo -- check the
Actions tab for the error output either way.

### Alternative: Windows Task Scheduler (local, optional)

Only useful as a backup or if you'd rather not use GitHub Actions. Downside: it only
runs if your PC is on, awake, and logged in at the scheduled time.

1. Set a persistent environment variable (one-time):
   ```powershell
   setx SUPABASE_DB_URL "postgresql://postgres.dduydmlrcmdzktqsnfuj:YOUR-PASSWORD@aws-1-us-east-2.pooler.supabase.com:5432/postgres"
   ```
   Close and reopen any terminal after running this once, for the variable to take effect.

2. Install dependencies (if not already done):
   ```powershell
   pip install psycopg2-binary requests
   ```

3. Open **Task Scheduler** (search for it in the Start menu) -> **Create Basic Task**.
   - Name: `H-2B Weekly Update`
   - Trigger: Weekly, pick a day/time
   - Action: Start a program
     - Program/script: `python`
     - Add arguments: `update_from_feed.py`
     - Start in: `C:\Users\rayga\Dev\aztec_soc_project`
   - Finish, then find the task in the Task Scheduler Library, right-click -> Properties ->
     check "Run whether user is logged on or not" if you want it to run even when you're
     not actively logged in (may prompt for your Windows password to save this setting).

4. Test it manually once: right-click the task -> **Run**, then check the output by
   opening a terminal and running `python update_from_feed.py` directly to see the printed
   row counts, or query Supabase directly (see verification queries below).

## Doing a full reload (new quarter's disclosure file, or schema changes)

1. Download the new disclosure XLSX and any feed zips you want included into
   `C:\Users\rayga\Downloads`, matching the filenames referenced at the top of
   `full_reload.py` (update that list if filenames differ).
2. Run:
   ```powershell
   python full_reload.py
   ```
   This truncates `h2b_cases` and reloads everything from scratch -- safe to
   re-run any time you get a new disclosure file or add more feed snapshots.
