"""FastAPI app: health check, natural-language query, anomaly detection."""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import database as db
import anomalies
import llm


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()  # rebuild SQLite from the CSV on startup
    yield


app = FastAPI(title="Support Ticket AI", version="1.0", lifespan=lifespan)


class Query(BaseModel):
    question: str


@app.get("/health")
def health():
    return {
        "status": "ok",
        "rows_loaded": db.row_count(),
        "llm_configured": llm.llm_available(),
        "model": llm.MODEL,
    }


@app.post("/query")
def query(q: Query):
    question = q.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty.")
    try:
        sql = llm.nl_to_sql(question)
        cols, rows = db.run_query(sql)
        answer = llm.summarize(question, rows,len(rows))
        return {"question": question, "sql": sql, "row_count": len(rows),
                "rows": rows[:100], "answer": answer}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Could not run a safe query: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/anomalies")
def get_anomalies():
    return anomalies.detect_anomalies()