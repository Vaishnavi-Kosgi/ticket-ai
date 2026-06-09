"""LLM layer: translate English -> SQL (Groq), then phrase the result in English."""
import os
import re
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


def llm_available() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


_SQL_SYSTEM = f"""You are a precise text-to-SQL translator for an SQLite database.
{SCHEMA_DESCRIPTION}
Rules:
- Output ONLY a single valid SQLite SELECT statement. No explanation, no markdown fences.
- Never write INSERT/UPDATE/DELETE/DROP or multiple statements.
- Use the exact category/priority/status spellings shown above.
- For "unresolved" use status != 'Resolved'.
- For date math on created_at, use SQLite datetime() functions.
"""


def _strip_fences(text: str) -> str:
    return re.sub(r"```sql|```", "", text).strip()


def nl_to_sql(question: str) -> str:
    resp = _get_client().chat.completions.create(
        model=MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": _SQL_SYSTEM},
            {"role": "user", "content": question},
        ],
    )
    return _strip_fences(resp.choices[0].message.content)


def summarize(question: str, rows: list, row_count: int) -> str:
    preview = rows[:20]  # a sample is enough; the count comes from the DB, not the LLM
    resp = _get_client().chat.completions.create(
        model=MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content":
             "You answer questions about support-ticket data. You are given the user's "
             "question, the EXACT number of result rows, and a sample of those rows (JSON). "
             "Rules: (1) The exact row count is provided - always use that number; never "
             "count the rows yourself. (2) Reply in one or two clear sentences. (3) If listing "
             "ticket IDs, list at most 5, then say 'and N more'. (4) If the count is 0, say no "
             "matching tickets were found."},
            {"role": "user", "content":
             f"Question: {question}\nExact row count: {row_count}\nSample rows: {preview}"},
        ],
    )
    return resp.choices[0].message.content.strip()