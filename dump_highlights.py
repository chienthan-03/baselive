import sqlite3
import json

def dump_highlights():
    conn = sqlite3.connect("c:\\Publish\\base-live\\base_live.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM highlights ORDER BY id DESC LIMIT 5")
    rows = cursor.fetchall()
    
    with open("c:\\Publish\\base-live\\dump.json", "w", encoding="utf-8") as f:
        json.dump([dict(row) for row in rows], f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    dump_highlights()
