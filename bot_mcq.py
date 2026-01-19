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
    filters,
)
from telegram.error import BadRequest

# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [1977205811]   # 👈 अपनी Telegram numeric ID
QUESTION_TIME = 30  # seconds per question

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
        await q.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return
        try:
            await q.message.reply_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception:
            pass

def safe_hindi(text):
    if not text:
        return ""
    return unicodedata.normalize("NFKC", str(text))

def is_admin(uid):
    return uid in ADMIN_IDS

# ================= UI HELPERS =================
def exam_kb():
    cur.execute("SELECT DISTINCT exam FROM mcq")
    exams = [r[0] for r in cur.fetchall()]
    if not exams:
        return InlineKeyboardMarkup([[InlineKeyboardButton("No Exam Available", callback_data="noop")]])
    return InlineKeyboardMarkup([[InlineKeyboardButton(e, callback_data=f"exam_{e}")] for e in exams])

def topic_kb(exam):
    cur.execute("SELECT DISTINCT topic FROM mcq WHERE exam=?", (exam,))
    topics = [r[0] for r in cur.fetchall()]
    buttons = [[InlineKeyboardButton(t, callback_data=f"topic_{t}")] for t in topics]
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="start_new")])
    return InlineKeyboardMarkup(buttons)

def home_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="start_new")],
        [InlineKeyboardButton("📊 My Score", callback_data="myscore")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
        [InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result")]
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
    await safe_edit_or_send(q, "👋 *Welcome to MyScoreCard Bot*\n\nSelect Exam 👇", exam_kb())

# ================= EXAM / TOPIC =================
async def exam_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    exam = q.data.replace("exam_", "")
    context.user_data.clear()
    context.user_data["exam"] = exam

    await safe_edit_or_send(q, "Choose Topic 👇", topic_kb(exam))

async def topic_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    exam = context.user_data.get("exam")
    topic = q.data.replace("topic_", "")

    cur.execute("SELECT COUNT(*) FROM mcq WHERE exam=? AND topic=?", (exam, topic))
    total = cur.fetchone()[0]
    if total == 0:
        await safe_edit_or_send(q, "❌ No questions.", home_kb())
        return

    context.user_data.update({
        "topic": topic,
        "score": 0,
        "q_no": 0,
        "limit": total,
        "asked": [],
        "wrong": [],
        "attempts": [],
        "timer": None
    })
    await send_mcq(q, context)

# ================= TIMER =================
async def question_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    q = job.data["query"]

    mcq = context.user_data["current"]
    context.user_data["attempts"].append({
        "question": mcq[3],
        "correct": mcq[8],
        "explanation": mcq[9],
        "selected": "⏱ Time Up"
    })
    context.user_data["q_no"] += 1
    await send_mcq(q, context)

# ================= MCQ =================
async def send_mcq(q, context):
    if context.user_data.get("timer"):
        context.user_data["timer"].schedule_removal()

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
        f"{mcq[3]}\n\n"
        f"A. {mcq[4]}\nB. {mcq[5]}\nC. {mcq[6]}\nD. {mcq[7]}\n\n"
        f"⏱ {QUESTION_TIME} sec",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("A", callback_data="ans_A"), InlineKeyboardButton("B", callback_data="ans_B")],
            [InlineKeyboardButton("C", callback_data="ans_C"), InlineKeyboardButton("D", callback_data="ans_D")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )

    context.user_data["timer"] = context.application.job_queue.run_once(
        question_timeout, QUESTION_TIME, data={"query": q}, chat_id=q.message.chat_id
    )

async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if context.user_data.get("timer"):
        context.user_data["timer"].schedule_removal()

    mcq = context.user_data["current"]
    selected = q.data.split("_")[1]

    context.user_data["attempts"].append({
        "question": mcq[3],
        "correct": mcq[8],
        "explanation": mcq[9],
        "selected": selected
    })

    if selected == mcq[8]:
        context.user_data["score"] += 1
    else:
        context.user_data["wrong"].append(mcq)

    context.user_data["q_no"] += 1
    await send_mcq(q, context)

# ================= RESULT / REVIEW =================
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
            [InlineKeyboardButton("📋 Review All", callback_data="review_all")],
            [InlineKeyboardButton("❌ Wrong Only", callback_data="wrong_only")],
            [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
            [InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )

async def review_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    text = "📋 *Review All Questions*\n\n"
    for i, a in enumerate(context.user_data["attempts"], 1):
        text += (
            f"*Q{i}.* {a['question']}\n"
            f"Your: {a['selected']} | Correct: {a['correct']}\n"
            f"📘 {a['explanation']}\n\n"
        )
    await safe_edit_or_send(q, text, home_kb())

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

    if idx >= len(wrong):
        await safe_edit_or_send(q, "✅ Completed", home_kb())
        return

    w = wrong[idx]
    await safe_edit_or_send(
        q,
        f"❌ *Wrong {idx+1}/{len(wrong)}*\n\n{w[3]}\n\n"
        f"✅ Correct: *{w[8]}*\n📘 {w[9]}",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Prev", callback_data="wrong_prev"),
             InlineKeyboardButton("➡️ Next", callback_data="wrong_next")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
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
    if context.user_data["widx"] < 0:
        context.user_data["widx"] = 0
    await show_wrong(q, context)

# ================= LEADERBOARD =================
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    exam = context.user_data.get("exam")
    topic = context.user_data.get("topic")

    cur.execute("""
        SELECT user_id, MAX(score) FROM scores
        WHERE exam=? AND topic=?
        GROUP BY user_id
        ORDER BY MAX(score) DESC LIMIT 10
    """, (exam, topic))

    rows = cur.fetchall()
    if not rows:
        await safe_edit_or_send(q, "❌ No data.", home_kb())
        return

    text = f"🏆 *Leaderboard – {exam}/{topic}*\n\n"
    for i, r in enumerate(rows, 1):
        text += f"{i}. `{r[0]}` → {r[1]}\n"

    await safe_edit_or_send(q, text, home_kb())

# ================= PDF =================
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import lightgrey

pdfmetrics.registerFont(TTFont("Hindi", "NotoSansDevanagari-Regular.ttf"))

def generate_pdf(uid, exam, topic, attempts, score, total):
    file = f"MyScoreCard_Result_{uid}.pdf"
    doc = SimpleDocTemplate(file, pagesize=A4)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H", fontName="Hindi", fontSize=11, leading=16))
    styles.add(ParagraphStyle(name="HT", fontName="Hindi", fontSize=16, leading=22))

    story = [Paragraph("MyScoreCard – टेस्ट परिणाम", styles["HT"]), Spacer(1, 10)]
    story.append(Paragraph(f"परीक्षा : {exam}", styles["H"]))
    story.append(Paragraph(f"विषय : {topic}", styles["H"]))
    story.append(Paragraph(f"स्कोर : {score}/{total}", styles["H"]))
    story.append(Spacer(1, 12))

    for i, a in enumerate(attempts, 1):
        story.append(Paragraph(f"<b>प्रश्न {i} :</b> {a['question']}", styles["H"]))
        story.append(Paragraph(f"<b>आपका :</b> {a['selected']}", styles["H"]))
        story.append(Paragraph(f"<b>सही :</b> {a['correct']}", styles["H"]))
        story.append(Paragraph(f"<b>व्याख्या :</b> {a['explanation']}", styles["H"]))
        story.append(Spacer(1, 10))

    def watermark(c, d):
        c.saveState()
        c.setFont("Hindi", 28)
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

    await context.bot.send_document(chat_id=q.from_user.id, document=open(file, "rb"))
    await context.bot.send_message(chat_id=q.from_user.id, text="📄 PDF Ready", reply_markup=home_kb())

# ================= ADMIN =================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    cur.execute("SELECT exam, topic, COUNT(*) FROM mcq GROUP BY exam, topic")
    rows = cur.fetchall()

    text = "👨‍💼 *ADMIN DASHBOARD*\n\n"
    for r in rows:
        text += f"{r[0]} / {r[1]} → {r[2]} MCQs\n"

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Upload Excel", callback_data="admin_upload")],
            [InlineKeyboardButton("🧾 Export DB", callback_data="admin_export")]
        ])
    )

async def upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("📤 Upload Excel (.xlsx)")

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
    await update.message.reply_text(f"✅ {len(df)} MCQs added")

async def admin_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    df = pd.read_sql_query("SELECT * FROM mcq", conn)
    file = "MCQ_DB.xlsx"
    df.to_excel(file, index=False)

    await context.bot.send_document(chat_id=q.from_user.id, document=open(file, "rb"))

# ================= FINAL HANDLERS =================
def register_final_handlers(app):
    app.add_handler(CallbackQueryHandler(leaderboard, "^leaderboard$"))
    app.add_handler(CallbackQueryHandler(review_all, "^review_all$"))
    app.add_handler(CallbackQueryHandler(admin_export, "^admin_export$"))

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
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
    app.add_handler(CallbackQueryHandler(pdf_result, "^pdf_result$"))

    register_final_handlers(app)

    print("🤖 Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
