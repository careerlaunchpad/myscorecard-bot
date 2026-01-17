import os
import sqlite3
import datetime
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

TOKEN = os.getenv("BOT_TOKEN")

# ================= DATABASE =================
conn = sqlite3.connect("mcq.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS mcq (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam TEXT,
    topic TEXT,
    question TEXT,
    a TEXT, b TEXT, c TEXT, d TEXT,
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

cur.execute("""
CREATE TABLE IF NOT EXISTS topic_stats (
    user_id INTEGER,
    topic TEXT,
    correct INTEGER,
    wrong INTEGER,
    PRIMARY KEY (user_id, topic)
)
""")
conn.commit()

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    kb = [
        [InlineKeyboardButton("🧠 Start Test", callback_data="exam_MPPSC")],
        [InlineKeyboardButton("📊 Topic Analytics", callback_data="topic_stats")]
    ]

    await update.message.reply_text(
        "👋 Welcome to MyScoreCard Bot\n\nChoose an option 👇",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ================= EXAM =================
async def exam_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    context.user_data.clear()
    context.user_data["exam"] = "MPPSC"

    kb = [
        [InlineKeyboardButton("History", callback_data="topic_History")],
        [InlineKeyboardButton("Polity", callback_data="topic_Polity")],
        [InlineKeyboardButton("🧠 Smart Adaptive Test", callback_data="adaptive")]
    ]

    await q.edit_message_text(
        "Select Topic 👇",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ================= TOPIC =================
async def topic_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    context.user_data.update({
        "topic": q.data.split("_")[1],
        "score": 0,
        "q_no": 0,
        "limit": 10,
        "asked": [],
        "attempts": []
    })

    await send_mcq(q, context)

# ================= SEND MCQ =================
async def send_mcq(q, context):
    asked = context.user_data["asked"]

    if asked:
        placeholders = ",".join("?" * len(asked))
        query = f"""
        SELECT * FROM mcq
        WHERE topic=? AND id NOT IN ({placeholders})
        ORDER BY RANDOM() LIMIT 1
        """
        params = [context.user_data["topic"]] + asked
    else:
        query = "SELECT * FROM mcq WHERE topic=? ORDER BY RANDOM() LIMIT 1"
        params = [context.user_data["topic"]]

    cur.execute(query, params)
    mcq = cur.fetchone()

    if not mcq:
        await finish_test(q, context)
        return

    context.user_data["asked"].append(mcq[0])
    context.user_data["correct"] = mcq[8]
    context.user_data["question"] = mcq

    kb = [
        [InlineKeyboardButton("A", callback_data="A"),
         InlineKeyboardButton("B", callback_data="B")],
        [InlineKeyboardButton("C", callback_data="C"),
         InlineKeyboardButton("D", callback_data="D")]
    ]

    await q.edit_message_text(
        f"Q{context.user_data['q_no']+1}. {mcq[3]}\n\n"
        f"A. {mcq[4]}\nB. {mcq[5]}\nC. {mcq[6]}\nD. {mcq[7]}",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ================= ANSWER =================
async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    selected = q.data
    mcq = context.user_data["question"]
    topic = mcq[2]
    uid = q.from_user.id

    correct = selected == mcq[8]

    if correct:
        context.user_data["score"] += 1

    # topic stats
    cur.execute(
        "SELECT correct, wrong FROM topic_stats WHERE user_id=? AND topic=?",
        (uid, topic)
    )
    row = cur.fetchone()

    if row:
        c, w = row
        c += 1 if correct else 0
        w += 0 if correct else 1
        cur.execute(
            "UPDATE topic_stats SET correct=?, wrong=? WHERE user_id=? AND topic=?",
            (c, w, uid, topic)
        )
    else:
        cur.execute(
            "INSERT INTO topic_stats VALUES (?,?,?,?)",
            (uid, topic, 1 if correct else 0, 0 if correct else 1)
        )

    conn.commit()

    context.user_data["q_no"] += 1

    if context.user_data["q_no"] >= context.user_data["limit"]:
        await finish_test(q, context)
        return

    await send_mcq(q, context)

# ================= FINISH =================
async def finish_test(q, context):
    score = context.user_data["score"]
    total = context.user_data["q_no"]

    await q.edit_message_text(
        f"✅ Test Completed\n\nScore: {score}/{total}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Topic Analytics", callback_data="topic_stats")],
            [InlineKeyboardButton("🔁 New Test", callback_data="exam_MPPSC")]
        ])
    )

# ================= TOPIC ANALYTICS =================
async def topic_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    cur.execute(
        "SELECT topic, correct, wrong FROM topic_stats WHERE user_id=?",
        (uid,)
    )
    rows = cur.fetchall()

    if not rows:
        await q.edit_message_text("No data available yet.")
        return

    msg = "📊 Topic-Wise Performance\n\n"
    for t, c, w in rows:
        total = c + w
        acc = round((c / total) * 100, 2)
        msg += f"{t} → {acc}% ({c}/{total})\n"

    await q.edit_message_text(msg)

# ================= ADAPTIVE TEST =================
async def adaptive_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    cur.execute(
        "SELECT topic, correct, wrong FROM topic_stats WHERE user_id=?",
        (uid,)
    )
    rows = cur.fetchall()

    if not rows:
        await q.edit_message_text("Attempt some tests first.")
        return

    weighted = []
    for t, c, w in rows:
        acc = c / max(1, (c + w))
        weight = 3 if acc < 0.5 else 2 if acc < 0.75 else 1
        weighted.extend([t] * weight)

    context.user_data.update({
        "topic": weighted[0],
        "score": 0,
        "q_no": 0,
        "limit": 10,
        "asked": [],
        "attempts": []
    })

    await send_mcq(q, context)

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(exam_select, "^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select, "^topic_"))
    app.add_handler(CallbackQueryHandler(answer, "^[ABCD]$"))
    app.add_handler(CallbackQueryHandler(topic_stats, "^topic_stats$"))
    app.add_handler(CallbackQueryHandler(adaptive_start, "^adaptive$"))

    print("🤖 Bot Running with Analytics + Adaptive Test")
    app.run_polling()

if __name__ == "__main__":
    main()
