"""
One-time backfill: adds employer/worksite postal codes (from the disclosure
xlsx and feed JSON) and job duties text (feed JSON only) to the 10,593 rows
already loaded into h2b_cases.

Run this locally (same machine/terminal you used for load_to_supabase.py) --
it needs real internet access to Supabase, and it reads the raw source files
straight out of your Downloads folder (no re-download from DOL needed, since
we already have them there from the original pull).

Usage:
    pip install psycopg2-binary python-calamine
    $env:SUPABASE_DB_URL="postgresql://...same as before..."
    python backfill_zip_and_duties.py
"""
import csv
import datetime
import glob
import json
import os
import sys
import zipfile

import psycopg2
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


def as_date(v):
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    return None


def load_disclosure_updates():
    """Returns list of (employer_zip, worksite_zip, case_number) for disclosure rows."""
    if not os.path.exists(DISCLOSURE_XLSX):
        print(f"WARNING: {DISCLOSURE_XLSX} not found, skipping disclosure backfill.")
        return []

    wb = CalamineWorkbook.from_path(DISCLOSURE_XLSX)
    ws = wb.get_sheet_by_name(wb.sheet_names[0])
    data = ws.to_python()
    header = data[0]
    idx = {name: i for i, name in enumerate(header)}

    updates = []
    for row in data[1:]:
        soc = row[idx["SOC_CODE"]]
        if soc not in SOC_CODES:
            continue
        recv = as_date(row[idx["RECEIVED_DATE"]])
        dec = as_date(row[idx["DECISION_DATE"]])
        if not ((recv and recv >= CUTOFF) or (dec and dec >= CUTOFF)):
            continue
        emp_zip = row[idx["EMPLOYER_POSTAL_CODE"]]
        work_zip = row[idx["WORKSITE_POSTAL_CODE"]]
        case_number = row[idx["CASE_NUMBER"]]
        updates.append((emp_zip, work_zip, None, case_number))
    return updates


def load_feed_updates():
    """Returns list of (employer_zip, worksite_zip, job_duties, case_number) for feed rows."""
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
            noa_date = r.get("dateAcceptanceLtrIssued") or ""
            existing = by_case.get(cn)
            if existing is None or noa_date > existing[0]:
                by_case[cn] = (noa_date, r.get("empPostcode"), r.get("jobPostcode"), r.get("jobDuties"))

    return [(v[1], v[2], v[3], cn) for cn, v in by_case.items()]


def main():
    conn = psycopg2.connect(DB_URL, connect_timeout=10)
    cur = conn.cursor()

    disclosure_updates = load_disclosure_updates()
    feed_updates = load_feed_updates()

    print(f"Disclosure rows to update: {len(disclosure_updates)}")
    print(f"Feed rows to update: {len(feed_updates)}")

    query = """
        UPDATE h2b_cases
        SET employer_postal_code = COALESCE(%s, employer_postal_code),
            worksite_postal_code = COALESCE(%s, worksite_postal_code),
            job_duties = COALESCE(%s, job_duties)
        WHERE case_number = %s
    """
    all_updates = disclosure_updates + feed_updates
    cur.executemany(query, all_updates)
    conn.commit()

    cur.execute("SELECT count(*) FROM h2b_cases WHERE employer_postal_code IS NOT NULL")
    zip_count = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM h2b_cases WHERE job_duties IS NOT NULL")
    duties_count = cur.fetchone()[0]
    print(f"Rows with employer zip: {zip_count}")
    print(f"Rows with job duties text: {duties_count}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
