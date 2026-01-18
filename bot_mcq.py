import os
import sqlite3
import datetime
import pandas as pd
import unicodedata

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
ADMIN_IDS = [1977205811]   # अपनी Telegram numeric ID

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

# ================= SAFE HELPERS =================
async def safe_edit_or_send(q, text, reply_markup=None):
    try:
        await q.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception:
        await q.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

def safe_hindi(text):
    if not text:
        return ""
    return unicodedata.normalize("NFKC", str(text))

def is_admin(uid):
    return uid in ADMIN_IDS

# ================= UI =================
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
        [InlineKeyboardButton("📊 My Score", callback_data="myscore")]
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
    await safe_edit_or_send(
        q,
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
        await safe_edit_or_send(q, "❌ इस Exam में प्रश्न उपलब्ध नहीं हैं।", home_kb())
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

    await safe_edit_or_send(
        q,
        f"🎯 *Test Completed*\n\nScore: *{context.user_data['score']}/{context.user_data['q_no']}*",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Wrong Only Practice", callback_data="wrong_only")],
            [InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result")],
            [InlineKeyboardButton("📊 My Score", callback_data="myscore")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )

# ================= WRONG ONLY =================
async def wrong_only(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    wrong = context.user_data.get("wrong", [])
    if not wrong:
        await safe_edit_or_send(q, "🎉 No wrong questions!", home_kb())
        return

    context.user_data["widx"] = 0
    await show_wrong(q, context)

async def show_wrong(q, context):
    idx = context.user_data["widx"]
    wrong = context.user_data["wrong"]

    if idx < 0:
        context.user_data["widx"] = 0
        idx = 0

    if idx >= len(wrong):
        await safe_edit_or_send(q, "✅ Wrong Practice Completed", home_kb())
        return

    w = wrong[idx]
    await safe_edit_or_send(
        q,
        f"❌ *Wrong {idx+1}/{len(wrong)}*\n\n{w[3]}\n\n"
        f"A. {w[4]}\nB. {w[5]}\nC. {w[6]}\nD. {w[7]}\n\n"
        f"✅ Correct: *{w[8]}*\n\n📘 {w[9]}",
        InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⬅️ Prev", callback_data="wrong_prev"),
                InlineKeyboardButton("➡️ Next", callback_data="wrong_next")
            ],
            [
                InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result"),
                InlineKeyboardButton("🏠 Home", callback_data="start_new")
            ]
        ])
    )

async def wrong_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["widx"] += 1
    await show_wrong(q, context)

async def wrong_prev(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["widx"] -= 1
    await show_wrong(q, context)

# ================= MY SCORE =================
async def myscore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        send = q.edit_message_text
    else:
        send = update.message.reply_text

    cur.execute(
        "SELECT exam, topic, score, total, test_date FROM scores WHERE user_id=? ORDER BY id DESC LIMIT 5",
        (update.effective_user.id,)
    )
    rows = cur.fetchall()

    if not rows:
        await send("❌ No score history.", reply_markup=home_kb())
        return

    msg = "📊 *Your Recent Tests*\n\n"
    for r in rows:
        msg += f"{r[0]} | {r[1]} → {r[2]}/{r[3]} ({r[4]})\n"

    await send(msg, parse_mode="Markdown", reply_markup=home_kb())

# ================= PDF (HINDI SAFE – REPORTLAB) =================
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import lightgrey

pdfmetrics.registerFont(
    TTFont("NotoHindi", "NotoSansDevanagari-Regular.ttf")
)

def generate_pdf(uid, exam, topic, attempts, score, total):
    file = f"MyScoreCard_Result_{uid}.pdf"
    doc = SimpleDocTemplate(file, pagesize=A4, leftMargin=40, rightMargin=40)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="Hindi",
        fontName="NotoHindi",
        fontSize=11,
        leading=16
    ))
    styles.add(ParagraphStyle(
        name="HindiTitle",
        fontName="NotoHindi",
        fontSize=15,
        leading=22
    ))

    story = []
    story.append(Paragraph("MyScoreCard – टेस्ट परिणाम", styles["HindiTitle"]))
    story.append(Spacer(1, 10))
    story.append(Paragraph(f"परीक्षा : {safe_hindi(exam)}", styles["Hindi"]))
    story.append(Paragraph(f"विषय : {safe_hindi(topic)}", styles["Hindi"]))
    story.append(Paragraph(f"स्कोर : {score}/{total}", styles["Hindi"]))
    story.append(Spacer(1, 14))

    for i, a in enumerate(attempts, 1):
        story.append(Paragraph(f"<b>प्रश्न {i} :</b> {safe_hindi(a['question'])}", styles["Hindi"]))
        story.append(Paragraph(f"<b>सही उत्तर :</b> {safe_hindi(a['correct'])}", styles["Hindi"]))
        story.append(Paragraph(f"<b>व्याख्या :</b> {safe_hindi(a['explanation'])}", styles["Hindi"]))
        story.append(Spacer(1, 12))

    def watermark(c, d):
        c.saveState()
        c.setFont("NotoHindi", 26)
        c.setFillColor(lightgrey)
        c.translate(300, 420)
        c.rotate(45)
        c.drawCentredString(0, 0, "MyScoreCard Bot")
        c.restoreState()

    doc.build(story, onFirstPage=watermark, onLaterPages=watermark)
    return file

async def pdf_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

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
        filename=file
    )

    await context.bot.send_message(
        chat_id=q.from_user.id,
        text="📄 PDF तैयार है। आगे क्या करना चाहेंगे?",
        reply_markup=home_kb()
    )

# ================= ADMIN =================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin access denied.")
        return

    cur.execute("SELECT COUNT(*) FROM mcq")
    mcqs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM scores")
    tests = cur.fetchone()[0]

    await update.message.reply_text(
        f"🛠 *ADMIN PANEL*\n\n📚 MCQs: {mcqs}\n📝 Tests: {tests}\n\n/upload – Upload Excel",
        parse_mode="Markdown"
    )

async def upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    await update.message.reply_text(
        "📤 Upload Excel (.xlsx)\n\nColumns:\nexam, topic, question, a, b, c, d, correct, explanation"
    )

async def handle_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    file = await update.message.document.get_file()
    path = "upload.xlsx"
    await file.download_to_drive(path)

    df = pd.read_excel(path)
    for _, r in df.iterrows():
        cur.execute(
            "INSERT INTO mcq VALUES (NULL,?,?,?,?,?,?,?,?,?)",
            (r.exam, r.topic, r.question, r.a, r.b, r.c, r.d, r.correct, r.explanation)
        )
    conn.commit()

    await update.message.reply_text(f"✅ {len(df)} MCQs uploaded successfully")

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myscore", myscore))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("upload", upload))

    app.add_handler(MessageHandler(filters.Document.ALL, handle_excel))

    app.add_handler(CallbackQueryHandler(start_new, "^start_new$"))
    app.add_handler(CallbackQueryHandler(exam_select, "^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select, "^topic_"))
    app.add_handler(CallbackQueryHandler(answer, "^ans_"))
    app.add_handler(CallbackQueryHandler(wrong_only, "^wrong_only$"))
    app.add_handler(CallbackQueryHandler(wrong_next, "^wrong_next$"))
    app.add_handler(CallbackQueryHandler(wrong_prev, "^wrong_prev$"))
    app.add_handler(CallbackQueryHandler(myscore, "^myscore$"))
    app.add_handler(CallbackQueryHandler(pdf_result, "^pdf_result$"))

    print("🤖 Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
