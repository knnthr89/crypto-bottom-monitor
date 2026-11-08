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
