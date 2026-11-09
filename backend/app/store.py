import sqlite3, os, json
from contextlib import contextmanager
DB=os.getenv("DB_PATH","monitor.db")
@contextmanager
def conn():
    c=sqlite3.connect(DB)
    try: yield c; c.commit()
    finally: c.close()
def init():
    with conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS daily_features(
          asset TEXT, date TEXT, close REAL, score REAL, confirmed INTEGER,
          features_json TEXT, UNIQUE(asset,date))""")
def save_row(asset,date,close,result,features):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO daily_features VALUES(?,?,?,?,?,?)",
          (asset,date,close,result.get("score"),int(result.get("confirmed_bottom",False)),json.dumps(features)))
def rows(asset):
    with conn() as c:
        return c.execute("SELECT date,close,score,confirmed FROM daily_features WHERE asset=? ORDER BY date",(asset,)).fetchall()


def history_rows(asset, start_date=None, end_date=None):
    """Return stored daily snapshots including their serialized feature details."""
    query = "SELECT date,close,score,confirmed,features_json FROM daily_features WHERE asset=?"
    params = [asset]
    if start_date:
        query += " AND date>=?"
        params.append(start_date)
    if end_date:
        query += " AND date<=?"
        params.append(end_date)
    query += " ORDER BY date"
    with conn() as c:
        records = c.execute(query, tuple(params)).fetchall()

    output = []
    for date, close, score, confirmed, features_json in records:
        try:
            details = json.loads(features_json) if features_json else {}
        except (TypeError, ValueError):
            details = {}
        output.append({
            "date": date,
            "close": close,
            "score": score,
            "confirmed_bottom": bool(confirmed),
            "details": details,
        })
    return output
