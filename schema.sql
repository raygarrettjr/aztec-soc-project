-- H-2B case data schema (SOC-filtered), Supabase project: aztec-h2b-data
-- Project ref: dduydmlrcmdzktqsnfuj
--
-- This is the comprehensive schema, capturing nearly every field DOL provides
-- across both source formats (quarterly disclosure XLSX + seasonaljobs.dol.gov
-- rolling feed JSON), not just the wage/duties subset from the first pass.
--
-- Multi-value structures from the feed (multiple worksites, multiple recruiters)
-- are stored as JSONB rather than normalized into separate tables -- simpler for
-- now, can be split out later if querying into them individually becomes common.

CREATE TABLE IF NOT EXISTS h2b_cases (
  case_number TEXT PRIMARY KEY,
  source TEXT NOT NULL,               -- 'disclosure_fy2026_q2' or 'seasonaljobs_feed'
  case_status TEXT,                   -- final determination (disclosure) or 'NOA Issued' (feed)

  -- Cap / worker counts
  cap_subject_workers NUMERIC,
  cap_exempt_workers NUMERIC,
  workers_requested NUMERIC,
  workers_certified NUMERIC,

  -- Job / occupation
  job_title TEXT,
  soc_code TEXT,
  soc_title TEXT,
  nature_of_need TEXT,                -- e.g. 'Seasonal', 'Peakload'
  job_duties TEXT,                    -- feed-only; disclosure never includes this
  temporary_need_statement TEXT,      -- feed-only narrative (tempneedDescription); distinct from nature_of_need
  special_requirements TEXT,          -- available from BOTH sources -- the SWA-relevant text
  education_level TEXT,
  training_months NUMERIC,
  work_experience_months NUMERIC,
  supervises_others TEXT,
  supervises_how_many NUMERIC,

  -- Dates
  requested_begin_date DATE,
  requested_end_date DATE,
  employment_begin_date DATE,
  employment_end_date DATE,
  received_date DATE,                 -- disclosure RECEIVED_DATE / feed dateApplicationSubmitted
  decision_date DATE,
  noa_issued_date DATE,

  -- Schedule
  anticipated_hours_total NUMERIC,
  hours_sunday NUMERIC,
  hours_monday NUMERIC,
  hours_tuesday NUMERIC,
  hours_wednesday NUMERIC,
  hours_thursday NUMERIC,
  hours_friday NUMERIC,
  hours_saturday NUMERIC,
  schedule_begin_time TEXT,
  schedule_end_time TEXT,

  -- Wages
  wage_from NUMERIC,
  wage_to NUMERIC,
  wage_per TEXT,
  overtime_available TEXT,
  overtime_rate_from NUMERIC,
  overtime_rate_to NUMERIC,
  additional_wage_conditions TEXT,
  pwd_case_number_1 TEXT,
  pwd_case_number_2 TEXT,
  pwd_case_number_3 TEXT,

  -- Employer
  employer_name TEXT,
  employer_trade_name TEXT,
  employer_address1 TEXT,
  employer_address2 TEXT,
  employer_city TEXT,
  employer_state TEXT,
  employer_postal_code TEXT,
  employer_country TEXT,
  employer_province TEXT,
  employer_phone TEXT,
  employer_phone_ext TEXT,
  employer_fein TEXT,
  naics_code TEXT,
  employer_type TEXT,

  -- Employer point of contact
  employer_poc_last_name TEXT,
  employer_poc_first_name TEXT,
  employer_poc_middle_name TEXT,
  employer_poc_job_title TEXT,
  employer_poc_address1 TEXT,
  employer_poc_address2 TEXT,
  employer_poc_city TEXT,
  employer_poc_state TEXT,
  employer_poc_postal_code TEXT,
  employer_poc_country TEXT,
  employer_poc_province TEXT,
  employer_poc_phone TEXT,
  employer_poc_phone_ext TEXT,
  employer_poc_email TEXT,

  -- Representation (attorney/agent)
  representation_type TEXT,
  attorney_last_name TEXT,
  attorney_first_name TEXT,
  attorney_middle_name TEXT,
  attorney_address1 TEXT,
  attorney_address2 TEXT,
  attorney_city TEXT,
  attorney_state TEXT,
  attorney_postal_code TEXT,
  attorney_country TEXT,
  attorney_province TEXT,
  attorney_phone TEXT,
  attorney_phone_ext TEXT,
  attorney_email TEXT,
  attorney_bar_number TEXT,
  attorney_firm_name TEXT,
  attorney_firm_fein TEXT,
  attorney_court_name TEXT,
  attorney_court_state TEXT,

  -- Preparer
  preparer_last_name TEXT,
  preparer_first_name TEXT,
  preparer_middle_initial TEXT,
  preparer_fein TEXT,
  preparer_business_name TEXT,
  preparer_email TEXT,

  -- SWA / job order
  swa_job_order_to_swa TEXT,
  swa_state TEXT,
  swa_job_order_submit_date DATE,

  -- Worksite
  worksite_address1 TEXT,
  worksite_address2 TEXT,
  worksite_city TEXT,
  worksite_state TEXT,
  worksite_postal_code TEXT,
  worksite_county TEXT,
  msa_area_name TEXT,

  -- Provisions / benefits
  daily_transportation_provided TEXT,
  otj_training_available TEXT,
  tools_equipment_provided TEXT,
  lodging_provided TEXT,
  payroll_deductions TEXT,
  phone_to_apply TEXT,
  email_to_apply TEXT,
  website_to_apply TEXT,

  -- Recruiter
  foreign_labor_recruiter TEXT,
  foreign_labor_recruiter_agreement_attached TEXT,

  -- Nested/multi-value data (feed only) -- stored as JSONB, not normalized
  employment_locations_json JSONB,
  recruiters_json JSONB,
  employer_client_json JSONB,

  -- Minor compliance/attachment checkbox fields, consolidated rather than
  -- given individual columns (see full_reload.py for what goes in here)
  compliance_flags_json JSONB,

  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_h2b_cases_soc_code ON h2b_cases(soc_code);
CREATE INDEX IF NOT EXISTS idx_h2b_cases_state ON h2b_cases(worksite_state);
CREATE INDEX IF NOT EXISTS idx_h2b_cases_worksite_zip ON h2b_cases(worksite_postal_code);
CREATE INDEX IF NOT EXISTS idx_h2b_cases_employer_zip ON h2b_cases(employer_postal_code);
CREATE INDEX IF NOT EXISTS idx_h2b_cases_employer_fein ON h2b_cases(employer_fein);
