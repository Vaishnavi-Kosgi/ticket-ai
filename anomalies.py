"""Deterministic anomaly detection. No LLM here on purpose: rules must be reliable."""
import sqlite3
import pandas as pd

from database import DB_PATH, TABLE

STALE_HOURS = 24  # how old an unresolved high-priority ticket must be to be flagged


def _load_df():
    conn = sqlite3.connect(DB_PATH)
    try:
        return pd.read_sql(f"SELECT * FROM {TABLE}", conn)
    finally:
        conn.close()


def detect_anomalies():
    """Two kinds of anomalies:
       1. Stale unresolved High/Critical tickets (> STALE_HOURS old).
       2. Statistically abnormal resolution times (IQR upper-fence outliers).
    """
    df = _load_df()
    df["created_at"] = pd.to_datetime(df["created_at"])

    # The dataset is historical, so we anchor "now" to the latest ticket in the
    # data rather than the real wall clock. (Documented in README.)
    now = df["created_at"].max()

    # --- Anomaly 1: stale unresolved high-priority tickets ---
    unresolved = df[df["status"] != "Resolved"].copy()
    high = unresolved[unresolved["priority"].isin(["High", "Critical"])].copy()
    high["age_hrs"] = (now - high["created_at"]).dt.total_seconds() / 3600
    stale = high[high["age_hrs"] > STALE_HOURS].sort_values("age_hrs", ascending=False)
    stale_list = [
        {
            "ticket_id": r.ticket_id,
            "priority": r.priority,
            "status": r.status,
            "age_hrs": round(r.age_hrs, 1),
            "agent_id": r.agent_id,
            "issue_summary": r.issue_summary,
        }
        for r in stale.itertuples()
    ]

    # --- Anomaly 2: abnormally long resolution times (IQR method) ---
    resolved = df[df["resolution_time_hrs"].notna()]
    rt = resolved["resolution_time_hrs"]
    q1, q3 = rt.quantile(0.25), rt.quantile(0.75)
    upper_fence = q3 + 1.5 * (q3 - q1)
    outliers = resolved[resolved["resolution_time_hrs"] > upper_fence] \
        .sort_values("resolution_time_hrs", ascending=False)
    outlier_list = [
        {
            "ticket_id": r.ticket_id,
            "priority": r.priority,
            "category": r.category,
            "resolution_time_hrs": round(r.resolution_time_hrs, 1),
            "agent_id": r.agent_id,
        }
        for r in outliers.itertuples()
    ]

    return {
        "reference_time": str(now),
        "stale_unresolved_high_priority": {
            "rule": f"status != 'Resolved', priority in (High, Critical), older than {STALE_HOURS}h",
            "count": len(stale_list),
            "tickets": stale_list,
        },
        "abnormal_resolution_times": {
            "rule": f"resolution_time_hrs > Q3 + 1.5*IQR (= {round(upper_fence, 1)}h)",
            "upper_fence_hrs": round(upper_fence, 1),
            "count": len(outlier_list),
            "tickets": outlier_list,
        },
    }