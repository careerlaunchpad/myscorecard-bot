# ================= IMPORTS =================
import os, sqlite3, datetime, unicodedata
import pandas as pd

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from telegram.error import BadRequest

# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [1977205811]
TEST_TIME_SECONDS = 600  # ⏱ 10 minutes

# ================= DATABASE =================
conn = sqlite3.connect("mcq.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS mcq (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam TEXT, topic TEXT,
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
    exam TEXT, topic TEXT,
    score INTEGER,
    total INTEGER,
    test_date TEXT
)
""")
conn.commit()

# ================= SAFE HELPERS =================
async def safe_edit_or_send(q, text, reply_markup=None):
    try:
        await q.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return
        try:
            await q.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except:
            pass

def safe_hindi(t):
    return unicodedata.normalize("NFKC", str(t)) if t else ""

def is_admin(uid):
    return uid in ADMIN_IDS

# ================= UI HELPERS =================
def home_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="start_new")],
        [InlineKeyboardButton("📊 My Score", callback_data="myscore")],
        [InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result")]
    ])

def exam_kb():
    cur.execute("SELECT DISTINCT exam FROM mcq")
    rows = cur.fetchall()
    return InlineKeyboardMarkup([[InlineKeyboardButton(r[0], callback_data=f"exam_{r[0]}")] for r in rows])

def topic_kb(exam):
    cur.execute("SELECT DISTINCT topic FROM mcq WHERE exam=?", (exam,))
    rows = cur.fetchall()
    kb = [[InlineKeyboardButton(r[0], callback_data=f"topic_{r[0]}")] for r in rows]
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="start_new")])
    return InlineKeyboardMarkup(kb)

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 *Welcome to MyScoreCard Bot*\n\nSelect Exam 👇",
        parse_mode="Markdown",
        reply_markup=exam_kb()
    )

async def start_new(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    await safe_edit_or_send(q, "👋 *Welcome*\n\nSelect Exam 👇", exam_kb())

# ================= TIMER =================
async def time_up(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    q = job.data["query"]
    ctx = job.data["context"]
    if ctx.user_data.get("test_running"):
        ctx.user_data["test_running"] = False
        await safe_edit_or_send(
            q,
            "⏱ *Time Up! Test auto-submitted.*",
            home_kb()
        )
        await show_result(q, ctx)

# ================= EXAM / TOPIC =================
async def exam_select(update, context):
    q = update.callback_query
    await q.answer()
    exam = q.data.replace("exam_", "")
    context.user_data.clear()
    context.user_data["exam"] = exam
    await safe_edit_or_send(q, "Choose Topic 👇", topic_kb(exam))

async def topic_select(update, context):
    q = update.callback_query
    await q.answer()

    exam = context.user_data.get("exam")
    topic = q.data.replace("topic_", "")

    cur.execute("SELECT COUNT(*) FROM mcq WHERE exam=? AND topic=?", (exam, topic))
    total = cur.fetchone()[0]
    if total == 0:
        await safe_edit_or_send(q, "❌ No questions", home_kb())
        return

    context.user_data.update({
        "topic": topic,
        "score": 0,
        "q_no": 0,
        "limit": total,
        "asked": [],
        "wrong": [],
        "attempts": [],
        "test_running": True
    })

    # ⏱ start timer
    context.job_queue.run_once(
        time_up,
        TEST_TIME_SECONDS,
        data={"query": q, "context": context}
    )

    await send_mcq(q, context)

# ================= MCQ FLOW =================
async def send_mcq(q, context):
    if not context.user_data.get("test_running"):
        return

    exam, topic = context.user_data["exam"], context.user_data["topic"]
    asked = context.user_data["asked"]

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

    await safe_edit_or_send(
        q,
        f"❓ *Q{context.user_data['q_no']+1}/{context.user_data['limit']}*\n\n"
        f"{mcq[3]}\n\nA. {mcq[4]}\nB. {mcq[5]}\nC. {mcq[6]}\nD. {mcq[7]}",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("A", callback_data="ans_A"),
             InlineKeyboardButton("B", callback_data="ans_B")],
            [InlineKeyboardButton("C", callback_data="ans_C"),
             InlineKeyboardButton("D", callback_data="ans_D")]
        ])
    )

async def answer(update, context):
    q = update.callback_query
    await q.answer()

    if not context.user_data.get("test_running"):
        return

    mcq = context.user_data["current"]
    sel = q.data.split("_")[1]

    context.user_data["attempts"].append({
        "question": mcq[3],
        "correct": mcq[8],
        "explanation": mcq[9]
    })

    if sel == mcq[8]:
        context.user_data["score"] += 1
    else:
        context.user_data["wrong"].append(mcq)

    context.user_data["q_no"] += 1
    if context.user_data["q_no"] >= context.user_data["limit"]:
        await show_result(q, context)
    else:
        await send_mcq(q, context)

# ================= RESULT =================
async def show_result(q, context):
    context.user_data["test_running"] = False

    cur.execute(
        "INSERT INTO scores VALUES(NULL,?,?,?,?,?,?)",
        (
            q.from_user.id,
            context.user_data["exam"],
            context.user_data["topic"],
            context.user_data["score"],
            context.user_data["q_no"],
            datetime.date.today().isoformat()
        )
    )
    conn.commit()

    await safe_edit_or_send(
        q,
        f"🎯 *Test Completed*\n\nScore: *{context.user_data['score']}/{context.user_data['q_no']}*",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Wrong Practice", callback_data="wrong_only")],
            [InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result")],
            [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )

# ================= LEADERBOARD =================
async def leaderboard(update, context):
    send = update.message.reply_text if update.message else update.callback_query.edit_message_text

    cur.execute("""
        SELECT user_id, MAX(score) as best
        FROM scores
        GROUP BY user_id
        ORDER BY best DESC
        LIMIT 10
    """)
    rows = cur.fetchall()

    if not rows:
        await send("No data yet")
        return

    msg = "🏆 *Top Rankers*\n\n"
    for i, r in enumerate(rows, 1):
        msg += f"{i}. User {r[0]} → {r[1]}\n"

    await send(msg, parse_mode="Markdown", reply_markup=home_kb())

# ================= ADMIN DELETE MCQ =================
async def admin(update, context):
    if not is_admin(update.effective_user.id):
        return

    cur.execute("SELECT id, exam, topic FROM mcq ORDER BY id DESC LIMIT 10")
    rows = cur.fetchall()

    msg = "🛠 *ADMIN – Recent MCQs*\n\n"
    kb = []
    for r in rows:
        msg += f"ID {r[0]} | {r[1]} – {r[2]}\n"
        kb.append([InlineKeyboardButton(f"❌ Delete {r[0]}", callback_data=f"del_{r[0]}")])

    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def delete_mcq(update, context):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return

    mcq_id = int(q.data.replace("del_", ""))
    cur.execute("DELETE FROM mcq WHERE id=?", (mcq_id,))
    conn.commit()

    await safe_edit_or_send(q, f"✅ MCQ {mcq_id} deleted", home_kb())

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("leaderboard", leaderboard))

    app.add_handler(CallbackQueryHandler(start_new, "^start_new$"))
    app.add_handler(CallbackQueryHandler(exam_select, "^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select, "^topic_"))
    app.add_handler(CallbackQueryHandler(answer, "^ans_"))
    app.add_handler(CallbackQueryHandler(leaderboard, "^leaderboard$"))
    app.add_handler(CallbackQueryHandler(delete_mcq, "^del_"))

    print("🤖 Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
