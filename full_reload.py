"""
Full reload: reads the disclosure XLSX and all feed zips from Downloads,
extracts the COMPLETE field set (not just wage/duties), and rebuilds
h2b_cases from scratch. Replaces load_to_supabase.py + backfill_zip_and_duties.py
-- run this instead of those two now that the schema captures nearly every
DOL field.

This is safe to re-run: it truncates and reloads every time, so if you add
more feed zips to FEED_ZIPS later, just re-run it to get a clean full rebuild.

Usage:
    pip install psycopg2-binary python-calamine
    $env:SUPABASE_DB_URL="postgresql://...same as before..."
    python full_reload.py
"""
import datetime
import json
import os
import sys
import zipfile

import psycopg2
import psycopg2.extras
from python_calamine import CalamineWorkbook

DB_URL = os.environ.get("SUPABASE_DB_URL")
if not DB_URL:
    sys.exit("Set SUPABASE_DB_URL environment variable first (see docstring).")

DOWNLOADS = os.path.join(os.path.expanduser("~"), "Downloads")
DISCLOSURE_XLSX = os.path.join(DOWNLOADS, "H-2B_Disclosure_Data_FY2026_Q2.xlsx")
FEED_ZIPS = [
    "2026-04-19_h2b.zip",
    "2026-05-09_h2b.zip",
    "2026-05-29_h2b.zip",
    "2026-06-18_h2b.zip",
    "2026-07-08_h2b.zip",
]

SOC_CODES = {
    "35-3023.00", "35-9021.00", "47-2051.00", "35-2011.00", "37-3012.00", "53-7062.00",
    "35-2021.00", "47-2061.00", "53-7064.00", "39-3091.00", "37-3011.00", "35-2014.00",
    "37-2012.00", "35-3031.00", "37-2011.00", "45-4011.00", "39-2021.00", "43-4081.00",
    "53-3032.00", "49-9098.00", "51-3022.00", "35-9011.00", "35-3011.00", "47-3016.00",
    "35-1012.00", "35-2015.00",
}
CUTOFF = datetime.date(2026, 1, 1)

# All columns in the table, in insert order. Keep this in sync with schema.sql.
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


def blank_row(case_number, source, case_status):
    row = {c: None for c in COLUMNS}
    row["case_number"] = case_number
    row["source"] = source
    row["case_status"] = case_status
    return row


def as_date(v):
    if isinstance(v, datetime.datetime):
        return v.date().isoformat()
    if isinstance(v, datetime.date):
        return v.isoformat()
    return None


def feed_date(v):
    if not v:
        return None
    try:
        return datetime.datetime.strptime(v, "%d-%b-%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Disclosure XLSX
# ---------------------------------------------------------------------------

DISCLOSURE_DIRECT_MAP = {
    "CASE_NUMBER": "case_number", "CASE_STATUS": "case_status",
    "RECEIVED_DATE": "received_date", "DECISION_DATE": "decision_date",
    "CAP_SUBJECT_WORKERS": "cap_subject_workers", "CAP_EXEMPT_WORKERS": "cap_exempt_workers",
    "JOB_TITLE": "job_title", "SOC_CODE": "soc_code", "SOC_TITLE": "soc_title",
    "TOTAL_WORKERS_REQUESTED": "workers_requested", "TOTAL_WORKERS_CERTIFIED": "workers_certified",
    "REQUESTED_BEGIN_DATE": "requested_begin_date", "REQUESTED_END_DATE": "requested_end_date",
    "EMPLOYMENT_BEGIN_DATE": "employment_begin_date", "EMPLOYMENT_END_DATE": "employment_end_date",
    "NATURE_OF_TEMPORARY_NEED": "nature_of_need",
    "EMPLOYER_NAME": "employer_name", "TRADE_NAME_DBA": "employer_trade_name",
    "EMPLOYER_ADDRESS1": "employer_address1", "EMPLOYER_ADDRESS2": "employer_address2",
    "EMPLOYER_CITY": "employer_city", "EMPLOYER_STATE": "employer_state",
    "EMPLOYER_POSTAL_CODE": "employer_postal_code", "EMPLOYER_COUNTRY": "employer_country",
    "EMPLOYER_PROVINCE": "employer_province", "EMPLOYER_PHONE": "employer_phone",
    "EMPLOYER_PHONE_EXT": "employer_phone_ext", "EMPLOYER_FEIN": "employer_fein",
    "NAICS_CODE": "naics_code",
    "EMPLOYER_POC_LAST_NAME": "employer_poc_last_name", "EMPLOYER_POC_FIRST_NAME": "employer_poc_first_name",
    "EMPLOYER_POC_MIDDLE_NAME": "employer_poc_middle_name", "EMPLOYER_POC_JOB_TITLE": "employer_poc_job_title",
    "EMPLOYER_POC_ADDRESS1": "employer_poc_address1", "EMPLOYER_POC_ADDRESS2": "employer_poc_address2",
    "EMPLOYER_POC_CITY": "employer_poc_city", "EMPLOYER_POC_STATE": "employer_poc_state",
    "EMPLOYER_POC_POSTAL_CODE": "employer_poc_postal_code", "EMPLOYER_POC_COUNTRY": "employer_poc_country",
    "EMPLOYER_POC_PROVINCE": "employer_poc_province", "EMPLOYER_POC_PHONE": "employer_poc_phone",
    "EMPLOYER_POC_PHONE_EXT": "employer_poc_phone_ext", "EMPLOYER_POC_EMAIL": "employer_poc_email",
    "TYPE_OF_REPRESENTATION": "representation_type",
    "ATTORNEY_AGENT_LAST_NAME": "attorney_last_name", "ATTORNEY_AGENT_FIRST_NAME": "attorney_first_name",
    "ATTORNEY_AGENT_MIDDLE_NAME": "attorney_middle_name", "ATTORNEY_AGENT_ADDRESS1": "attorney_address1",
    "ATTORNEY_AGENT_ADDRESS2": "attorney_address2", "ATTORNEY_AGENT_CITY": "attorney_city",
    "ATTORNEY_AGENT_STATE": "attorney_state", "ATTORNEY_AGENT_POSTAL_CODE": "attorney_postal_code",
    "ATTORNEY_AGENT_COUNTRY": "attorney_country", "ATTORNEY_AGENT_PROVINCE": "attorney_province",
    "ATTORNEY_AGENT_PHONE": "attorney_phone", "ATTORNEY_AGENT_PHONE_EXT": "attorney_phone_ext",
    "ATTORNEY_AGENT_EMAIL_ADDRESS": "attorney_email",
    "LAWFIRM_NAME_BUSINESS_NAME": "attorney_firm_name", "LAWFIRM_BUSINESS_FEIN": "attorney_firm_fein",
    "STATE_OF_HIGHEST_COURT": "attorney_court_state", "NAME_OF_HIGHEST_STATE_COURT": "attorney_court_name",
    "JOB_ORDER_TO_SWA": "swa_job_order_to_swa", "SWA_STATE": "swa_state",
    "JOB_ORDER_SUBMIT_DATE": "swa_job_order_submit_date",
    "ANTICIPATED_NUMBER_OF_HOURS": "anticipated_hours_total",
    "SUNDAY_HOURS": "hours_sunday", "MONDAY_HOURS": "hours_monday", "TUESDAY_HOURS": "hours_tuesday",
    "WEDNESDAY_HOURS": "hours_wednesday", "THURSDAY_HOURS": "hours_thursday",
    "FRIDAY_HOURS": "hours_friday", "SATURDAY_HOURS": "hours_saturday",
    "HOURLY_SCHEDULE_BEGIN": "schedule_begin_time", "HOURLY_SCHEDULE_END": "schedule_end_time",
    "EDUCATION_LEVEL": "education_level", "TRAINING_MONTHS": "training_months",
    "WORK_EXPERIENCE_MONTHS": "work_experience_months",
    "SUPERVISE_OTHER_EMP": "supervises_others", "SUPERVISE_HOW_MANY": "supervises_how_many",
    "SPECIAL_REQUIREMENTS": "special_requirements",
    "WORKSITE_ADDRESS1": "worksite_address1", "WORKSITE_ADDRESS2": "worksite_address2",
    "WORKSITE_CITY": "worksite_city", "WORKSITE_STATE": "worksite_state",
    "WORKSITE_POSTAL_CODE": "worksite_postal_code", "WORKSITE_COUNTY": "worksite_county",
    "MSA_NAME_OES_AREA_TITLE": "msa_area_name",
    "BASIC_WAGE_RATE_FROM": "wage_from", "BASIC_WAGE_RATE_TO": "wage_to", "PER": "wage_per",
    "OVERTIME_AVAILABLE": "overtime_available", "OVERTIME_RATE_FROM": "overtime_rate_from",
    "OVERTIME_RATE_TO": "overtime_rate_to", "ADDITIONAL_WAGE_CONDITIONS": "additional_wage_conditions",
    "1st_PWD_CASE_NUMBER": "pwd_case_number_1", "2nd_PWD_CASE_NUMBER": "pwd_case_number_2",
    "3rd_PWD_CASE_NUMBER": "pwd_case_number_3",
    "DAILY_TRANSPORTATION": "daily_transportation_provided",
    "ON_THE_JOB_TRAINING_AVAILABLE": "otj_training_available",
    "EMP_PROVIDED_TOOLS_EQUIPMENT": "tools_equipment_provided",
    "BOARD_LODGING_OTHER_FACILITIES": "lodging_provided",
    "DEDUCTIONS_FROM_PAY": "payroll_deductions",
    "PHONE_TO_APPLY": "phone_to_apply", "EMAIL_TO_APPLY": "email_to_apply",
    "WEBSITE_TO_APPLY": "website_to_apply", "TYPE_OF_EMPLOYER": "employer_type",
    "FOREIGN_LABOR_RECRUITER": "foreign_labor_recruiter",
    "PREPARER_LAST_NAME": "preparer_last_name", "PREPARER_FIRST_NAME": "preparer_first_name",
    "PREPARER_MIDDLE_INITIAL": "preparer_middle_initial", "PREPARER_FEIN": "preparer_fein",
    "PREPARER_BUSINESS_NAME": "preparer_business_name", "PREPARER_EMAIL": "preparer_email",
}
DATE_COLUMNS = {
    "received_date", "decision_date", "requested_begin_date", "requested_end_date",
    "employment_begin_date", "employment_end_date", "swa_job_order_submit_date",
    "noa_issued_date",
}
DISCLOSURE_COMPLIANCE_FIELDS = [
    "AGENT_AGREEMENT_ATTACHED", "AGENT_MSPA_ATTACHED", "EMP_MSPA_ATTACHED",
    "APPENDIX_A_ATTACHED", "APPENDIX_D_COMPLETED", "JOB_CONTRACT_EXISTS",
    "AGREEMENTS_ATTACHED", "APPENDIX_C_ATTACHED", "EMPLOYER_APPENDIX_B_ATTACHED",
    "EMP_CLIENT_APPENDIX_B_ATTACHED", "EMERGENCY_FILING_PWD_ATTACHED", "OTHER_WORKSITE_LOCATION",
]


def load_disclosure_rows():
    if not os.path.exists(DISCLOSURE_XLSX):
        print(f"WARNING: {DISCLOSURE_XLSX} not found, skipping disclosure source.")
        return []

    wb = CalamineWorkbook.from_path(DISCLOSURE_XLSX)
    ws = wb.get_sheet_by_name(wb.sheet_names[0])
    data = ws.to_python()
    header = data[0]
    idx = {name: i for i, name in enumerate(header)}

    rows = []
    for raw in data[1:]:
        soc = raw[idx["SOC_CODE"]] if "SOC_CODE" in idx else None
        if soc not in SOC_CODES:
            continue
        recv = raw[idx["RECEIVED_DATE"]] if "RECEIVED_DATE" in idx else None
        dec = raw[idx["DECISION_DATE"]] if "DECISION_DATE" in idx else None
        recv_d, dec_d = as_date(recv), as_date(dec)
        keep = (recv_d and recv_d >= CUTOFF.isoformat()) or (dec_d and dec_d >= CUTOFF.isoformat())
        if not keep:
            continue

        row = blank_row(raw[idx["CASE_NUMBER"]], "disclosure_fy2026_q2", raw[idx.get("CASE_STATUS", 0)])
        for src_col, dest_col in DISCLOSURE_DIRECT_MAP.items():
            if src_col not in idx:
                continue
            val = raw[idx[src_col]]
            if dest_col in DATE_COLUMNS:
                val = as_date(val)
            row[dest_col] = val

        flags = {}
        for src_col in DISCLOSURE_COMPLIANCE_FIELDS:
            if src_col in idx:
                v = raw[idx[src_col]]
                if v is not None:
                    flags[src_col] = str(v)
        row["compliance_flags_json"] = json.dumps(flags) if flags else None

        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Feed JSON (from the already-downloaded zips)
# ---------------------------------------------------------------------------

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


def load_feed_rows():
    by_case = {}
    for zip_name in FEED_ZIPS:
        zip_path = os.path.join(DOWNLOADS, zip_name)
        if not os.path.exists(zip_path):
            print(f"WARNING: {zip_path} not found, skipping.")
            continue
        with zipfile.ZipFile(zip_path) as zf:
            json_name = [n for n in zf.namelist() if n.endswith(".json")][0]
            with zf.open(json_name) as f:
                records = json.load(f)
        for r in records:
            if r.get("tempneedSoc") not in SOC_CODES:
                continue
            cn = r["caseNumber"]
            noa = r.get("dateAcceptanceLtrIssued") or ""
            existing = by_case.get(cn)
            if existing is None or noa > existing.get("dateAcceptanceLtrIssued", ""):
                by_case[cn] = r

    rows = []
    for cn, r in by_case.items():
        row = blank_row(cn, "seasonaljobs_feed", "NOA Issued")
        for src_key, dest_col in FEED_DIRECT_MAP.items():
            row[dest_col] = r.get(src_key)
        for src_key, dest_col in FEED_DATE_FIELDS.items():
            row[dest_col] = feed_date(r.get(src_key))
        row["requested_begin_date"] = row["employment_begin_date"]
        row["requested_end_date"] = row["employment_end_date"]

        begin_t = r.get("jobHourStart")
        begin_p = r.get("jobStartperiod")
        if begin_t:
            row["schedule_begin_time"] = f"{begin_t} {begin_p}".strip() if begin_p else begin_t
        end_t = r.get("jobHourEnd")
        end_p = r.get("jobEndperiod")
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

        rows.append(row)
    return rows


def main():
    disclosure_rows = load_disclosure_rows()
    feed_rows_all = load_feed_rows()
    disclosure_cases = {r["case_number"] for r in disclosure_rows}
    feed_rows = [r for r in feed_rows_all if r["case_number"] not in disclosure_cases]

    print(f"Disclosure rows: {len(disclosure_rows)}")
    print(f"Feed rows (pre-dedup vs disclosure): {len(feed_rows_all)}")
    print(f"Feed rows (after removing overlap with disclosure): {len(feed_rows)}")

    all_rows = disclosure_rows + feed_rows

    def clean(v):
        # Blank spreadsheet/feed cells sometimes come through as "" rather than
        # None -- Postgres will reject "" for NUMERIC/DATE columns, so normalize
        # every empty string to NULL before inserting.
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    tuples = [tuple(clean(r[c]) for c in COLUMNS) for r in all_rows]

    conn = psycopg2.connect(DB_URL, connect_timeout=10)
    cur = conn.cursor()

    print("Truncating h2b_cases...")
    cur.execute("TRUNCATE TABLE h2b_cases")

    print(f"Inserting {len(tuples)} rows...")
    insert_sql = f"INSERT INTO h2b_cases ({', '.join(COLUMNS)}) VALUES %s"
    psycopg2.extras.execute_values(cur, insert_sql, tuples, page_size=500)
    conn.commit()

    cur.execute("SELECT count(*) FROM h2b_cases")
    print(f"Done. Table now has {cur.fetchone()[0]} rows.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
