-- H-2B case data schema (SOC-filtered), Supabase project: aztec-h2b-data
-- Project ref: dduydmlrcmdzktqsnfuj

CREATE TABLE IF NOT EXISTS h2b_cases (
  case_number TEXT PRIMARY KEY,
  source TEXT NOT NULL,               -- 'disclosure_fy2026_q2' or 'seasonaljobs_feed'
  case_status TEXT,                   -- final determination (disclosure) or 'NOA Issued' (feed)
  soc_code TEXT,
  soc_title TEXT,
  job_title TEXT,
  workers_requested NUMERIC,
  workers_certified NUMERIC,
  employer_name TEXT,
  employer_city TEXT,
  employer_state TEXT,
  worksite_city TEXT,
  worksite_state TEXT,
  wage_from NUMERIC,
  wage_to NUMERIC,
  wage_per TEXT,
  employment_begin_date DATE,
  employment_end_date DATE,
  received_date DATE,
  decision_date DATE,
  noa_issued_date DATE,
  nature_of_need TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_h2b_cases_soc_code ON h2b_cases(soc_code);
CREATE INDEX IF NOT EXISTS idx_h2b_cases_state ON h2b_cases(worksite_state);
