import os
import sqlite3
import datetime
import pandas as pd

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Document
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [1977205811]
BOT_BRAND = "MyScoreCard Telegram Bot"

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

def nav_buttons(prev=None, next=None):
    row = []
    if prev:
        row.append(InlineKeyboardButton("⬅️ Back", callback_data=prev))
    if next:
        row.append(InlineKeyboardButton("➡️ Next", callback_data=next))

    return InlineKeyboardMarkup([
        row,
        [
            InlineKeyboardButton("🏠 Home", callback_data="start_new"),
            InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result")
        ],
        [
            InlineKeyboardButton("📊 My Score", callback_data="myscore")
        ]
    ])

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Welcome to MyScoreCard Bot*\n\nSelect Exam 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📘 MPPSC", callback_data="exam_MPPSC")],
            [InlineKeyboardButton("📕 UGC NET", callback_data="exam_NET")]
        ])
    )

async def start_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    await q.edit_message_text(
        "🏠 *Home*\n\nSelect Exam 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📘 MPPSC", callback_data="exam_MPPSC")],
            [InlineKeyboardButton("📕 UGC NET", callback_data="exam_NET")]
        ])
    )

# ================= EXAM & TOPIC =================
async def exam_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    context.user_data["exam"] = q.data.split("_")[1]

    await q.edit_message_text(
        "Choose Topic 👇",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("History", callback_data="topic_History")],
            [InlineKeyboardButton("Polity", callback_data="topic_Polity")]
        ])
    )

async def topic_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    exam = context.user_data["exam"]
    topic = q.data.split("_")[1]

    cur.execute("SELECT COUNT(*) FROM mcq WHERE exam=? AND topic=?", (exam, topic))
    total = cur.fetchone()[0]

    if total == 0:
        await q.edit_message_text("❌ No questions available.", reply_markup=nav_buttons())
        return

    context.user_data.update({
        "topic": topic,
        "score": 0,
        "q_no": 0,
        "limit": total,
        "asked": [],
        "attempts": [],
        "wrong": []
    })

    await send_mcq(q, context)

# ================= MCQ =================
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

    context.user_data["current"] = mcq
    context.user_data["asked"].append(mcq[0])

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
        reply_markup=nav_buttons(prev="wrong_only")
    )

# ================= WRONG ONLY =================
async def wrong_only(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    context.user_data["wrong_idx"] = 0
    await show_wrong(q, context)

async def show_wrong(q, context):
    idx = context.user_data["wrong_idx"]
    wrong = context.user_data["wrong"]

    if not wrong:
        await q.edit_message_text("🎉 No wrong questions!", reply_markup=nav_buttons())
        return

    if idx >= len(wrong):
        await q.edit_message_text(
            "✅ Wrong Practice Completed",
            reply_markup=nav_buttons()
        )
        return

    w = wrong[idx]
    await q.edit_message_text(
        f"❌ *Wrong Question {idx+1}/{len(wrong)}*\n\n"
        f"{w[3]}\n\n"
        f"A. {w[4]}\nB. {w[5]}\nC. {w[6]}\nD. {w[7]}\n\n"
        f"✅ सही उत्तर: {w[8]}\n\n📘 {w[9]}",
        parse_mode="Markdown",
        reply_markup=nav_buttons(
            prev="wrong_prev" if idx > 0 else None,
            next="wrong_next" if idx < len(wrong)-1 else None
        )
    )

async def wrong_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["wrong_idx"] += 1
    await show_wrong(q, context)

async def wrong_prev(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["wrong_idx"] -= 1
    await show_wrong(q, context)

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
        await q.edit_message_text("❌ No history", reply_markup=nav_buttons())
        return

    msg = "📊 *Your Scores*\n\n"
    for r in rows:
        msg += f"{r[0]} | {r[1]} → {r[2]}/{r[3]} ({r[4]})\n"

    await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=nav_buttons())

# ================= PDF (HINDI + WATERMARK FIXED) =================
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.colors import lightgrey

pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))

def generate_pdf(uid, context):
    file = f"result_{uid}.pdf"
    styles = getSampleStyleSheet()
    styles["Normal"].fontName = "HeiseiMin-W3"
    styles["Title"].fontName = "HeiseiMin-W3"

    doc = SimpleDocTemplate(file, pagesize=A4)
    story = []

    story.append(Paragraph("📘 MyScoreCard – परीक्षा परिणाम", styles["Title"]))
    story.append(Spacer(1, 15))

    for i, a in enumerate(context.user_data["attempts"], 1):
        story.append(Paragraph(f"<b>प्रश्न {i}:</b> {a['question']}", styles["Normal"]))
        for k, v in a["options"].items():
            story.append(Paragraph(f"{k}. {v}", styles["Normal"]))
        story.append(Paragraph(f"सही उत्तर: {a['correct']}", styles["Normal"]))
        story.append(Paragraph(f"व्याख्या: {a['explanation']}", styles["Normal"]))
        story.append(Spacer(1, 12))

    def watermark(c, d):
        c.saveState()
        c.setFont("HeiseiMin-W3", 32)
        c.setFillColor(lightgrey)
        c.rotate(45)
        c.drawCentredString(300, 400, BOT_BRAND)
        c.restoreState()

    doc.build(story, onFirstPage=watermark, onLaterPages=watermark)
    return file

async def pdf_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    file = generate_pdf(q.from_user.id, context)
    await context.bot.send_document(
        chat_id=q.from_user.id,
        document=open(file, "rb"),
        filename="MyScoreCard_Result.pdf"
    )

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(start_new, "^start_new$"))
    app.add_handler(CallbackQueryHandler(exam_select, "^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select, "^topic_"))
    app.add_handler(CallbackQueryHandler(answer, "^ans_"))
    app.add_handler(CallbackQueryHandler(wrong_only, "^wrong_only$"))
    app.add_handler(CallbackQueryHandler(wrong_next, "^wrong_next$"))
    app.add_handler(CallbackQueryHandler(wrong_prev, "^wrong_prev$"))
    app.add_handler(CallbackQueryHandler(myscore, "^myscore$"))
    app.add_handler(CallbackQueryHandler(pdf_result, "^pdf_result$"))

    print("🤖 Bot Running…")
    app.run_polling()

if __name__ == "__main__":
    main()
