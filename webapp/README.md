# Job Duties Suggestion Tool — Web Interface (Beta)

Short-term hosted interface so any Aztec employee can open a link, pick an occupation
(SOC code) and, if relevant, a NAICS industry context, and get a four-part job duties
suggestion generated live from real filing data and O*NET's official reference. This
follows the same methodology documented in the `h2b-wage-lookup` skill's `SKILL.md`
(frequency threshold, O*NET core-duty floor, tool specificity, risk analysis, RFI
examples, no em dashes) rather than a hardcoded template, so it keeps working as the
underlying data updates weekly.

Hosted on **Vercel**, not Netlify. This workload (a handful of database queries plus a
full Claude generation call) realistically takes somewhere in the 10-25 second range,
and Netlify's free/personal tier kills synchronous functions after 10 seconds. Vercel's
free Hobby tier gives 30 seconds by default and up to 300 seconds with Fluid Compute
(also free), which comfortably covers this without needing a paid plan.

## Important: a security issue to fix before this goes live

Supabase flagged that **Row Level Security (RLS) is disabled on `h2b_cases`**. That
table is currently fully exposed to Supabase's `anon` key, so if this key were ever
used from the browser (client-side), anyone with it could read or modify every row.

This app is designed to avoid that: the browser never talks to Supabase directly, only
to this app's own serverless functions, which connect to Postgres directly using the
`SUPABASE_DB_URL` connection string (kept server-side only, never sent to the browser).
As long as that stays true, this specific exposure isn't triggered by this app. But
the underlying issue is still open on the database itself, and should be fixed
independently, especially if anything else ever uses the Supabase client library or
the anon key directly. The fix is:

```sql
ALTER TABLE public.h2b_cases ENABLE ROW LEVEL SECURITY;
-- then add explicit policies for whatever access pattern is actually needed,
-- since enabling RLS with no policies blocks all access, including this app's own
-- service connection if it were ever switched to use the anon/service key instead
-- of a direct Postgres connection string.
```

Don't run this without deciding on policies first, since it will otherwise lock out
all access, including the weekly update job and the Supabase MCP connection used in
chat. Worth a deliberate pass, not an urgent blocker for this specific app's launch.

## What's in this folder

- `public/index.html` — the entire frontend: SOC dropdown, NAICS dropdown (scoped live
  to whatever NAICS codes actually appear for the selected SOC), a generate button, and
  a results panel that renders the returned Markdown.
- `api/naics-options.js` — given a SOC code, returns the distinct NAICS industry
  descriptions that actually appear in real filings for that SOC, grouped by resolved
  title (multiple raw digit-precision codes can share one title).
- `api/generate-duties.js` — given a SOC code and optional NAICS codes, pulls a live
  sample of real `job_duties` text, RFI-flagged filings, wage averages (for this SOC
  and any O*NET-related SOC that's also in Aztec's 26-code dataset), and the bundled
  O*NET reference file, then calls the Anthropic API with those as grounding to
  generate the four-part suggestion.
- `api/lib/instructions.js` — the system prompt given to the model, condensed from
  `h2b-wage-lookup/SKILL.md`'s duty-amalgam methodology plus the 5-or-50%-whichever-
  is-greater selection rule. Keep this in sync if the skill's methodology changes.
- `api/lib/reference.js` — loads and parses the bundled O*NET reference files and the
  NAICS code-to-title lookup.
- `api/data/` — a copy of `onet_reference/` (71 files) and `naics_reference.csv`,
  bundled so the deployed functions don't need a live fetch.
- `vercel.json` — tells Vercel to bundle `api/data/**` into the deployed functions
  (Vercel's static analysis doesn't always catch dynamic file reads on its own) and
  sets `generate-duties` to a 60-second max duration for headroom.

## Required secrets (set these as Vercel environment variables, not in code)

- `SUPABASE_DB_URL` — the same Postgres connection string already used for the weekly
  GitHub Actions update job.
- `ANTHROPIC_API_KEY` — a new key from the Anthropic API console
  (https://console.anthropic.com), scoped to this project's usage if you want separate
  billing visibility. This is the one new piece of infrastructure this app needs that
  didn't already exist.

Optional tuning:
- `DUTY_SAMPLE_SIZE` (default 200) — how many real `job_duties` rows are sampled per
  request. Higher gives the model more signal for frequency estimates, but costs more
  tokens and a slower response.
- `MAX_OUTPUT_TOKENS` (default 3200).
- `ANTHROPIC_MODEL` (default `claude-sonnet-5`).

## Deploying to Vercel

1. Push this repo (including the `webapp/` folder) to GitHub if not already done.
2. On vercel.com: **Add New...** → **Project**, then connect GitHub if not already
   linked, and select the `aztec-soc-project` repo.
3. On the configuration screen, set **Root Directory** to `webapp` (since this app
   lives in a subfolder of the main repo, not the repo root). Vercel should
   auto-detect it as a plain Node.js project; leave the build/install commands as
   whatever it auto-fills (typically `npm install`, no build command needed since
   there's no bundling step for a static `public/` folder plus `api/` functions).
4. Add the environment variables before deploying (or right after, under
   **Settings → Environment Variables**): `SUPABASE_DB_URL` and `ANTHROPIC_API_KEY`.
5. Click **Deploy**. Vercel gives you a `*.vercel.app` URL; anyone with the link can
   use the tool (no login, by design, for this short-term version). Vercel's
   password-protection for a project is a Pro-plan feature; on the free tier, the
   main way to limit access for a beta is simply not sharing the link widely, or
   asking the team to only test it over a known window.
6. Test end-to-end: pick Landscaping and Groundskeeping Workers (37-3011.00), generate,
   and compare the output against `sample_output_landscaping.md` in the main project
   folder. It won't be word-for-word identical since it's generated live from a live
   data sample, but the structure, the selection logic, and the tone should match.

## Known limitations of this short-term version

- No authentication (see the Vercel password-protection note above). Anyone with the
  link can generate suggestions and see the underlying real filing stats used to
  build them (not raw employer-identifying data, since employer fields are never
  queried or returned by these functions, but real duty-text snippets are).
- Each generation is a live model call using a real data sample, not a cached answer,
  so cost and latency scale with how many people use it and how large
  `DUTY_SAMPLE_SIZE` is. Worth keeping an eye on Anthropic API usage during the beta.
- No submission/webhook step yet; this only produces suggested text for a specialist
  to review and paste into the actual filing. Airtable webhook integration is still a
  separate, later task.
- Duty and tool frequency figures are the model's estimate from the sampled real text
  supplied to it, not a precomputed exact percentage the way the earlier static demo
  document was. That's an intentional tradeoff for staying current as data updates
  weekly, per the direction to have this be AI-driven against live data rather than a
  fixed template.
