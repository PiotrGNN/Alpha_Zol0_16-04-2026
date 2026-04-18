# MemoryCore.py – zapis decyzji AI z kontekstem i wynikiem
import json
import logging
import sqlite3
from datetime import datetime, timezone


class MemoryCore:
    def __init__(self, db_path="memory_core.db", use_sqlite=True):
        self.use_sqlite = use_sqlite
        self.db_path = db_path
        if use_sqlite:
            self.conn = sqlite3.connect(db_path)
            self._init_db()
        else:
            self.memory = []

    def _init_db(self):
        c = self.conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            input TEXT,
            result TEXT,
            timestamp TEXT,
            metrics TEXT
        )""")
        self.conn.commit()

    def save_decision(self, input_data, result, metrics):
        timestamp = datetime.now(timezone.utc).isoformat()
        if self.use_sqlite:
            c = self.conn.cursor()
            c.execute(
                """INSERT INTO decisions (input, result, timestamp, metrics)
                   VALUES (?, ?, ?, ?)""",
                (
                    json.dumps(input_data),
                    json.dumps(result),
                    timestamp,
                    json.dumps(metrics),
                ),
            )
            self.conn.commit()
            logging.info(
                "MemoryCore: decision saved to SQLite at %s",
                timestamp,
            )
        else:
            entry = {
                "input": input_data,
                "result": result,
                "timestamp": timestamp,
                "metrics": metrics,
            }
            self.memory.append(entry)
            logging.info("MemoryCore: decision saved to JSON at %s", timestamp)

    def get_decisions(self, limit=100):
        if self.use_sqlite:
            c = self.conn.cursor()
            c.execute(
                "SELECT input, result, timestamp, metrics "
                "FROM decisions ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            rows = c.fetchall()
            return [
                {
                    "input": json.loads(row[0]),
                    "result": json.loads(row[1]),
                    "timestamp": row[2],
                    "metrics": json.loads(row[3]),
                }
                for row in rows
            ]
        else:
            return self.memory[-limit:]
