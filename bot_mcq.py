import os
import sqlite3
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = "@MyScoreCard_bot"  # 🔁 change this

# ---------- DATABASE ----------
conn = sqlite3.connect("mcq.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    is_paid INTEGER DEFAULT 0,
    expiry TEXT
)
""")

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

# ---------- HELPERS ----------
def add_user(user_id):
    cur.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()

def is_paid(user_id):
    cur.execute("SELECT is_paid, expiry FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if not row or row[0] == 0:
        return False
    return datetime.datetime.strptime(row[1], "%Y-%m-%d") >= datetime.datetime.now()

# ---------- START ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_user(update.effective_user.id)

    kb = [
        [InlineKeyboardButton("MPPSC", callback_data="exam_MPPSC")],
        [InlineKeyboardButton("UGC NET", callback_data="exam_NET")]
    ]
    await update.message.reply_text(
        "👋 Welcome to MyScoreCard Bot 🎯\nSelect Exam 👇",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ---------- EXAM ----------
async def exam_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    exam = q.data.split("_")[1]
    context.user_data["exam"] = exam

    kb = [
        [InlineKeyboardButton("History", callback_data="topic_History")],
        [InlineKeyboardButton("Polity", callback_data="topic_Polity")]
    ]
    await q.edit_message_text(
        f"📘 Exam: {exam}\nChoose Topic 👇",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ---------- TOPIC ----------
async def topic_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    context.user_data["topic"] = q.data.split("_")[1]
    context.user_data["score"] = 0
    context.user_data["q_no"] = 0
    context.user_data["limit"] = 50 if is_paid(q.from_user.id) else 10
    context.user_data["asked_questions"] = []

    # 🔽 LIMIT SAFETY (NO INDENT ISSUE HERE)
    cur.execute(
        "SELECT COUNT(*) FROM mcq WHERE exam=? AND topic=?",
        (context.user_data["exam"], context.user_data["topic"])
    )
    total_q = cur.fetchone()[0]

    context.user_data["limit"] = min(
        context.user_data["limit"], total_q
    )

    await send_mcq(q, context)

# ---------- SEND MCQ ----------
async def send_mcq(q, context):
    asked = context.user_data.get("asked_questions", [])

    if asked:
        placeholders = ",".join("?" * len(asked))
        query = f"""
        SELECT * FROM mcq 
        WHERE exam=? AND topic=? 
        AND id NOT IN ({placeholders})
        ORDER BY RANDOM() LIMIT 1
        """
        params = [context.user_data["exam"], context.user_data["topic"]] + asked
    else:
        query = """
        SELECT * FROM mcq 
        WHERE exam=? AND topic=? 
        ORDER BY RANDOM() LIMIT 1
        """
        params = [context.user_data["exam"], context.user_data["topic"]]

    cur.execute(query, params)
    mcq = cur.fetchone()

    if not mcq:
        #await q.edit_message_text("✅ All questions completed for this topic.")
        return

    # save asked question id
    context.user_data["asked_questions"].append(mcq[0])

    context.user_data["ans"] = mcq[8]
    context.user_data["exp"] = mcq[9]

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

    # check answer
    if q.data.split("_")[1] == context.user_data["ans"]:
        context.user_data["score"] += 1

    context.user_data["q_no"] += 1

    # 👉 TEST COMPLETE CONDITION (MOST IMPORTANT)
    if context.user_data["q_no"] >= context.user_data["limit"]:
        score = context.user_data["score"]
        total = context.user_data["q_no"]

        # save score
        cur.execute("""
        INSERT INTO scores (user_id, exam, topic, score, total, test_date)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            q.from_user.id,
            context.user_data["exam"],
            context.user_data["topic"],
            score,
            total,
            datetime.date.today().isoformat()
        ))
        conn.commit()

        acc = round((score / total) * 100, 2)

        await q.edit_message_text(
            f"🎯 Test Completed ✅\n\n"
            f"Score: {score}/{total}\n"
            f"Accuracy: {acc}%"
        )
        return

    # 👉 NEXT QUESTION
    await send_mcq(q, context)
    
#-----------------old code with comment 
"""async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data.split("_")[1] == context.user_data["ans"]:
        context.user_data["score"] += 1

    context.user_data["q_no"] += 1

    if context.user_data["q_no"] >= context.user_data["limit"]:
        score = context.user_data["score"]
        total = context.user_data["limit"]

        cur.execute("""
       # INSERT INTO scores (user_id, exam, topic, score, total, test_date)
       # VALUES (?, ?, ?, ?, ?, ?)
        """, (
            q.from_user.id,
            context.user_data["exam"],
            context.user_data["topic"],
            score,
            total,
            datetime.date.today().isoformat()
        ))
        conn.commit()

        acc = round((score / total) * 100, 2)

        await q.edit_message_text(
            f"🎯 Test Completed\nScore: {score}/{total}\nAccuracy: {acc}%"
        )
    else:
        await send_mcq(q, context)"""

# ---------- MY SCORE (USER SCORE HISTORY) ----------
async def myscore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    cur.execute(
        "SELECT exam, topic, score, total, test_date FROM scores "
        "WHERE user_id=? ORDER BY id DESC LIMIT 5",
        (user_id,)
    )
    rows = cur.fetchall()

    if not rows:
        await update.message.reply_text("❌ No score history found.")
        return

    msg = "📊 MyScoreCard – Recent Tests\n\n"
    for r in rows:
        msg += f"📘 {r[0]} | {r[1]}\nScore: {r[2]}/{r[3]} | {r[4]}\n\n"

    await update.message.reply_text(msg)

# ---------- LEADERBOARD (EXAM + ACCURACY) ----------
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    exam = context.args[0] if context.args else "MPPSC"

    cur.execute("""
    SELECT user_id,
           SUM(score)*100.0/SUM(total) AS accuracy
    FROM scores
    WHERE exam=?
    GROUP BY user_id
    ORDER BY accuracy DESC
    LIMIT 10
    """, (exam,))
    rows = cur.fetchall()

    msg = f"🏆 {exam} Leaderboard (Accuracy)\n\n"
    for i, r in enumerate(rows, 1):
        msg += f"{i}. User {r[0]} → {round(r[1],2)}%\n"

    await update.message.reply_text(msg)

# ---------- PERFORMANCE TREND ----------
async def performance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cur.execute("""
    SELECT score, total FROM scores
    WHERE user_id=?
    ORDER BY id DESC LIMIT 7
    """, (uid,))
    rows = cur.fetchall()

    if not rows:
        await update.message.reply_text("❌ No performance data.")
        return

    msg = "📈 Performance Trend\n\n"
    for i, r in enumerate(rows[::-1], 1):
        bar = "█" * int((r[0]/r[1]) * 10)
        msg += f"Test {i}: {bar} {r[0]}/{r[1]}\n"

    await update.message.reply_text(msg)

# ---------- DAILY TOPPERS ----------
async def daily_toppers(context: ContextTypes.DEFAULT_TYPE):
    today = datetime.date.today().isoformat()
    cur.execute("""
    SELECT user_id, SUM(score)*100.0/SUM(total) acc
    FROM scores WHERE test_date=?
    GROUP BY user_id
    ORDER BY acc DESC LIMIT 3
    """, (today,))
    rows = cur.fetchall()

    if not rows:
        return

    msg = "🔥 Daily Toppers – MyScoreCard 🔥\n\n"
    for i, r in enumerate(rows, 1):
        msg += f"{i}. User {r[0]} → {round(r[1],2)}%\n"

    await context.bot.send_message(chat_id=CHANNEL_ID, text=msg)

# ---------- MAIN ----------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myscore", myscore))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("performance", performance))
    app.add_handler(CallbackQueryHandler(exam_select, "^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select, "^topic_"))
    app.add_handler(CallbackQueryHandler(answer, "^ans_"))

    app.job_queue.run_daily(
        daily_toppers,
        time=datetime.time(hour=21, minute=0)
    )

    print("🤖 MyScoreCard Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()







