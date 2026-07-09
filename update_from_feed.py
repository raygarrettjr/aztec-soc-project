"""
Weekly update job: pulls today's 20-day rolling H-2B feed from
seasonaljobs.dol.gov, filters to the 26 target SOC codes, and upserts into
Supabase using the full comprehensive field set (same mapping as
full_reload.py). This is the main way job_duties, special_requirements, and
temporary_need_statement text get captured long-term, since DOL's quarterly
disclosure files never include job_duties/temporary_need_statement (though
they DO include special_requirements).

Run weekly via Windows Task Scheduler (see README.md for setup). Needs real
internet access -- run this locally, not in a restricted sandbox.

Usage:
    pip install psycopg2-binary requests
    $env:SUPABASE_DB_URL="postgresql://...same as before..."
    python update_from_feed.py
"""
import datetime
import io
import json
import os
import sys
import zipfile

import psycopg2
import psycopg2.extras
import requests

DB_URL = os.environ.get("SUPABASE_DB_URL")
if not DB_URL:
    sys.exit("Set SUPABASE_DB_URL environment variable first (see docstring).")

SOC_CODES = {
    "35-3023.00", "35-9021.00", "47-2051.00", "35-2011.00", "37-3012.00", "53-7062.00",
    "35-2021.00", "47-2061.00", "53-7064.00", "39-3091.00", "37-3011.00", "35-2014.00",
    "37-2012.00", "35-3031.00", "37-2011.00", "45-4011.00", "39-2021.00", "43-4081.00",
    "53-3032.00", "49-9098.00", "51-3022.00", "35-9011.00", "35-3011.00", "47-3016.00",
    "35-1012.00", "35-2015.00",
}

# Same column list as full_reload.py -- keep these in sync with schema.sql.
COLUMNS = [
    "case_number", "source", "case_status",
    "cap_subject_workers", "cap_exempt_workers", "workers_requested", "workers_certified",
    "job_title", "soc_code", "soc_title", "nature_of_need", "temporary_need_statement",
    "job_duties", "special_requirements", "education_level", "training_months",
    "work_experience_months", "supervises_others", "supervises_how_many",
    "requested_begin_date", "requested_end_date", "employment_begin_date", "employment_end_date",
    "received_date", "decision_date", "noa_issued_date",
    "anticipated_hours_total", "hours_sunday", "hours_monday", "hours_tuesday",
    "hours_wednesday", "hours_thursday", "hours_friday", "hours_saturday",
    "schedule_begin_time", "schedule_end_time",
    "wage_from", "wage_to", "wage_per", "overtime_available", "overtime_rate_from",
    "overtime_rate_to", "additional_wage_conditions",
    "pwd_case_number_1", "pwd_case_number_2", "pwd_case_number_3",
    "employer_name", "employer_trade_name", "employer_address1", "employer_address2",
    "employer_city", "employer_state", "employer_postal_code", "employer_country",
    "employer_province", "employer_phone", "employer_phone_ext", "employer_fein",
    "naics_code", "employer_type",
    "employer_poc_last_name", "employer_poc_first_name", "employer_poc_middle_name",
    "employer_poc_job_title", "employer_poc_address1", "employer_poc_address2",
    "employer_poc_city", "employer_poc_state", "employer_poc_postal_code",
    "employer_poc_country", "employer_poc_province", "employer_poc_phone",
    "employer_poc_phone_ext", "employer_poc_email",
    "representation_type", "attorney_last_name", "attorney_first_name",
    "attorney_middle_name", "attorney_address1", "attorney_address2", "attorney_city",
    "attorney_state", "attorney_postal_code", "attorney_country", "attorney_province",
    "attorney_phone", "attorney_phone_ext", "attorney_email", "attorney_bar_number",
    "attorney_firm_name", "attorney_firm_fein", "attorney_court_name", "attorney_court_state",
    "preparer_last_name", "preparer_first_name", "preparer_middle_initial", "preparer_fein",
    "preparer_business_name", "preparer_email",
    "swa_job_order_to_swa", "swa_state", "swa_job_order_submit_date",
    "worksite_address1", "worksite_address2", "worksite_city", "worksite_state",
    "worksite_postal_code", "worksite_county", "msa_area_name",
    "daily_transportation_provided", "otj_training_available", "tools_equipment_provided",
    "lodging_provided", "payroll_deductions", "phone_to_apply", "email_to_apply",
    "website_to_apply",
    "foreign_labor_recruiter", "foreign_labor_recruiter_agreement_attached",
    "employment_locations_json", "recruiters_json", "employer_client_json",
    "compliance_flags_json",
]

# Columns that should never be clobbered by a later, less-complete pull.
# COALESCE(new, old) so a missing value in this pull keeps whatever's stored.
PRESERVE_IF_NULL = [c for c in COLUMNS if c not in ("case_number", "source")]

FEED_DIRECT_MAP = {
    "capSubject": "cap_subject_workers", "capExempt": "cap_exempt_workers",
    "tempneedJobtitle": "job_title", "tempneedSoc": "soc_code", "tempneedSocTitle": "soc_title",
    "tempneedWkrPos": "workers_requested", "tempneedNature": "nature_of_need",
    "tempneedDescription": "temporary_need_statement",
    "empBusinessName": "employer_name", "empTradeName": "employer_trade_name",
    "empAddr1": "employer_address1", "empAddr2": "employer_address2",
    "empCity": "employer_city", "empState": "employer_state", "empPostcode": "employer_postal_code",
    "empCountry": "employer_country", "empProvince": "employer_province",
    "empPhone": "employer_phone", "empPhoneext": "employer_phone_ext", "empFein": "employer_fein",
    "empNaics": "naics_code", "empType": "employer_type",
    "emppocLastname": "employer_poc_last_name", "emppocFirstname": "employer_poc_first_name",
    "emppocMiddlename": "employer_poc_middle_name", "emppocJobtitle": "employer_poc_job_title",
    "emppocAddr1": "employer_poc_address1", "emppocAddr2": "employer_poc_address2",
    "emppocCity": "employer_poc_city", "emppocState": "employer_poc_state",
    "emppocPostcode": "employer_poc_postal_code", "emppocCountry": "employer_poc_country",
    "emppocProvince": "employer_poc_province", "emppocPhone": "employer_poc_phone",
    "emppocPhoneext": "employer_poc_phone_ext", "emppocEmail": "employer_poc_email",
    "attyRepresentType": "representation_type",
    "attyLastname": "attorney_last_name", "attyFirstname": "attorney_first_name",
    "attyMiddlename": "attorney_middle_name", "attyAddr1": "attorney_address1",
    "attyAddr2": "attorney_address2", "attyCity": "attorney_city", "attyState": "attorney_state",
    "attyPostcode": "attorney_postal_code", "attyCountry": "attorney_country",
    "attyProvince": "attorney_province", "attyPhone": "attorney_phone",
    "attyPhoneext": "attorney_phone_ext", "attyEmail": "attorney_email",
    "attyBizname": "attorney_firm_name", "attyFein": "attorney_firm_fein",
    "attyStatebarno": "attorney_bar_number", "attyNamehighct": "attorney_court_name",
    "attyStatehighct": "attorney_court_state",
    "swaJoborderAttached": "swa_job_order_to_swa", "swaJoborderStatename": "swa_state",
    "jobDuties": "job_duties",
    "jobHoursTotal": "anticipated_hours_total", "jobHoursSun": "hours_sunday",
    "jobHoursMon": "hours_monday", "jobHoursTues": "hours_tuesday", "jobHoursWed": "hours_wednesday",
    "jobHoursThu": "hours_thursday", "jobHoursFri": "hours_friday", "jobHoursSat": "hours_saturday",
    "jobMinedu": "education_level", "jobMintrainingmonths": "training_months",
    "jobMinexpmonths": "work_experience_months", "jobSupervisor": "supervises_others",
    "jobNumberSup": "supervises_how_many", "jobMinspecialreq": "special_requirements",
    "jobAddr1": "worksite_address1", "jobAddr2": "worksite_address2", "jobCity": "worksite_city",
    "jobState": "worksite_state", "jobPostcode": "worksite_postal_code", "jobCounty": "worksite_county",
    "jobMsa": "msa_area_name",
    "wageFrom": "wage_from", "wageTo": "wage_to", "wageOtFrom": "overtime_rate_from",
    "wageOtTo": "overtime_rate_to", "wagePer": "wage_per", "wageAdditional": "additional_wage_conditions",
    "jobPwdNumber": "pwd_case_number_1", "jobPwdNumber2": "pwd_case_number_2",
    "jobPwdNumber3": "pwd_case_number_3",
    "recIsDailyTransport": "daily_transportation_provided", "recIsOtAvailable": "overtime_available",
    "recIsTrainingAvailable": "otj_training_available", "recIsToolsEquip": "tools_equipment_provided",
    "recIsLodging": "lodging_provided", "recPayDeductions": "payroll_deductions",
    "recApplyPhone": "phone_to_apply", "recApplyEmail": "email_to_apply", "recApplyUrl": "website_to_apply",
    "empflrecEngageH2b": "foreign_labor_recruiter",
    "prepLastname": "preparer_last_name", "prepFirstname": "preparer_first_name",
    "prepMiddlename": "preparer_middle_initial", "prepFein": "preparer_fein",
    "prepBizname": "preparer_business_name", "prepEmail": "preparer_email",
}
FEED_DATE_FIELDS = {
    "tempneedStart": "employment_begin_date", "tempneedEnd": "employment_end_date",
    "dateApplicationSubmitted": "received_date", "dateAcceptanceLtrIssued": "noa_issued_date",
    "swaJoborderSubmitted": "swa_job_order_submit_date",
}
FEED_COMPLIANCE_FIELDS = [
    "appIsCapExempt", "attyIsAgreementAttached", "agntMspaAttached", "appIsH2bPwdAttached",
    "jobMultiplesites", "empJoinApdxAAttached", "empMspAttached", "empclntApdxDAttached",
    "empIsContractAttached", "empflrecEngageH2bAttached", "empflrecApdxCAttached",
    "declareIsConfmApdxB", "declareConfmEmp", "registrationNumber", "formVersionId",
]


def iso_date(v):
    """Feed dates look like '07-Sep-2026'; convert to ISO or return None."""
    if not v:
        return None
    try:
        return datetime.datetime.strptime(v, "%d-%b-%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def fetch_today_feed(max_days_back=10):
    """
    The feed URL is dated (e.g. .../h2b/2026-07-08), but the exact date DOL has
    actually published isn't guaranteed to be "today" -- there can be a
    publish-time lag, timezone offset (DOL updates at midnight Eastern; this
    runs in UTC), or weekend/holiday gaps. Try today first, then walk backward
    a few days until one actually resolves, rather than assuming today's date
    always exists.
    """
    last_error = None
    for days_back in range(max_days_back):
        day = (datetime.date.today() - datetime.timedelta(days=days_back)).isoformat()
        url = f"https://api.seasonaljobs.dol.gov/datahub-search/sjCaseData/zip/h2b/{day}"
        print(f"Trying {url} ...")
        resp = requests.get(url, timeout=60)
        if resp.status_code == 404:
            last_error = f"404 for {day}"
            continue
        resp.raise_for_status()
        print(f"Found feed dated {day}.")
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            json_name = [n for n in zf.namelist() if n.endswith(".json")][0]
            with zf.open(json_name) as f:
                return json.load(f)
    raise RuntimeError(
        f"No feed file found in the last {max_days_back} days. Last error: {last_error}"
    )


def to_row(r):
    row = {c: None for c in COLUMNS}
    row["case_number"] = r["caseNumber"]
    row["source"] = "seasonaljobs_feed"
    row["case_status"] = "NOA Issued"

    for src_key, dest_col in FEED_DIRECT_MAP.items():
        row[dest_col] = r.get(src_key)
    for src_key, dest_col in FEED_DATE_FIELDS.items():
        row[dest_col] = iso_date(r.get(src_key))
    row["requested_begin_date"] = row["employment_begin_date"]
    row["requested_end_date"] = row["employment_end_date"]

    begin_t, begin_p = r.get("jobHourStart"), r.get("jobStartperiod")
    if begin_t:
        row["schedule_begin_time"] = f"{begin_t} {begin_p}".strip() if begin_p else begin_t
    end_t, end_p = r.get("jobHourEnd"), r.get("jobEndperiod")
    if end_t:
        row["schedule_end_time"] = f"{end_t} {end_p}".strip() if end_p else end_t

    flags = {k: r[k] for k in FEED_COMPLIANCE_FIELDS if r.get(k) is not None}
    row["compliance_flags_json"] = json.dumps(flags) if flags else None

    for json_key, dest_col in [
        ("employmentLocations", "employment_locations_json"),
        ("recruiters", "recruiters_json"),
        ("employerClient", "employer_client_json"),
    ]:
        val = r.get(json_key)
        row[dest_col] = json.dumps(val) if val else None

    return tuple(row[c] for c in COLUMNS)


def main():
    records = fetch_today_feed()
    matched = [to_row(r) for r in records if r.get("tempneedSoc") in SOC_CODES]
    print(f"Total records in today's pull: {len(records)}")
    print(f"Matching target SOC codes: {len(matched)}")

    if not matched:
        print("Nothing to upsert.")
        return

    conn = psycopg2.connect(DB_URL, connect_timeout=10)
    cur = conn.cursor()

    # Never overwrite a final case_status with a fresh 'NOA Issued', and never
    # clobber a populated field with a NULL from this pull -- COALESCE(new, old)
    # for everything except case_status, which has its own status-priority rule.
    set_clauses = []
    for c in PRESERVE_IF_NULL:
        if c == "case_status":
            set_clauses.append(
                "case_status = CASE WHEN h2b_cases.case_status = 'NOA Issued' "
                "THEN EXCLUDED.case_status ELSE h2b_cases.case_status END"
            )
        else:
            set_clauses.append(f"{c} = COALESCE(EXCLUDED.{c}, h2b_cases.{c})")

    query = f"""
        INSERT INTO h2b_cases ({", ".join(COLUMNS)})
        VALUES %s
        ON CONFLICT (case_number) DO UPDATE SET
            {", ".join(set_clauses)}
    """
    psycopg2.extras.execute_values(cur, query, matched, page_size=500)
    conn.commit()

    for check_col in ("job_duties", "special_requirements", "temporary_need_statement", "worksite_postal_code"):
        cur.execute(f"SELECT count(*) FROM h2b_cases WHERE {check_col} IS NOT NULL")
        print(f"Rows with {check_col}: {cur.fetchone()[0]}")

    cur.execute("SELECT count(*) FROM h2b_cases")
    print(f"Done. Table now has {cur.fetchone()[0]} total rows.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
