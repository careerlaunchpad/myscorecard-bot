import csv
import sqlite3

DB_NAME = "mcq.db"
CSV_FILE = "mcq_upload.csv"

conn = sqlite3.connect(DB_NAME)
cur = conn.cursor()

with open(CSV_FILE, "r", encoding="utf-8") as file:
    reader = csv.DictReader(file)

    count = 0
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
        count += 1

conn.commit()
conn.close()

print(f"✅ {count} MCQs successfully uploaded!")
