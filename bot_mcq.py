import os
import sqlite3
import datetime
import pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Document
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [1977205811]  # <-- apni Telegram ID yahan daalo

# ================= DATABASE =================
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

# ================= HELPERS =================
def is_admin(user_id):
    return user_id in ADMIN_IDS

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("📘 MPPSC", callback_data="exam_MPPSC")],
        [InlineKeyboardButton("📕 UGC NET", callback_data="exam_NET")]
    ]
    await update.message.reply_text(
        "👋 Welcome to MyScoreCard Bot 🎯\n\nSelect Exam 👇",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ================= EXAM =================
async def exam_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    context.user_data["exam"] = q.data.split("_")[1]

    kb = [
        [InlineKeyboardButton("History", callback_data="topic_History")],
        [InlineKeyboardButton("Polity", callback_data="topic_Polity")]
    ]
    await q.edit_message_text("Choose Topic 👇", reply_markup=InlineKeyboardMarkup(kb))

# ================= TOPIC =================
async def topic_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    context.user_data["topic"] = q.data.split("_")[1]
    context.user_data.update({
        "score": 0,
        "q_no": 0,
        "limit": 10,
        "asked": [],
        "attempts": [],
        "wrong": []
    })
    await send_mcq(q, context)

# ================= SEND MCQ =================
async def send_mcq(q, context):
    asked = context.user_data["asked"]
    exam = context.user_data["exam"]
    topic = context.user_data["topic"]

    if asked:
        ph = ",".join("?" * len(asked))
        cur.execute(
            f"SELECT * FROM mcq WHERE exam=? AND topic=? AND id NOT IN ({ph}) ORDER BY RANDOM() LIMIT 1",
            [exam, topic] + asked
        )
    else:
        cur.execute(
            "SELECT * FROM mcq WHERE exam=? AND topic=? ORDER BY RANDOM() LIMIT 1",
            (exam, topic)
        )

    mcq = cur.fetchone()
    if not mcq:
        await show_result(q, context)
        return

    context.user_data["asked"].append(mcq[0])
    context.user_data["current"] = mcq

    kb = [
        [InlineKeyboardButton("A", callback_data="ans_A"),
         InlineKeyboardButton("B", callback_data="ans_B")],
        [InlineKeyboardButton("C", callback_data="ans_C"),
         InlineKeyboardButton("D", callback_data="ans_D")]
    ]

    await q.edit_message_text(
        f"❓ Q{context.user_data['q_no']+1}\n{mcq[3]}\n\n"
        f"A. {mcq[4]}\nB. {mcq[5]}\nC. {mcq[6]}\nD. {mcq[7]}",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ================= ANSWER =================
async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    selected = q.data.split("_")[1]
    mcq = context.user_data["current"]

    if selected == mcq[8]:
        context.user_data["score"] += 1
    else:
        context.user_data["wrong"].append(mcq)

    context.user_data["q_no"] += 1

    if context.user_data["q_no"] >= context.user_data["limit"]:
        await show_result(q, context)
        return

    await send_mcq(q, context)

# ================= RESULT =================
async def show_result(q, context):
    s = context.user_data["score"]
    t = context.user_data["q_no"]

    cur.execute(
        "INSERT INTO scores VALUES (NULL,?,?,?,?,?)",
        (
            q.from_user.id,
            context.user_data["exam"],
            context.user_data["topic"],
            s,
            t,
            datetime.date.today().isoformat()
        )
    )
    conn.commit()

    await q.edit_message_text(
        f"🎯 Test Completed\nScore: {s}/{t}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 New Test", callback_data="start_new")],
            [InlineKeyboardButton("📊 My Score", callback_data="myscore")]
        ])
    )

# ================= ADMIN DASHBOARD =================
async def admin_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    cur.execute("SELECT COUNT(*) FROM mcq")
    total_mcq = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM scores")
    total_tests = cur.fetchone()[0]

    cur.execute("SELECT COUNT(DISTINCT user_id) FROM scores")
    users = cur.fetchone()[0]

    msg = (
        "🛠 ADMIN DASHBOARD\n\n"
        f"📚 Total MCQs: {total_mcq}\n"
        f"👤 Active Users: {users}\n"
        f"📝 Tests Conducted: {total_tests}\n\n"
        "📤 Upload MCQs via Excel using /upload"
    )
    await update.message.reply_text(msg)

# ================= EXCEL UPLOAD =================
async def upload_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    await update.message.reply_text(
        "📤 Send Excel file (.xlsx)\n\n"
        "Columns must be:\n"
        "exam, topic, question, a, b, c, d, correct, explanation"
    )

async def handle_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    doc: Document = update.message.document
    file = await doc.get_file()
    path = "upload.xlsx"
    await file.download_to_drive(path)

    df = pd.read_excel(path)

    for _, r in df.iterrows():
        cur.execute(
            "INSERT INTO mcq VALUES (NULL,?,?,?,?,?,?,?,?,?)",
            (
                r["exam"], r["topic"], r["question"],
                r["a"], r["b"], r["c"], r["d"],
                r["correct"], r["explanation"]
            )
        )
    conn.commit()

    await update.message.reply_text(f"✅ {len(df)} MCQs uploaded successfully!")

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_dashboard))
    app.add_handler(CommandHandler("upload", upload_excel))

    app.add_handler(MessageHandler(filters.Document.ALL, handle_excel))

    app.add_handler(CallbackQueryHandler(exam_select, "^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select, "^topic_"))
    app.add_handler(CallbackQueryHandler(answer, "^ans_"))
    app.add_handler(CallbackQueryHandler(start, "^start_new$"))

    print("🤖 Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()

