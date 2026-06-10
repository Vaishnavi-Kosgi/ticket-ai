"""CSV -> SQLite ingestion and safe read-only querying."""
import sqlite3
import pandas as pd
import re

DB_PATH = "tickets.db"
CSV_PATH = "support_tickets.csv"
TABLE = "tickets"

# Plain-English description of the table, fed to the LLM so it writes correct SQL.
SCHEMA_DESCRIPTION = """
Table: tickets
Columns:
  ticket_id           TEXT   unique id, e.g. 'TKT-001'
  created_at          TEXT   timestamp 'YYYY-MM-DD HH:MM' (use SQLite datetime() on it)
  category            TEXT   one of: 'Billing', 'Technical', 'General'
  priority            TEXT   one of: 'Low', 'Medium', 'High', 'Critical'
  status              TEXT   one of: 'Open', 'Resolved', 'Escalated'
  response_time_hrs   REAL   hours to first response
  resolution_time_hrs REAL   hours to resolution; NULL if not resolved
  agent_id            TEXT   assigned agent, e.g. 'AGT-04'
  customer_rating     REAL   1-5 satisfaction; NULL if not resolved
  issue_summary       TEXT   free-text description
Notes:
  - A ticket is "unresolved" when status != 'Resolved' (i.e. 'Open' or 'Escalated').
  - resolution_time_hrs and customer_rating are NULL for unresolved tickets.
"""


def init_db():
    """(Re)build the SQLite db from the CSV. Idempotent: safe to call on every startup."""
    df = pd.read_csv(CSV_PATH)
    conn = sqlite3.connect(DB_PATH)
    df.to_sql(TABLE, conn, if_exists="replace", index=False)
    conn.close()
    return len(df)


def row_count():
    conn = sqlite3.connect(DB_PATH)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    finally:
        conn.close()


# Anything that could mutate data is rejected.
_FORBIDDEN = ("insert", "update", "delete", "drop", "alter", "create",
              "replace", "attach", "pragma")


def run_query(sql: str):
    """Execute a single read-only SELECT and return (columns, rows). Raises on unsafe SQL."""
    clean = sql.strip().rstrip(";").strip()
    low = clean.lower()
    if not low.startswith("select"):
        raise ValueError("Only SELECT queries are allowed.")
    if any(re.search(rf"\b{kw}\b", low) for kw in _FORBIDDEN):
        raise ValueError("Query contains a forbidden keyword.")
    if ";" in clean:
        raise ValueError("Multiple statements are not allowed.")
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(clean)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return cols, rows
    finally:
        conn.close()