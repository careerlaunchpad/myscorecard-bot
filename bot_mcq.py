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

# ================= PDF =================
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.colors import lightgrey

pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))

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

# ================= HELPERS =================
def is_admin(uid):
    return uid in ADMIN_IDS

def exam_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📘 MPPSC", callback_data="exam_MPPSC")],
        [InlineKeyboardButton("📕 UGC NET", callback_data="exam_NET")]
    ])

def home_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬅️ Back", callback_data="start_new"),
            InlineKeyboardButton("🏠 Home", callback_data="start_new")
        ],
        [
            InlineKeyboardButton("📊 My Score", callback_data="myscore"),
            InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result")
        ]
    ])

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
    await q.edit_message_text(
        "👋 *Welcome to MyScoreCard Bot*\n\nSelect Exam 👇",
        parse_mode="Markdown",
        reply_markup=exam_kb()
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
        await q.edit_message_text("❌ इस Exam में प्रश्न नहीं हैं।", reply_markup=home_kb())
        return

    await q.edit_message_text(
        "Choose Topic 👇",
        reply_markup=InlineKeyboardMarkup([
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
        await q.edit_message_text("⚠️ Session expired.", reply_markup=home_kb())
        return

    cur.execute("SELECT COUNT(*) FROM mcq WHERE exam=? AND topic=?", (exam, topic))
    total = cur.fetchone()[0]

    if total == 0:
        await q.edit_message_text("❌ इस Topic में प्रश्न नहीं हैं।", reply_markup=home_kb())
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

    await q.edit_message_text(
        f"❓ *Q{context.user_data['q_no']+1}/{context.user_data['limit']}*\n\n"
        f"{mcq[3]}\n\n"
        f"A. {mcq[4]}\nB. {mcq[5]}\nC. {mcq[6]}\nD. {mcq[7]}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
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
        "q": mcq[3],
        "a": mcq[4],
        "b": mcq[5],
        "c": mcq[6],
        "d": mcq[7],
        "correct": mcq[8],
        "exp": mcq[9]
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
        "INSERT INTO scores (user_id, exam, topic, score, total, test_date) VALUES (?,?,?,?,?,?)",
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

    await q.edit_message_text(
        f"🎯 *Test Completed*\n\nScore: *{context.user_data['score']}/{context.user_data['q_no']}*",
        parse_mode="Markdown",
        reply_markup=home_kb()
    )

# ================= PDF =================
def generate_pdf(uid, exam, topic, attempts, score, total):
    file = f"result_{uid}.pdf"
    doc = SimpleDocTemplate(file, pagesize=A4)
    styles = getSampleStyleSheet()
    styles["Normal"].fontName = "HeiseiMin-W3"
    story = []

    story.append(Paragraph("📘 MyScoreCard – परीक्षा परिणाम", styles["Title"]))
    story.append(Spacer(1, 10))
    story.append(Paragraph(f"परीक्षा: {exam}", styles["Normal"]))
    story.append(Paragraph(f"विषय: {topic}", styles["Normal"]))
    story.append(Paragraph(f"स्कोर: {score}/{total}", styles["Normal"]))
    story.append(Spacer(1, 15))

    for i, a in enumerate(attempts, 1):
        story.append(Paragraph(f"<b>प्रश्न {i}:</b> {a['q']}", styles["Normal"]))
        story.append(Paragraph(f"A. {a['a']}", styles["Normal"]))
        story.append(Paragraph(f"B. {a['b']}", styles["Normal"]))
        story.append(Paragraph(f"C. {a['c']}", styles["Normal"]))
        story.append(Paragraph(f"D. {a['d']}", styles["Normal"]))
        story.append(Paragraph(f"✅ सही उत्तर: {a['correct']}", styles["Normal"]))
        story.append(Paragraph(f"📘 व्याख्या: {a['exp']}", styles["Normal"]))
        story.append(Spacer(1, 12))

    def watermark(c, _):
        c.saveState()
        c.setFont("HeiseiMin-W3", 30)
        c.setFillColor(lightgrey)
        c.translate(300, 400)
        c.rotate(45)
        c.drawCentredString(0, 0, "MyScoreCard Bot")
        c.restoreState()

    doc.build(story, onFirstPage=watermark, onLaterPages=watermark)
    return file

async def pdf_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if "exam" not in context.user_data:
        await q.edit_message_text("⚠️ Session expired. नया test शुरू करें।", reply_markup=home_kb())
        return

    file = generate_pdf(
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
        filename="MyScoreCard_Result.pdf",
        reply_markup=home_kb()
    )

# ================= MY SCORE =================
async def myscore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    cur.execute(
        "SELECT exam, topic, score, total, test_date FROM scores WHERE user_id=? ORDER BY id DESC LIMIT 5",
        (q.from_user.id,)
    )
    rows = cur.fetchall()

    if not rows:
        await q.edit_message_text("❌ No score history.", reply_markup=home_kb())
        return

    msg = "📊 *Your Recent Tests*\n\n"
    for r in rows:
        msg += f"{r[0]} | {r[1]} → {r[2]}/{r[3]} ({r[4]})\n"

    await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=home_kb())

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(start_new, "^start_new$"))
    app.add_handler(CallbackQueryHandler(exam_select, "^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select, "^topic_"))
    app.add_handler(CallbackQueryHandler(answer, "^ans_"))
    app.add_handler(CallbackQueryHandler(myscore, "^myscore$"))
    app.add_handler(CallbackQueryHandler(pdf_result, "^pdf_result$"))

    print("🤖 Bot Running with FULL PDF support...")
    app.run_polling()

if __name__ == "__main__":
    main()
