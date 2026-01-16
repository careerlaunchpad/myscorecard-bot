import csv
import sqlite3

conn = sqlite3.connect("mcq.db")
cur = conn.cursor()

with open("mcq_upload.csv", "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        cur.execute("""
        INSERT INTO mcq
        (exam, topic, question, a, b, c, d, correct, explanation)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row["exam"],
            row["topic"],
            row["question"],
            row["a"],
            row["b"],
            row["c"],
            row["d"],
            row["correct"],
            row["explanation"]
        ))

conn.commit()
conn.close()

print("✅ CSV imported successfully")

