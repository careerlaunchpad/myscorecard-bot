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

    context.user_data.clear()
    context.user_data["exam"] = q.data.split("_")[1]

    kb = [
        [InlineKeyboardButton("History", callback_data="topic_History")],
        [InlineKeyboardButton("Polity", callback_data="topic_Polity")]
    ]
    await q.edit_message_text(
        f"📘 Exam: {context.user_data['exam']}\nChoose Topic 👇",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ---------- TOPIC ----------
async def topic_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    context.user_data["topic"] = q.data.split("_")[1]
    context.user_data["score"] = 0
    context.user_data["q_no"] = 0
    context.user_data["asked_questions"] = []
    context.user_data["attempts"] = []
    context.user_data["wrong_questions"] = []

    limit = 50 if is_paid(q.from_user.id) else 10
    cur.execute(
        "SELECT COUNT(*) FROM mcq WHERE exam=? AND topic=?",
        (context.user_data["exam"], context.user_data["topic"])
    )
    total_q = cur.fetchone()[0]
    context.user_data["limit"] = min(limit, total_q)

    await send_mcq(q, context)

# ---------- SEND MCQ ----------
async def send_mcq(q, context):
    asked = context.user_data["asked_questions"]

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
        await finish_test(q, context)
        return

    context.user_data["asked_questions"].append(mcq[0])
    context.user_data["last_question"] = mcq[3]
    context.user_data["last_options"] = {
        "A": mcq[4],
        "B": mcq[5],
        "C": mcq[6],
        "D": mcq[7]
    }
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

    selected = q.data.split("_")[1]

    context.user_data["attempts"].append({
        "question": context.user_data["last_question"],
        "options": context.user_data["last_options"],
        "selected": selected,
        "correct": context.user_data["ans"],
        "explanation": context.user_data["exp"]
    })

    if selected == context.user_data["ans"]:
        context.user_data["score"] += 1
    else:
        context.user_data["wrong_questions"].append({
            "question": context.user_data["last_question"],
            "options": context.user_data["last_options"],
            "correct": context.user_data["ans"],
            "explanation": context.user_data["exp"]
        })

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
        "INSERT INTO scores (user_id, exam, topic, score, total, test_date) "
        "VALUES (?, ?, ?, ?, ?, ?)",
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
        f"👇 Choose option",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Review Answers", callback_data="review_0")],
            [InlineKeyboardButton("❌ Practice Wrong Only", callback_data="wrong_only")],
            [InlineKeyboardButton("📄 Download Result PDF", callback_data="pdf_result")]
        ])
    )

# ---------- WRONG ONLY REVIEW ----------
async def wrong_only_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not context.user_data["wrong_questions"]:
        await q.edit_message_text("🎉 No wrong questions to practice!")
        return

    context.user_data["wrong_index"] = 0
    await send_wrong_review(q, context)

async def send_wrong_review(q, context):
    idx = context.user_data["wrong_index"]
    wrongs = context.user_data["wrong_questions"]

    if idx >= len(wrongs):
        await q.edit_message_text(
            "✅ Wrong-Only Practice Completed 🎯",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Start New Test", callback_data="start_new")],
                [InlineKeyboardButton("📊 My Score", callback_data="go_myscore")]
            ])
        )
        return

    w = wrongs[idx]

    await q.edit_message_text(
        f"❌ Wrong Question {idx+1}\n\n"
        f"{w['question']}\n\n"
        f"A. {w['options']['A']}\n"
        f"B. {w['options']['B']}\n"
        f"C. {w['options']['C']}\n"
        f"D. {w['options']['D']}\n\n"
        f"✅ Correct Answer: {w['correct']}\n\n"
        f"📘 {w['explanation']}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Next ▶", callback_data="wrong_next")]
        ])
    )

async def wrong_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["wrong_index"] += 1
    await send_wrong_review(q, context)

# ---------- REVIEW ANSWERS ----------
async def review_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    idx = int(q.data.split("_")[1])
    attempts = context.user_data["attempts"]

    if idx >= len(attempts):
        await q.edit_message_text(
            "✅ Review Completed 🎉",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Start New Test", callback_data="start_new")],
                [InlineKeyboardButton("📊 My Score", callback_data="go_myscore")]
            ])
        )
        return

    a = attempts[idx]

    await q.edit_message_text(
        f"❓ Q{idx+1}\n{a['question']}\n\n"
        f"A. {a['options']['A']}\n"
        f"B. {a['options']['B']}\n"
        f"C. {a['options']['C']}\n"
        f"D. {a['options']['D']}\n\n"
        f"🧑 Your Answer: {a['selected']}\n"
        f"✅ Correct: {a['correct']}\n\n"
        f"📘 {a['explanation']}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Next ▶", callback_data=f"review_{idx+1}")]
        ])
    )

# ---------- PDF ----------
def generate_result_pdf(user_id, exam, topic, attempts, score, total):
    filename = f"result_{user_id}.pdf"
    c = canvas.Canvas(filename, pagesize=A4)
    y = 800

    c.drawString(40, y, f"Exam: {exam} | Topic: {topic}")
    y -= 30
    c.drawString(40, y, f"Score: {score}/{total}")
    y -= 40

    for i, a in enumerate(attempts, 1):
        if y < 100:
            c.showPage()
            y = 800
        c.drawString(40, y, f"Q{i}. {a['question']}")
        y -= 15
        c.drawString(40, y, f"Correct: {a['correct']}")
        y -= 25

    c.save()
    return filename

async def pdf_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    file = generate_result_pdf(
        q.from_user.id,
        context.user_data["exam"],
        context.user_data["topic"],
        context.user_data["attempts"],
        context.user_data["score"],
        context.user_data["q_no"]
    )

    await context.bot.send_document(chat_id=q.from_user.id, document=open(file, "rb"))

# ---------- START NEW ----------
async def start_new_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await start(update, context)

# ---------- MAIN ----------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myscore", start))
    app.add_handler(CallbackQueryHandler(exam_select, "^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select, "^topic_"))
    app.add_handler(CallbackQueryHandler(answer, "^ans_"))
    app.add_handler(CallbackQueryHandler(review_answers, "^review_"))
    app.add_handler(CallbackQueryHandler(wrong_only_start, "^wrong_only$"))
    app.add_handler(CallbackQueryHandler(wrong_next, "^wrong_next$"))
    app.add_handler(CallbackQueryHandler(start_new_test, "^start_new$"))
    app.add_handler(CallbackQueryHandler(pdf_result, "^pdf_result$"))

    print("🤖 MyScoreCard Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
