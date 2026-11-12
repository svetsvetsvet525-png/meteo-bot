"""Разовая настройка чата: python _setup_chat.py <chat_id> <district> <shift> <grade>"""
import sqlite3
import sys

conn = sqlite3.connect("data/bot.db")
chat_id, district, shift, grade = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
conn.execute(
    "UPDATE chats SET district=?, shift=?, grade=? WHERE chat_id=?",
    (district, shift, grade, int(chat_id)),
)
conn.commit()
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT * FROM chats").fetchall()
import json
print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=1))
