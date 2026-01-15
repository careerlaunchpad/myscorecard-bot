import sqlite3
import random
import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

TOKEN = "8438663111:AAEcoEzGY5L2l9l4kSLEASQ8vgRaHE00Bi8"

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
conn.commit()

# ---------- SAMPLE MCQ ----------
def insert_sample_mcq():
    cur.execute("SELECT COUNT(*) FROM mcq")
    if cur.fetchone()[0] == 0:
        cur.execute("""
        INSERT INTO mcq
        (exam, topic, question, a, b, c, d, correct, explanation)
        VALUES
        ('MPPSC','History',
         'संविधान सभा की पहली बैठक कब हुई?',
         '1946','1947','1948','1950',
         'A',
         'संविधान सभा की पहली बैठक 9 दिसम्बर 1946 को हुई')
        """)
        conn.commit()

insert_sample_mcq()

# ---------- HELPERS ----------
def add_user(user_id: int):
    cur.execute(
        "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
        (user_id,)
    )
    conn.commit()

def is_paid_user(user_id: int) -> bool:
    cur.execute(
        "SELECT is_paid, expiry FROM users WHERE user_id=?",
        (user_id,)
    )
    row = cur.fetchone()
    if not row or row[0] == 0 or not row[1]:
        return False
    expiry = datetime.datetime.strptime(row[1], "%Y-%m-%d")
    return expiry >= datetime.datetime.now()

# ---------- COMMANDS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    add_user(user_id)

    keyboard = [
        [InlineKeyboardButton("MPPSC", callback_data="exam_MPPSC")],
        [InlineKeyboardButton("UGC NET", callback_data="exam_NET")]
    ]

    await update.message.reply_text(
        "👋 Welcome to MCQ Test Bot\n\nSelect Exam 👇",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def exam_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    exam = query.data.split("_")[1]
    context.user_data["exam"] = exam

    keyboard = [
        [InlineKeyboardButton("History", callback_data="topic_History")],
        [InlineKeyboardButton("Polity", callback_data="topic_Polity")]
    ]

    await query.edit_message_text(
        f"📘 Exam Selected: {exam}\n\nChoose Topic 👇",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def topic_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    topic = query.data.split("_")[1]
    context.user_data.update({
        "topic": topic,
        "score": 0,
        "q_no": 0
    })

    paid = is_paid_user(query.from_user.id)
    context.user_data["limit"] = 10 if paid else 3

    await send_mcq(query, context)

async def send_mcq(query, context):
    exam = context.user_data["exam"]
    topic = context.user_data["topic"]

    cur.execute(
        "SELECT * FROM mcq WHERE exam=? AND topic=? ORDER BY RANDOM() LIMIT 1",
        (exam, topic)
    )
    mcq = cur.fetchone()

    if not mcq:
        await query.edit_message_text("❌ No MCQ found.")
        return

    context.user_data["current_answer"] = mcq[8]
    context.user_data["explanation"] = mcq[9]

    keyboard = [
        [
            InlineKeyboardButton("A", callback_data="ans_A"),
            InlineKeyboardButton("B", callback_data="ans_B")
        ],
        [
            InlineKeyboardButton("C", callback_data="ans_C"),
            InlineKeyboardButton("D", callback_data="ans_D")
        ]
    ]

    text = (
        f"❓ Q{context.user_data['q_no'] + 1}\n"
        f"{mcq[3]}\n\n"
        f"A. {mcq[4]}\n"
        f"B. {mcq[5]}\n"
        f"C. {mcq[6]}\n"
        f"D. {mcq[7]}"
    )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    selected = query.data.split("_")[1]
    correct = context.user_data["current_answer"]
    paid = is_paid_user(query.from_user.id)

    if selected == correct:
        context.user_data["score"] += 1
        msg = "✅ Correct Answer!"
    else:
        msg = f"❌ Wrong! Correct Answer: {correct}"

    if paid:
        msg += f"\n📘 Explanation: {context.user_data['explanation']}"

    context.user_data["q_no"] += 1

    if context.user_data["q_no"] >= context.user_data["limit"]:
        score = context.user_data["score"]
        total = context.user_data["limit"]

        keyboard = [[
            InlineKeyboardButton("💎 Upgrade Premium", callback_data="upgrade")
        ]]

        await query.edit_message_text(
            f"🎯 Test Completed\n\nScore: {score}/{total}\n\n"
            "🔓 Premium Users get:\n"
            "✔ 10–50 MCQ/day\n"
            "✔ Explanation\n"
            "✔ Mock Tests",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await query.edit_message_text(msg)
        await send_mcq(query, context)

async def upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "💰 Premium Plan\n\n"
        "₹199 / Month\n\n"
        "UPI: yourupi@okaxis\n"
        "Payment ke baad /paid likho"
    )

async def paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    expiry = (
        datetime.datetime.now() + datetime.timedelta(days=30)
    ).strftime("%Y-%m-%d")

    cur.execute(
        "UPDATE users SET is_paid=1, expiry=? WHERE user_id=?",
        (expiry, user_id)
    )
    conn.commit()

    await update.message.reply_text(
        "✅ Premium Activated for 30 Days 🎉"
    )

# ---------- MAIN ----------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("paid", paid))
    app.add_handler(CallbackQueryHandler(exam_select, pattern="^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select, pattern="^topic_"))
    app.add_handler(CallbackQueryHandler(answer_handler, pattern="^ans_"))
    app.add_handler(CallbackQueryHandler(upgrade, pattern="^upgrade$"))

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
