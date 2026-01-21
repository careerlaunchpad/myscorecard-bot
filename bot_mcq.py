# =========================================================
# STEP 1 — CORE MCQ ENGINE (STABLE FOUNDATION)
# Exam → Topic → MCQ → Result
# =========================================================

import os, sqlite3, datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes
)
from telegram.error import BadRequest

# ================= CONFIG =================
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

conn.commit()

# ================= SAFE EDIT =================
async def safe_edit(q, text, kb=None):
    try:
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    except BadRequest:
        await q.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

# ================= KEYBOARDS =================
def exam_kb():
    cur.execute("SELECT DISTINCT exam FROM mcq")
    exams = [r[0] for r in cur.fetchall()]
    if not exams:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⚠️ No exams available", callback_data="noop")]
        ])
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(e, callback_data=f"exam_{e}")] for e in exams]
    )

def topic_kb(exam):
    cur.execute("SELECT DISTINCT topic FROM mcq WHERE exam=?", (exam,))
    topics = [r[0] for r in cur.fetchall()]
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t, callback_data=f"topic_{t}")] for t in topics] +
        [[InlineKeyboardButton("🏠 Home", callback_data="start")]]
    )

def answer_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("A", callback_data="ans_A"),
            InlineKeyboardButton("B", callback_data="ans_B")
        ],
        [
            InlineKeyboardButton("C", callback_data="ans_C"),
            InlineKeyboardButton("D", callback_data="ans_D")
        ],
        [InlineKeyboardButton("🏠 Home", callback_data="start")]
    ])

# ================= START =================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "👋 *Select Exam*",
        parse_mode="Markdown",
        reply_markup=exam_kb()
    )

# ================= EXAM =================
async def exam_select(update, ctx):
    q = update.callback_query
    await q.answer()
    ctx.user_data.clear()

    exam = q.data.replace("exam_", "")
    ctx.user_data["exam"] = exam

    await safe_edit(q, "*Select Topic*", topic_kb(exam))

# ================= TOPIC =================
async def topic_select(update, ctx):
    q = update.callback_query
    await q.answer()

    exam = ctx.user_data.get("exam")
    topic = q.data.replace("topic_", "")

    cur.execute(
        "SELECT COUNT(*) FROM mcq WHERE exam=? AND topic=?",
        (exam, topic)
    )
    total = cur.fetchone()[0]

    if total == 0:
        await safe_edit(
            q,
            "⚠️ No questions found",
            InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="start")]])
        )
        return

    ctx.user_data.update({
        "topic": topic,
        "asked": [],
        "score": 0,
        "q_no": 0,
        "total": total
    })

    await send_mcq(q, ctx)

# ================= SEND MCQ =================
async def send_mcq(q, ctx):
    exam = ctx.user_data["exam"]
    topic = ctx.user_data["topic"]
    asked = ctx.user_data["asked"]

    if asked:
        ph = ",".join("?" * len(asked))
        cur.execute(
            f"""
            SELECT * FROM mcq
            WHERE exam=? AND topic=? AND id NOT IN ({ph})
            ORDER BY RANDOM() LIMIT 1
            """,
            [exam, topic] + asked
        )
    else:
        cur.execute(
            "SELECT * FROM mcq WHERE exam=? AND topic=? ORDER BY RANDOM() LIMIT 1",
            (exam, topic)
        )

    m = cur.fetchone()
    if not m:
        await show_result(q, ctx)
        return

    ctx.user_data["current"] = m
    ctx.user_data["asked"].append(m[0])

    text = (
        f"❓ *Q{ctx.user_data['q_no']+1}/{ctx.user_data['total']}*\n\n"
        f"{m[3]}\n\n"
        f"A. {m[4]}\n"
        f"B. {m[5]}\n"
        f"C. {m[6]}\n"
        f"D. {m[7]}"
    )

    await safe_edit(q, text, answer_kb())

# ================= ANSWER =================
async def answer(update, ctx):
    q = update.callback_query
    await q.answer()

    if "current" not in ctx.user_data:
        await safe_edit(
            q,
            "⚠️ Session expired. Start again.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="start")]])
        )
        return

    m = ctx.user_data["current"]
    sel = q.data[-1]

    if sel == m[8]:
        ctx.user_data["score"] += 1

    ctx.user_data["q_no"] += 1
    await send_mcq(q, ctx)

# ================= RESULT =================
async def show_result(q, ctx):
    score = ctx.user_data["score"]
    total = ctx.user_data["q_no"]

    await safe_edit(
        q,
        f"🎯 *Test Completed*\n\nScore: *{score}/{total}*",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Home", callback_data="start")]
        ])
    )

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(start, "^start$"))
    app.add_handler(CallbackQueryHandler(exam_select, "^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select, "^topic_"))
    app.add_handler(CallbackQueryHandler(answer, "^ans_"))

    print("🤖 STEP 1 CORE BOT RUNNING")
    app.run_polling()

if __name__ == "__main__":
    main()
