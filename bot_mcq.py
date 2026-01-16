import os
import sqlite3
import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = "@MyScoreCard_bot"

# ---------- DATABASE ----------
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
conn.commit()

# ---------- START ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("MPPSC", callback_data="exam_MPPSC")],
        [InlineKeyboardButton("UGC NET", callback_data="exam_NET")]
    ]
    await update.message.reply_text(
        "👋 Welcome to MyScoreCard Bot\n\nSelect Exam 👇",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ---------- EXAM ----------
async def exam_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    context.user_data.clear()
    context.user_data["exam"] = q.data.split("_")[1]

    kb = [
        [InlineKeyboardButton("History", callback_data="topic_History")],
        [InlineKeyboardButton("Polity", callback_data="topic_Polity")]
    ]
    await q.edit_message_text(
        f"📘 Exam: {context.user_data['exam']}\n\nChoose Topic 👇",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ---------- TOPIC ----------
async def topic_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    context.user_data.update({
        "topic": q.data.split("_")[1],
        "score": 0,
        "q_no": 0,
        "attempts": [],
        "asked": []
    })

    cur.execute(
        "SELECT COUNT(*) FROM mcq WHERE exam=? AND topic=?",
        (context.user_data["exam"], context.user_data["topic"])
    )
    context.user_data["limit"] = min(10, cur.fetchone()[0])

    await send_mcq(q, context)

# ---------- SEND MCQ ----------
async def send_mcq(q, context):
    asked = context.user_data["asked"]

    sql = "SELECT * FROM mcq WHERE exam=? AND topic=?"
    params = [context.user_data["exam"], context.user_data["topic"]]

    if asked:
        sql += f" AND id NOT IN ({','.join('?'*len(asked))})"
        params += asked

    sql += " ORDER BY RANDOM() LIMIT 1"

    cur.execute(sql, params)
    mcq = cur.fetchone()

    # ✅ FIX: when questions are over
    if not mcq:
        await finish_test(q, context)
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

# ---------- ANSWER ----------
async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    selected = q.data.split("_")[1]
    mcq = context.user_data["current"]

    context.user_data["attempts"].append({
        "question": mcq[3],
        "options": {"A": mcq[4], "B": mcq[5], "C": mcq[6], "D": mcq[7]},
        "selected": selected,
        "correct": mcq[8],
        "explanation": mcq[9]
    })

    if selected == mcq[8]:
        context.user_data["score"] += 1

    context.user_data["q_no"] += 1

    if context.user_data["q_no"] >= context.user_data["limit"]:
        await finish_test(q, context)
        return

    await send_mcq(q, context)

# ---------- FINISH TEST ----------
async def finish_test(q, context):
    score = context.user_data["score"]
    total = context.user_data["q_no"]

    cur.execute(
        "INSERT INTO scores VALUES (NULL,?,?,?,?,?)",
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

    acc = round((score / total) * 100, 2)

    await q.edit_message_text(
        f"🎯 Test Completed ✅\n\n"
        f"Score: {score}/{total}\n"
        f"Accuracy: {acc}%\n\n"
        f"👇 Review your answers",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Review Answers", callback_data="review_0")]
        ])
    )

# ---------- REVIEW ----------
async def review_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    idx = int(q.data.split("_")[1])
    attempts = context.user_data["attempts"]

    if idx >= len(attempts):
        await q.edit_message_text(
            "✅ Review Completed 🎉\n\nWhat would you like to do next?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Start New Test", callback_data="start_new")],
                [InlineKeyboardButton("📊 My Score", callback_data="go_score")],
                [InlineKeyboardButton("📈 Performance", callback_data="go_perf")]
            ])
        )
        return

    a = attempts[idx]

    await q.edit_message_text(
        f"❓ Q{idx+1}\n{a['question']}\n\n"
        f"Your Answer: {a['selected']}\n"
        f"Correct Answer: {a['correct']}\n\n"
        f"{a['explanation']}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Next ▶", callback_data=f"review_{idx+1}")]
        ])
    )

# ---------- NAVIGATION ----------
async def start_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()

    kb = [
        [InlineKeyboardButton("MPPSC", callback_data="exam_MPPSC")],
        [InlineKeyboardButton("UGC NET", callback_data="exam_NET")]
    ]
    await q.edit_message_text("🔁 Start New Test\n\nSelect Exam 👇",
                              reply_markup=InlineKeyboardMarkup(kb))

async def go_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    cur.execute(
        "SELECT exam, topic, score, total, test_date "
        "FROM scores WHERE user_id=? ORDER BY id DESC LIMIT 5",
        (q.from_user.id,)
    )
    rows = cur.fetchall()

    if not rows:
        await q.edit_message_text("❌ No score history found.")
        return

    msg = "📊 My Scores\n\n"
    for r in rows:
        msg += f"{r[0]} | {r[1]} → {r[2]}/{r[3]} ({r[4]})\n"

    await q.edit_message_text(msg)

async def go_perf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    cur.execute(
        "SELECT score, total FROM scores "
        "WHERE user_id=? ORDER BY id DESC LIMIT 7",
        (q.from_user.id,)
    )
    rows = cur.fetchall()

    if not rows:
        await q.edit_message_text("❌ No performance data.")
        return

    msg = "📈 Performance Trend\n\n"
    for i, r in enumerate(rows[::-1], 1):
        bar = "█" * int((r[0] / r[1]) * 10)
        msg += f"Test {i}: {bar} {r[0]}/{r[1]}\n"

    await q.edit_message_text(msg)

# ---------- MAIN ----------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(exam_select, "^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select, "^topic_"))
    app.add_handler(CallbackQueryHandler(answer, "^ans_"))
    app.add_handler(CallbackQueryHandler(review_answers, "^review_"))
    app.add_handler(CallbackQueryHandler(start_new, "^start_new$"))
    app.add_handler(CallbackQueryHandler(go_score, "^go_score$"))
    app.add_handler(CallbackQueryHandler(go_perf, "^go_perf$"))

    print("🤖 MyScoreCard Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()

