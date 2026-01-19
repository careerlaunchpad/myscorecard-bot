# ================= PART 1 / 3 =================
# Core Setup, DB, Safe Helpers, Dynamic Exam/Topic

import os
import sqlite3
import datetime
import pandas as pd
import unicodedata
import asyncio

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
ADMIN_IDS = [1977205811]   # <-- अपनी Telegram numeric ID

QUESTION_TIME = 30  # ⏱ per question timer (seconds)

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
    """
    Prevents:
    - Message is not modified error
    - Dead ends
    """
    try:
        await q.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return
        try:
            await q.message.reply_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
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
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("No Exam Available", callback_data="noop")]
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(e, callback_data=f"exam_{e}")]
        for e in exams
    ])

def topic_kb(exam):
    cur.execute("SELECT DISTINCT topic FROM mcq WHERE exam=?", (exam,))
    topics = [r[0] for r in cur.fetchall()]
    buttons = [
        [InlineKeyboardButton(t, callback_data=f"topic_{t}")]
        for t in topics
    ]
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="start_new")])
    return InlineKeyboardMarkup(buttons)

def home_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="start_new")],
        [InlineKeyboardButton("📊 My Score", callback_data="myscore")],
        [InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")]
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

    exam = q.data.replace("exam_", "")
    context.user_data.clear()
    context.user_data["exam"] = exam

    cur.execute("SELECT COUNT(*) FROM mcq WHERE exam=?", (exam,))
    if cur.fetchone()[0] == 0:
        await safe_edit_or_send(q, "❌ इस Exam में प्रश्न नहीं हैं।", home_kb())
        return

    await safe_edit_or_send(q, "Choose Topic 👇", topic_kb(exam))

# ================= TOPIC =================
async def topic_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    exam = context.user_data.get("exam")
    topic = q.data.replace("topic_", "")

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
        "attempts": [],
        "timer_task": None
    })

    await send_mcq(q, context)
# ================= PART 2 / 3 =================
# MCQ Engine, Timer, Result, Review, Wrong-only

# ================= TIMER =================
async def question_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    q = job.data["query"]
    context.user_data["q_no"] += 1
    context.user_data["attempts"].append({
        "question": context.user_data["current"][3],
        "correct": context.user_data["current"][8],
        "explanation": context.user_data["current"][9],
        "selected": "⏱ Time Up"
    })
    await send_mcq(q, context)

# ================= SEND MCQ =================
async def send_mcq(q, context):
    exam = context.user_data["exam"]
    topic = context.user_data["topic"]
    asked = context.user_data["asked"]

    # cancel old timer
    if context.user_data.get("timer_task"):
        context.user_data["timer_task"].schedule_removal()

    if asked:
        ph = ",".join("?" * len(asked))
        cur.execute(
            f"""SELECT * FROM mcq
                WHERE exam=? AND topic=? AND id NOT IN ({ph})
                ORDER BY RANDOM() LIMIT 1""",
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
        f"A. {mcq[4]}\nB. {mcq[5]}\nC. {mcq[6]}\nD. {mcq[7]}\n\n"
        f"⏱ *Time:* {QUESTION_TIME} sec",
        InlineKeyboardMarkup([
            [
                InlineKeyboardButton("A", callback_data="ans_A"),
                InlineKeyboardButton("B", callback_data="ans_B")
            ],
            [
                InlineKeyboardButton("C", callback_data="ans_C"),
                InlineKeyboardButton("D", callback_data="ans_D")
            ],
            [
                InlineKeyboardButton("⬅️ Home", callback_data="start_new")
            ]
        ])
    )

    # start timer
    context.user_data["timer_task"] = context.application.job_queue.run_once(
        question_timeout,
        QUESTION_TIME,
        data={"query": q},
        chat_id=q.message.chat_id
    )

# ================= ANSWER =================
async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if context.user_data.get("timer_task"):
        context.user_data["timer_task"].schedule_removal()

    mcq = context.user_data["current"]
    selected = q.data.split("_")[1]

    attempt = {
        "question": mcq[3],
        "correct": mcq[8],
        "explanation": mcq[9],
        "selected": selected
    }
    context.user_data["attempts"].append(attempt)

    if selected == mcq[8]:
        context.user_data["score"] += 1
    else:
        context.user_data["wrong"].append(mcq)

    context.user_data["q_no"] += 1
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
        f"🎯 *Test Completed*\n\n"
        f"Score: *{context.user_data['score']}/{context.user_data['q_no']}*",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Review All Questions", callback_data="review_all")],
            [InlineKeyboardButton("❌ Wrong Only Practice", callback_data="wrong_only")],
            [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
            [InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )

# ================= REVIEW ALL =================
async def review_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    text = "📋 *Review – All Questions*\n\n"
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
        await safe_edit_or_send(q, "✅ Wrong Practice Completed", home_kb())
        return

    w = wrong[idx]
    await safe_edit_or_send(
        q,
        f"❌ *Wrong {idx+1}/{len(wrong)}*\n\n{w[3]}\n\n"
        f"A. {w[4]}\nB. {w[5]}\nC. {w[6]}\nD. {w[7]}\n\n"
        f"✅ Correct: *{w[8]}*\n📘 {w[9]}",
        InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⬅️ Prev", callback_data="wrong_prev"),
                InlineKeyboardButton("➡️ Next", callback_data="wrong_next")
            ],
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
# ================= PART 3 / 3 =================
# Admin Panel, Leaderboard, PDF, Export, Final Handlers

QUESTION_TIME = 20  # seconds per question

# ================= LEADERBOARD =================
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    exam = context.user_data.get("exam")
    topic = context.user_data.get("topic")

    cur.execute("""
        SELECT user_id, MAX(score) as best
        FROM scores
        WHERE exam=? AND topic=?
        GROUP BY user_id
        ORDER BY best DESC
        LIMIT 10
    """, (exam, topic))

    rows = cur.fetchall()
    if not rows:
        await safe_edit_or_send(q, "❌ No leaderboard data yet.", home_kb())
        return

    text = f"🏆 *Leaderboard – {exam} / {topic}*\n\n"
    for i, r in enumerate(rows, 1):
        text += f"{i}. User `{r[0]}` → {r[1]}\n"

    await safe_edit_or_send(q, text, home_kb())

# ================= PDF (Hindi – Stable) =================
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
    styles.add(ParagraphStyle(name="Hindi", fontName="Hindi", fontSize=11, leading=16))
    styles.add(ParagraphStyle(name="HindiTitle", fontName="Hindi", fontSize=16, leading=22))

    story = []
    story.append(Paragraph("MyScoreCard – टेस्ट परिणाम", styles["HindiTitle"]))
    story.append(Spacer(1, 10))
    story.append(Paragraph(f"परीक्षा : {exam}", styles["Hindi"]))
    story.append(Paragraph(f"विषय : {topic}", styles["Hindi"]))
    story.append(Paragraph(f"स्कोर : {score}/{total}", styles["Hindi"]))
    story.append(Spacer(1, 14))

    for i, a in enumerate(attempts, 1):
        story.append(Paragraph(f"<b>प्रश्न {i} :</b> {a['question']}", styles["Hindi"]))
        story.append(Paragraph(f"<b>आपका उत्तर :</b> {a['selected']}", styles["Hindi"]))
        story.append(Paragraph(f"<b>सही उत्तर :</b> {a['correct']}", styles["Hindi"]))
        story.append(Paragraph(f"<b>व्याख्या :</b> {a['explanation']}", styles["Hindi"]))
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

    await context.bot.send_document(
        chat_id=q.from_user.id,
        document=open(file, "rb"),
        filename=file
    )

    await context.bot.send_message(
        chat_id=q.from_user.id,
        text="📄 *PDF Generated Successfully*",
        parse_mode="Markdown",
        reply_markup=home_kb()
    )

# ================= ADMIN DASHBOARD =================
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
            [InlineKeyboardButton("🧾 Export MCQ DB", callback_data="admin_export")]
        ])
    )

# ================= EXPORT MCQ DB =================
async def admin_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    df = pd.read_sql_query("SELECT * FROM mcq", conn)
    file = "MCQ_Database.xlsx"
    df.to_excel(file, index=False)

    await context.bot.send_document(
        chat_id=q.from_user.id,
        document=open(file, "rb"),
        filename=file
    )

# ================= FINAL HANDLERS =================
def register_final_handlers(app):
    app.add_handler(CallbackQueryHandler(leaderboard, "^leaderboard$"))
    app.add_handler(CallbackQueryHandler(review_all, "^review_all$"))
    app.add_handler(CallbackQueryHandler(admin_export, "^admin_export$"))
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

    # ✅ ADD THIS LINE
    #register_final_handlers(app)

    print("🤖 Bot Running...")
    app.run_polling()

# ================= MAIN EXTENSION =================
# add this inside main() AFTER building app
# register_final_handlers(app)
if __name__ == "__main__":
    main()

