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
ADMIN_IDS = [1977205811]  # 👈 अपनी numeric Telegram ID

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
def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("📘 MPPSC", callback_data="exam_MPPSC")],
        [InlineKeyboardButton("📕 UGC NET", callback_data="exam_NET")]
    ]
    await update.message.reply_text(
        "👋 Welcome to *MyScoreCard Bot*\n\nSelect Exam 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ================= START NEW =================
async def start_new_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    await start(update, context)

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

    topic = q.data.split("_")[1]
    exam = context.user_data["exam"]

    cur.execute("SELECT COUNT(*) FROM mcq WHERE exam=? AND topic=?", (exam, topic))
    total_q = cur.fetchone()[0]

    if total_q == 0:
        await q.edit_message_text("❌ No questions available.")
        return

    context.user_data.update({
        "topic": topic,
        "score": 0,
        "q_no": 0,
        "limit": min(10, total_q),
        "asked": [],
        "wrong_questions": []
    })

    await send_mcq(q, context)

# ================= SEND MCQ =================
async def send_mcq(q, context):
    exam = context.user_data["exam"]
    topic = context.user_data["topic"]
    asked = context.user_data["asked"]

    if asked:
        ph = ",".join("?" * len(asked))
        cur.execute(
            f"""SELECT * FROM mcq
                WHERE exam=? AND topic=? AND id NOT IN ({ph})
                ORDER BY RANDOM() LIMIT 1""",
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

    context.user_data["current"] = mcq
    context.user_data["asked"].append(mcq[0])

    kb = [
        [InlineKeyboardButton("A", callback_data="ans_A"),
         InlineKeyboardButton("B", callback_data="ans_B")],
        [InlineKeyboardButton("C", callback_data="ans_C"),
         InlineKeyboardButton("D", callback_data="ans_D")]
    ]

    await q.edit_message_text(
        f"❓ *Q{context.user_data['q_no']+1}/{context.user_data['limit']}*\n\n"
        f"{mcq[3]}\n\n"
        f"A. {mcq[4]}\nB. {mcq[5]}\nC. {mcq[6]}\nD. {mcq[7]}",
        parse_mode="Markdown",
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
        context.user_data["wrong_questions"].append(mcq)

    context.user_data["q_no"] += 1

    if context.user_data["q_no"] >= context.user_data["limit"]:
        await show_result(q, context)
        return

    await send_mcq(q, context)

# ================= RESULT =================
async def show_result(q, context):
    score = context.user_data["score"]
    total = context.user_data["q_no"]

    cur.execute(
        "INSERT INTO scores (user_id, exam, topic, score, total, test_date) VALUES (?,?,?,?,?,?)",
        (
            q.from_user.id,
            context.user_data["exam"],
            context.user_data["topic"],
            score,
            total,
            datetime.date.today().isoformat()
        )
    )
    conn.commit()

    buttons = [
        [InlineKeyboardButton("❌ Practice Wrong Only", callback_data="wrong_only")],
        [InlineKeyboardButton("📊 My Score", callback_data="myscore")],
        [InlineKeyboardButton("🔁 Start New Test", callback_data="start_new")]
    ]

    if not context.user_data["wrong_questions"]:
        buttons.pop(0)

    await q.edit_message_text(
        f"🎯 *Test Completed*\n\nScore: *{score}/{total}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ================= WRONG ONLY =================
async def wrong_only_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["wrong_index"] = 0
    await send_wrong(q, context)

async def send_wrong(q, context):
    idx = context.user_data["wrong_index"]
    wrongs = context.user_data["wrong_questions"]

    if idx >= len(wrongs):
        await q.edit_message_text(
            "✅ Wrong-Only Practice Completed 🎯",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Start New Test", callback_data="start_new")]
            ])
        )
        return

    w = wrongs[idx]
    await q.edit_message_text(
        f"❌ *Wrong Question {idx+1}/{len(wrongs)}*\n\n"
        f"{w[3]}\n\n"
        f"A. {w[4]}\nB. {w[5]}\nC. {w[6]}\nD. {w[7]}\n\n"
        f"✅ *Correct:* {w[8]}\n\n📘 {w[9]}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Next ▶", callback_data="wrong_next")]
        ])
    )

async def wrong_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["wrong_index"] += 1
    await send_wrong(q, context)

# ================= MY SCORE =================
async def myscore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cur.execute(
        "SELECT exam, topic, score, total, test_date FROM scores WHERE user_id=? ORDER BY id DESC LIMIT 5",
        (uid,)
    )
    rows = cur.fetchall()

    if not rows:
        await update.message.reply_text("❌ No score history.")
        return

    msg = "📊 *Your Scores*\n\n"
    for r in rows:
        msg += f"{r[0]} | {r[1]} → {r[2]}/{r[3]} ({r[4]})\n"

    await update.message.reply_text(
        msg,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 Start New Test", callback_data="start_new")]
        ])
    )

# ================= ADMIN =================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    cur.execute("SELECT COUNT(*) FROM mcq")
    mcqs = cur.fetchone()[0]
    await update.message.reply_text(f"🛠 Admin Panel\n\nMCQs: {mcqs}\n/upload – Upload Excel")

# ================= EXCEL UPLOAD =================
async def upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("📤 Send Excel (.xlsx)")

async def handle_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    doc: Document = update.message.document
    file = await doc.get_file()
    await file.download_to_drive("upload.xlsx")

    df = pd.read_excel("upload.xlsx")
    for _, r in df.iterrows():
        cur.execute(
            "INSERT INTO mcq VALUES (NULL,?,?,?,?,?,?,?,?,?)",
            (r.exam, r.topic, r.question, r.a, r.b, r.c, r.d, r.correct, r.explanation)
        )
    conn.commit()
    await update.message.reply_text(f"✅ {len(df)} MCQs uploaded")

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myscore", myscore))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("upload", upload))

    app.add_handler(MessageHandler(filters.Document.ALL, handle_excel))

    app.add_handler(CallbackQueryHandler(start_new_test, "^start_new$"))
    app.add_handler(CallbackQueryHandler(exam_select, "^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select, "^topic_"))
    app.add_handler(CallbackQueryHandler(answer, "^ans_"))
    app.add_handler(CallbackQueryHandler(wrong_only_start, "^wrong_only$"))
    app.add_handler(CallbackQueryHandler(wrong_next, "^wrong_next$"))

    print("🤖 Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
