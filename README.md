# Aztec H-2B SOC Data

H-2B case data filtered to 26 target SOC codes, covering January 1, 2026 through July 8, 2026.

## Files

- `h2b_soc_data_2026.csv` -- 10,593 unique H-2B case records (the full dataset)
- `schema.sql` -- Postgres table definition used in Supabase
- `load_to_supabase.py` -- bulk loader script (run locally / in Claude Code, not in a network-restricted sandbox)

## Sources

1. **DOL OFLC Disclosure Data, FY2026 Q2** (`source = 'disclosure_fy2026_q2'`)
   Cumulative final determinations for Oct 1, 2025 - Mar 31, 2026, filtered to records
   received or decided on/after Jan 1, 2026. 7,396 rows.
   https://www.dol.gov/agencies/eta/foreign-labor/performance

2. **SeasonalJobs.dol.gov rolling feed** (`source = 'seasonaljobs_feed'`)
   NOA-issued (Notice of Acceptance) cases pulled from five 20-day-window snapshots
   between April 19 and July 8, 2026, to bridge the gap until Q3 FY2026 disclosure
   data is published (expected ~mid-August 2026). 3,197 rows, deduplicated against
   the disclosure set by case number.
   https://seasonaljobs.dol.gov/feeds

## Target SOC codes (26)

35-3023.00, 35-9021.00, 47-2051.00, 35-2011.00, 37-3012.00, 53-7062.00, 35-2021.00,
47-2061.00, 53-7064.00, 39-3091.00, 37-3011.00, 35-2014.00, 37-2012.00, 35-3031.00,
37-2011.00, 45-4011.00, 39-2021.00, 43-4081.00, 53-3032.00, 49-9098.00, 51-3022.00,
35-9011.00, 35-3011.00, 47-3016.00, 35-1012.00, 35-2015.00

## Known limitation

Records dated April 1 - July 8, 2026 reflect NOA-issuance only (`case_status = 'NOA Issued'`),
not final certification/denial outcomes, since OFLC hasn't published Q3 disclosure data yet.
Re-run the Q2/Q3 pull and re-filter once it's out (mid-August 2026) to backfill final
statuses for that window.

## Supabase

- Project: `aztec-h2b-data` (ref `dduydmlrcmdzktqsnfuj`)
- Table `h2b_cases` is created but empty -- see `load_to_supabase.py` to load it.
  This step needs to run somewhere with real network access to Supabase (the sandbox
  this was built in has proxy-restricted egress that blocks both supabase.co and
  api.github.com).
