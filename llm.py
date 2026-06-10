"""LLM layer: translate English -> SQL (Groq), then phrase the result in English."""
import os
import re
import sqlite3
from database import DB_PATH, TABLE
from groq import Groq
from dotenv import load_dotenv

from database import SCHEMA_DESCRIPTION

load_dotenv()

MODEL = "llama-3.3-70b-versatile"
_client = None


def _get_client():
    global _client
    if _client is None:
        key = os.getenv("GROQ_API_KEY")
        if not key:
            raise RuntimeError("GROQ_API_KEY is not set. Add it to your .env file.")
        _client = Groq(api_key=key)
    return _client

def _reference_date() -> str:
    """Latest ticket timestamp — the dataset's notion of 'now'. Data is historical."""
    conn = sqlite3.connect(DB_PATH)
    try:
        return conn.execute(f"SELECT MAX(created_at) FROM {TABLE}").fetchone()[0]
    finally:
        conn.close()


def llm_available() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


def _build_sql_system() -> str:
    ref = _reference_date()
    return f"""You are a precise text-to-SQL translator for an SQLite database.
{SCHEMA_DESCRIPTION}
IMPORTANT — the data is HISTORICAL. The most recent ticket is dated {ref}.
Treat all relative time expressions ("today", "this month", "this week",
"last 24 hours", "recently") relative to {ref}, NOT the real current date.
NEVER use datetime('now') or date('now') — substitute the literal date {ref} instead.
Example: "this month" -> created_at >= '{ref[:7]}-01'.

CRITICAL — the SELECT must contain the value that answers the question.
If a column appears in ORDER BY, it MUST also appear in SELECT. Returning only
a grouping key (like agent_id or category) is WRONG because the actual number
is then lost. Follow these patterns exactly:

  Q: Which agent has the lowest average customer rating?
  WRONG: SELECT agent_id FROM tickets WHERE customer_rating IS NOT NULL
         GROUP BY agent_id ORDER BY AVG(customer_rating) ASC LIMIT 1
  RIGHT: SELECT agent_id, ROUND(AVG(customer_rating),2) AS avg_rating FROM tickets
         WHERE customer_rating IS NOT NULL GROUP BY agent_id
         ORDER BY avg_rating ASC LIMIT 1

  Q: Which category has the worst average resolution time?
  RIGHT: SELECT category, ROUND(AVG(resolution_time_hrs),2) AS avg_hrs FROM tickets
         WHERE resolution_time_hrs IS NOT NULL GROUP BY category
         ORDER BY avg_hrs DESC LIMIT 1

  Q: Which agent resolved the most tickets this month?
  RIGHT: SELECT agent_id, COUNT(*) AS resolved FROM tickets WHERE status='Resolved'
         AND created_at >= '{ref[:7]}-01' GROUP BY agent_id
         ORDER BY resolved DESC LIMIT 1

Rules:
- Output ONLY a single valid SQLite SELECT statement. No explanation, no markdown fences.
- Never write INSERT/UPDATE/DELETE/DROP or multiple statements.
- Use the exact category/priority/status spellings shown above.
- For "unresolved" use status != 'Resolved'.
"""



def _strip_fences(text: str) -> str:
    return re.sub(r"```sql|```", "", text).strip()


def nl_to_sql(question: str) -> str:
    resp = _get_client().chat.completions.create(
        model=MODEL, temperature=0,
        messages=[
            {"role": "system", "content": _build_sql_system()},
            {"role": "user", "content": question},
        ],
    )
    return _strip_fences(resp.choices[0].message.content)

def summarize(question: str, rows: list, row_count: int) -> str:
    preview = rows[:20]
    resp = _get_client().chat.completions.create(
        model=MODEL, temperature=0,
        messages=[
            {"role": "system", "content":
             "You answer questions about support-ticket data from a SQL result. "
             "You get the user's question, row_count (how many rows the query "
             "returned), and a sample of those rows as JSON.\n"
             "How to find the answer:\n"
             "- If a row contains an aggregate value (a column like COUNT(...), "
             "AVG(...), SUM(...), MIN/MAX, or a renamed total/average), the answer "
             "is THAT value inside the row. Report it. Do NOT report row_count.\n"
             "- Only use row_count itself as the answer when the user asked 'how "
             "many' AND each row is an individual ticket (no aggregate column).\n"
             "- Never say things like 'there is 1 row representing 31 tickets'.\n"
             "Style: one or two clear sentences. If listing ticket IDs, show at "
             "most 5 then 'and N more'. If there are no rows, say no matching "
             "tickets were found."},
            {"role": "user", "content":
             f"Question: {question}\nrow_count: {row_count}\nSample rows: {preview}"},
        ],
    )
    return resp.choices[0].message.content.strip()