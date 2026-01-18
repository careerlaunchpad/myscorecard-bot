import os
import sqlite3
import datetime
import pandas as pd

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from weasyprint import HTML

# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [1977205811]

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

# ================= SAFE EDIT =================
async def safe_edit_or_send(q, text, reply_markup=None):
    try:
        await q.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception:
        await q.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

# ================= UI =================
def exam_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📘 MPPSC", callback_data="exam_MPPSC")],
        [InlineKeyboardButton("📕 UGC NET", callback_data="exam_NET")]
    ])

def home_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="start_new")],
        [InlineKeyboardButton("📊 My Score", callback_data="myscore")],
        [InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result")]
    ])

def is_admin(uid):
    return uid in ADMIN_IDS

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 *Welcome to MyScoreCard Bot*\n\nSelect Exam 👇",
        parse_mode="Markdown",
        reply_markup=exam_kb()
    )

async def start_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    await safe_edit_or_send(q,
        "👋 *Welcome to MyScoreCard Bot*\n\nSelect Exam 👇",
        exam_kb()
    )

# ================= EXAM =================
async def exam_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    exam = q.data.split("_")[1]
    context.user_data.clear()
    context.user_data["exam"] = exam

    cur.execute("SELECT COUNT(*) FROM mcq WHERE exam=?", (exam,))
    if cur.fetchone()[0] == 0:
        await safe_edit_or_send(q, "❌ इस Exam में प्रश्न नहीं हैं।", home_kb())
        return

    await safe_edit_or_send(
        q,
        "Choose Topic 👇",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("History", callback_data="topic_History")],
            [InlineKeyboardButton("Polity", callback_data="topic_Polity")],
            [InlineKeyboardButton("⬅️ Back", callback_data="start_new")]
        ])
    )

# ================= TOPIC =================
async def topic_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    exam = context.user_data.get("exam")
    topic = q.data.split("_")[1]

    if not exam:
        await safe_edit_or_send(q, "⚠️ Session expired.", home_kb())
        return

    cur.execute("SELECT COUNT(*) FROM mcq WHERE exam=? AND topic=?", (exam, topic))
    total = cur.fetchone()[0]

    if total == 0:
        await safe_edit_or_send(q, "❌ इस Topic में प्रश्न नहीं हैं।", home_kb())
        return

    context.user_data.update({
        "topic": topic,
        "score": 0,
        "q_no": 0,
        "limit": total,
        "asked": [],
        "wrong": [],
        "attempts": []
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
        f"{mcq[3]}\n\n"
        f"A. {mcq[4]}\nB. {mcq[5]}\nC. {mcq[6]}\nD. {mcq[7]}",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("A", callback_data="ans_A"),
             InlineKeyboardButton("B", callback_data="ans_B")],
            [InlineKeyboardButton("C", callback_data="ans_C"),
             InlineKeyboardButton("D", callback_data="ans_D")]
        ])
    )

# ================= ANSWER =================
async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    mcq = context.user_data["current"]
    selected = q.data.split("_")[1]

    context.user_data["attempts"].append({
        "question": mcq[3],
        "correct": mcq[8],
        "explanation": mcq[9]
    })

    if selected == mcq[8]:
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
    cur.execute(
        "INSERT INTO scores VALUES (NULL,?,?,?,?,?,?)",
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
            [InlineKeyboardButton("❌ Wrong Only Practice", callback_data="wrong_only")],
            [InlineKeyboardButton("📊 My Score", callback_data="myscore")],
            [InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )

# ================= PDF (HTML → REAL HINDI) =================
def generate_pdf_html(uid, exam, topic, attempts, score, total):
    file = f"MyScoreCard_Result_{uid}.pdf"

    html = f"""
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            @font-face {{
                font-family: 'Mangal';
                src: url('Mangal.ttf');
            }}
            body {{
                font-family: 'Mangal';
                font-size: 14px;
            }}
            .watermark {{
                position: fixed;
                top: 40%;
                left: 25%;
                font-size: 48px;
                color: rgba(150,150,150,0.25);
                transform: rotate(-30deg);
            }}
        </style>
    </head>
    <body>
        <div class="watermark">MyScoreCard Bot</div>

        <h2>MyScoreCard – टेस्ट परिणाम</h2>
        <p>परीक्षा : {exam}</p>
        <p>विषय : {topic}</p>
        <p>स्कोर : {score}/{total}</p>
        <hr>
    """

    for i, a in enumerate(attempts, 1):
        html += f"""
        <p><b>प्रश्न {i} :</b> {a['question']}<br>
        <b>सही उत्तर :</b> {a['correct']}<br>
        <b>व्याख्या :</b> {a['explanation']}</p>
        """

    html += "</body></html>"

    HTML(string=html, base_url=".").write_pdf(file)
    return file

async def pdf_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if "exam" not in context.user_data:
        await safe_edit_or_send(q, "⚠️ No active test found.", home_kb())
        return

    file = generate_pdf_html(
        q.from_user.id,
        context.user_data["exam"],
        context.user_data["topic"],
        context.user_data["attempts"],
        context.user_data["score"],
        context.user_data["q_no"]
    )

    await context.bot.send_document(
        chat_id=q.from_user.id,
        document=open(file, "rb"),
        filename=file
    )

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myscore", myscore))

    app.add_handler(CallbackQueryHandler(start_new, "^start_new$"))
    app.add_handler(CallbackQueryHandler(exam_select, "^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select, "^topic_"))
    app.add_handler(CallbackQueryHandler(answer, "^ans_"))
    app.add_handler(CallbackQueryHandler(pdf_result, "^pdf_result$"))

    print("🤖 Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
