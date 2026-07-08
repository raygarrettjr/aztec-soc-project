"""
Bulk-load h2b_soc_data_2026.csv into Supabase Postgres.

Run this from Claude Code (or any environment with real internet access) --
the Cowork sandbox this project came from can't reach Supabase directly
(outbound network is proxy-restricted), which is why this wasn't run there.

Usage:
    pip install psycopg2-binary
    export SUPABASE_DB_URL="postgresql://postgres:[YOUR-PASSWORD]@db.dduydmlrcmdzktqsnfuj.supabase.co:5432/postgres"
    python load_to_supabase.py

Get the connection string from: Supabase dashboard -> aztec-h2b-data project
-> Project Settings -> Database -> Connection string (URI).
"""
import csv
import os
import sys

import psycopg2

DB_URL = os.environ.get("SUPABASE_DB_URL")
if not DB_URL:
    sys.exit("Set SUPABASE_DB_URL environment variable first (see docstring).")

CSV_PATH = os.path.join(os.path.dirname(__file__), "h2b_soc_data_2026.csv")

COLUMNS = [
    "case_number", "source", "case_status", "soc_code", "soc_title", "job_title",
    "workers_requested", "workers_certified", "employer_name", "employer_city",
    "employer_state", "worksite_city", "worksite_state", "wage_from", "wage_to",
    "wage_per", "employment_begin_date", "employment_end_date", "received_date",
    "decision_date", "noa_issued_date", "nature_of_need",
]

def main():
    print("Connecting...")
    conn = psycopg2.connect(DB_URL, connect_timeout=10)
    cur = conn.cursor()
    print("Connected. Creating table if needed...")

    with open(os.path.join(os.path.dirname(__file__), "schema.sql")) as f:
        cur.execute(f.read())
    conn.commit()

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [tuple(row[c] or None for c in COLUMNS) for row in reader]

    placeholders = ", ".join(["%s"] * len(COLUMNS))
    query = f"""
        INSERT INTO h2b_cases ({", ".join(COLUMNS)})
        VALUES ({placeholders})
        ON CONFLICT (case_number) DO NOTHING
    """
    cur.executemany(query, rows)
    conn.commit()

    cur.execute("SELECT count(*) FROM h2b_cases")
    print(f"Loaded. Table now has {cur.fetchone()[0]} rows.")

    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
