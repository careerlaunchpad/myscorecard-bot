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
TEST_TIME = 600  # 10 minutes

# ================= DATABASE =================
conn = sqlite3.connect("mcq.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS mcq (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 exam TEXT, topic TEXT,
 question TEXT,
 a TEXT,b TEXT,c TEXT,d TEXT,
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
async def safe_edit_or_send(q, text, kb=None):
    try:
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return
        try:
            await q.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
        except:
            pass

def safe_hindi(t): return unicodedata.normalize("NFKC", str(t)) if t else ""
def is_admin(uid): return uid in ADMIN_IDS

# ================= UI =================
def home_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="start_new")],
        [InlineKeyboardButton("📊 My Score", callback_data="myscore")]
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
        "👋 *Welcome*\n\nSelect Exam 👇",
        parse_mode="Markdown",
        reply_markup=exam_kb()
    )

async def start_new(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    await safe_edit_or_send(q, "Select Exam 👇", exam_kb())

# ================= TIMER =================
async def time_up(ctx: ContextTypes.DEFAULT_TYPE):
    data = ctx.job.data
    q = data["q"]
    context = data["context"]
    if context.user_data.get("running"):
        context.user_data["running"] = False
        await show_result(q, context)

# ================= EXAM / TOPIC =================
async def exam_select(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    context.user_data["exam"] = q.data.replace("exam_", "")
    await safe_edit_or_send(q, "Choose Topic 👇", topic_kb(context.user_data["exam"]))

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
        "review": [],
        "running": True
    })

    context.job_queue.run_once(
        time_up, TEST_TIME,
        data={"q": q, "context": context}
    )

    await send_mcq(q, context)

# ================= MCQ =================
async def send_mcq(q, context):
    if not context.user_data.get("running"):
        return

    exam = context.user_data["exam"]
    topic = context.user_data["topic"]
    asked = context.user_data["asked"]

    if asked:
        ph = ",".join("?" * len(asked))
        cur.execute(
            f"SELECT * FROM mcq WHERE exam=? AND topic=? AND id NOT IN ({ph}) ORDER BY RANDOM() LIMIT 1",
            [exam, topic] + asked
        )
    else:
        cur.execute("SELECT * FROM mcq WHERE exam=? AND topic=? ORDER BY RANDOM() LIMIT 1", (exam, topic))

    mcq = cur.fetchone()
    if not mcq:
        await show_result(q, context)
        return

    context.user_data["current"] = mcq
    context.user_data["asked"].append(mcq[0])

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
    mcq = context.user_data["current"]
    sel = q.data.split("_")[1]

    correct = mcq[8]
    is_right = sel == correct

    context.user_data["review"].append({
        "q": mcq[3], "sel": sel, "correct": correct,
        "exp": mcq[9]
    })

    if is_right:
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
    context.user_data["running"] = False

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
            [InlineKeyboardButton("📖 Review All Questions", callback_data="review_all")],
            [InlineKeyboardButton("❌ Wrong Only", callback_data="wrong_only")],
            [InlineKeyboardButton("🏆 Subject Leaderboard", callback_data="sub_leader")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )

# ================= REVIEW =================
async def review_all(update, context):
    q = update.callback_query
    await q.answer()

    text = "📖 *Review*\n\n"
    for i, r in enumerate(context.user_data["review"], 1):
        text += (
            f"*Q{i}* {r['q']}\n"
            f"Your: {r['sel']} | Correct: {r['correct']}\n"
            f"{r['exp']}\n\n"
        )

    await safe_edit_or_send(q, text, InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back", callback_data="start_new")]
    ]))

# ================= SUBJECT LEADERBOARD =================
async def sub_leader(update, context):
    q = update.callback_query
    await q.answer()

    exam = context.user_data["exam"]
    topic = context.user_data["topic"]

    cur.execute("""
    SELECT user_id, MAX(score) FROM scores
    WHERE exam=? AND topic=?
    GROUP BY user_id
    ORDER BY MAX(score) DESC LIMIT 10
    """, (exam, topic))

    rows = cur.fetchall()
    msg = f"🏆 *{exam} – {topic}*\n\n"
    for i, r in enumerate(rows, 1):
        msg += f"{i}. User {r[0]} → {r[1]}\n"

    await safe_edit_or_send(q, msg, InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back", callback_data="start_new")]
    ]))

# ================= ADMIN EDIT / DELETE =================
async def admin(update, context):
    if not is_admin(update.effective_user.id):
        return

    cur.execute("SELECT id, question FROM mcq ORDER BY id DESC LIMIT 10")
    rows = cur.fetchall()

    kb = []
    msg = "🛠 *Admin MCQs*\n\n"
    for r in rows:
        msg += f"ID {r[0]}: {r[1][:30]}...\n"
        kb.append([
            InlineKeyboardButton("✏️ Edit", callback_data=f"edit_{r[0]}"),
            InlineKeyboardButton("❌ Delete", callback_data=f"del_{r[0]}")
        ])

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

    app.add_handler(CallbackQueryHandler(start_new, "^start_new$"))
    app.add_handler(CallbackQueryHandler(exam_select, "^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select, "^topic_"))
    app.add_handler(CallbackQueryHandler(answer, "^ans_"))
    app.add_handler(CallbackQueryHandler(review_all, "^review_all$"))
    app.add_handler(CallbackQueryHandler(sub_leader, "^sub_leader$"))
    app.add_handler(CallbackQueryHandler(delete_mcq, "^del_"))

    print("🤖 Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
