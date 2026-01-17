import os
import sqlite3
import datetime
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Document
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [1977205811]   # 👈 अपनी Telegram ID यहाँ डालें

# ---------- DATABASE ----------
conn = sqlite3.connect("mcq.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS mcq (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam TEXT,
    topic TEXT,
    question TEXT,
    a TEXT,
    b TEXT,
    c TEXT,
    d TEXT,
    correct TEXT,
    explanation TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    exam TEXT,
    topic TEXT,
    score INTEGER,
    total INTEGER,
    test_date TEXT
)
""")
conn.commit()

# ---------- START ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("📘 MPPSC", callback_data="exam_MPPSC")],
        [InlineKeyboardButton("📗 UGC NET", callback_data="exam_NET")],
        [InlineKeyboardButton("📊 My Score", callback_data="go_myscore")]
    ]
    await update.message.reply_text(
        "👋 Welcome to MyScoreCard Bot 🎯\n\nSelect Exam 👇",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ---------- ADMIN DASHBOARD ----------
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not admin.")
        return

    cur.execute("SELECT COUNT(*) FROM mcq")
    total_mcq = cur.fetchone()[0]

    cur.execute("SELECT COUNT(DISTINCT user_id) FROM scores")
    users = cur.fetchone()[0]

    await update.message.reply_text(
        f"👨‍💼 ADMIN DASHBOARD\n\n"
        f"📄 Total MCQs: {total_mcq}\n"
        f"👥 Active Users: {users}\n\n"
        f"📂 Upload MCQs: Send Excel file"
    )

# ---------- EXCEL UPLOAD ----------
async def excel_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    doc: Document = update.message.document
    if not doc.file_name.endswith(".xlsx"):
        await update.message.reply_text("❌ Please upload .xlsx file only")
        return

    file = await doc.get_file()
    path = f"/tmp/{doc.file_name}"
    await file.download_to_drive(path)

    try:
        df = pd.read_excel(path)
    except Exception as e:
        await update.message.reply_text("❌ Invalid Excel file")
        return

    required_cols = ["exam","topic","question","a","b","c","d","correct","explanation"]
    if not all(col in df.columns for col in required_cols):
        await update.message.reply_text("❌ Excel columns mismatch")
        return

    inserted = 0
    for _, r in df.iterrows():
        cur.execute("""
        INSERT INTO mcq (exam,topic,question,a,b,c,d,correct,explanation)
        VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            str(r.exam).strip(),
            str(r.topic).strip(),
            str(r.question),
            str(r.a), str(r.b), str(r.c), str(r.d),
            str(r.correct).strip().upper(),
            str(r.explanation)
        ))
        inserted += 1

    conn.commit()
    await update.message.reply_text(f"✅ {inserted} MCQs uploaded successfully!")

# ---------- MY SCORE ----------
async def myscore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cur.execute(
        "SELECT exam,topic,score,total,test_date FROM scores WHERE user_id=? ORDER BY id DESC LIMIT 5",
        (update.effective_user.id,)
    )
    rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("❌ No history found.")
        return

    msg = "📊 My Score History\n\n"
    for r in rows:
        msg += f"{r[0]} | {r[1]} → {r[2]}/{r[3]} ({r[4]})\n"

    await update.message.reply_text(msg)

# ---------- MAIN ----------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("myscore", myscore))

    app.add_handler(
        MessageHandler(filters.Document.FileExtension("xlsx"), excel_upload)
    )

    print("🤖 Bot Running with Admin + Excel Upload")
    app.run_polling()

if __name__ == "__main__":
    main()

