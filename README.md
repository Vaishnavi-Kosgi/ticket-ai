# Support Ticket AI

A small backend that takes a CSV of customer support tickets and lets you ask
questions about it in plain English. It also flags tickets that look off, like
high-priority ones that have been sitting unresolved for too long.

Built for the DOTMappers AI Engineer sprint. Everything runs locally and on
free-tier services, so there's nothing to pay for.

## What it does

There are three things you can hit:

- Ask a question in English ("how many tickets are open?") and get an answer back.
- Get a list of anomalies in the data.
- Check that the service is up and the data loaded.

Under the hood, an LLM turns your English question into SQL. That's the whole
trick. The data lives in SQLite, the LLM writes the query, the query runs, and
the LLM reads the result back to you in a sentence.

## How it's put together

The code is split so each file does one job:

- `database.py` loads the CSV into a SQLite table on startup and handles all the
  querying. It only allows read-only SELECTs and rejects anything that could
  change the data.
- `llm.py` is the only place that talks to the LLM. It does two calls: English to
  SQL, and then SQL-result back to English.
- `anomalies.py` is pure pandas, no LLM. Anomaly detection needs to be reliable
  and repeatable, so I kept it as plain deterministic rules.
- `main.py` is the FastAPI app that wires the three endpoints together.

One thing worth knowing: the dataset is historical (the newest ticket is from
March 2024). So anything time-relative like "this month" or "last 24 hours" is
measured against the latest ticket in the data, not today's real date. Both the
SQL prompt and the anomaly code anchor "now" to that latest timestamp on purpose.

## Tools used

- FastAPI for the API
- SQLite + pandas for storage and queries
- Groq free tier running `llama-3.3-70b-versatile` for the language model
- python-dotenv for the API key

## Setup

You need Python 3.10+ and a free Groq API key (https://console.groq.com).

```bash
pip install -r requirements.txt
cp .env.example .env        # then paste your key into .env
uvicorn main:app
```

The CSV gets loaded into SQLite automatically when the server starts, so there's
no separate setup step. Open http://127.0.0.1:8000/docs to try the endpoints.

## The endpoints

`GET /health` tells you it's running, how many rows loaded, and whether the LLM
key is configured.

`POST /query` takes `{"question": "..."}` and returns the SQL it generated, the
rows, and a plain-English answer.

`GET /anomalies` returns the flagged tickets.

## Example queries

These are real answers from the current dataset (500 tickets).

"How many tickets are currently open?"
> 111 tickets are currently open.

"How many critical tickets are unresolved?"
> 31 critical tickets are unresolved.

"What is the average customer rating for Technical category tickets?"
> The average customer rating for Technical tickets is 3.74.

"Which agent has the lowest average customer rating?"
> AGT-08 has the lowest average rating at 3.48.

For `/anomalies`, the current data flags two groups: 80 high/critical tickets
that have been unresolved for more than 24 hours, and 21 tickets whose resolution
time is a statistical outlier (above 48.1 hours, using the IQR rule).

## How anomaly detection works

Two rules, both deterministic:

1. Unresolved High or Critical tickets older than 24 hours. Straightforward and
   the kind of thing a support lead would actually want surfaced.
2. Resolution times that are statistical outliers. I used the IQR method
   (anything above Q3 + 1.5×IQR), which is a standard way to catch values that
   sit far outside the normal range without hardcoding a "too slow" threshold.

## Known limitations

- The SQLite db is rebuilt from the CSV every time the server starts. Fine for a
  prototype, but it means there's no persistence or live data ingestion.
- The English-to-SQL step can get a question wrong if it's ambiguous. The safety
  layer guarantees the query is read-only, but it can't guarantee the query
  actually answers what you meant.
- The query guard is a keyword denylist on SELECT-only statements, not a full SQL
  parser. It's solid for blocking writes but isn't a substitute for proper
  sandboxing if this faced untrusted users.
- The anomaly thresholds (24 hours, IQR 1.5×) are fixed. A real deployment would
  make these configurable per team.
- No multi-turn memory. Each question is answered on its own.

## What I'd do with more time

Add a few automated tests around the SQL generation, make the thresholds
configurable, and cache the schema/reference-date lookups instead of hitting the
db on every request.
