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
TOKEN = os.getenv("BOT_TOKEN")        # export BOT_TOKEN=xxxx
ADMIN_IDS = [1977205811]              # 👈 अपनी Telegram numeric ID

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
def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def home_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 Start New Test", callback_data="start_new")],
        [InlineKeyboardButton("📊 My Score", callback_data="myscore")]
    ])


def post_pdf_keyboard(has_wrong: bool):
    kb = []
    if has_wrong:
        kb.append([InlineKeyboardButton("❌ Wrong-Only Practice", callback_data="wrong_only")])
    kb.extend([
        [InlineKeyboardButton("📊 My Score", callback_data="myscore")],
        [InlineKeyboardButton("🔁 Start New Test", callback_data="start_new")]
    ])
    return InlineKeyboardMarkup(kb)

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("📘 MPPSC", callback_data="exam_MPPSC")],
        [InlineKeyboardButton("📕 UGC NET", callback_data="exam_NET")]
    ]
    await update.message.reply_text(
        "👋 *Welcome to MyScoreCard Bot*\n\nSelect Exam 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ================= START NEW =================
async def start_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    await q.edit_message_text(
        "🔁 *Start New Test*\n\nSelect Exam 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📘 MPPSC", callback_data="exam_MPPSC")],
            [InlineKeyboardButton("📕 UGC NET", callback_data="exam_NET")]
        ])
    )

# ================= EXAM =================
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

# ================= TOPIC =================
async def topic_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    exam = context.user_data["exam"]
    topic = q.data.split("_")[1]

    cur.execute("SELECT COUNT(*) FROM mcq WHERE exam=? AND topic=?", (exam, topic))
    total_q = cur.fetchone()[0]

    if total_q == 0:
        await q.edit_message_text("❌ No questions available.")
        return

    context.user_data.update({
        "topic": topic,
        "score": 0,
        "q_no": 0,
        "limit": total_q,
        "asked": [],
        "attempts": [],
        "wrong": []
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
        return

    await send_mcq(q, context)

# ================= RESULT =================
async def show_result(q, context):
    score = context.user_data["score"]
    total = context.user_data["q_no"]

    cur.execute(
        "INSERT INTO scores (user_id, exam, topic, score, total, test_date) VALUES (?,?,?,?,?,?)",
        (q.from_user.id, context.user_data["exam"], context.user_data["topic"],
         score, total, datetime.date.today().isoformat())
    )
    conn.commit()

    await q.edit_message_text(
        f"🎯 *Test Completed*\n\nScore: *{score}/{total}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Wrong-Only Practice", callback_data="wrong_only")],
            [InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result")],
            [InlineKeyboardButton("📊 My Score", callback_data="myscore")],
            [InlineKeyboardButton("🔁 Start New Test", callback_data="start_new")]
        ])
    )

# ================= WRONG ONLY =================
async def wrong_only(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not context.user_data["wrong"]:
        await q.edit_message_text("🎉 No wrong questions!", reply_markup=post_pdf_keyboard(False))
        return

    context.user_data["wrong_idx"] = 0
    await show_wrong(q, context)

async def show_wrong(q, context):
    idx = context.user_data["wrong_idx"]
    wrong = context.user_data["wrong"]

    if idx >= len(wrong):
        await q.edit_message_text(
            "✅ Wrong-Only Practice Completed",
            reply_markup=post_pdf_keyboard(True)
        )
        return

    w = wrong[idx]
    await q.edit_message_text(
        f"❌ *Wrong Question {idx+1}*\n\n{w[3]}\n\n"
        f"A. {w[4]}\nB. {w[5]}\nC. {w[6]}\nD. {w[7]}\n\n"
        f"✅ Correct: {w[8]}\n\n📘 {w[9]}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Next ▶", callback_data="wrong_next")]
        ])
    )

async def wrong_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["wrong_idx"] += 1
    await show_wrong(q, context)

# ================= MY SCORE =================
async def myscore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        send = q.edit_message_text
    else:
        send = update.message.reply_text

    uid = update.effective_user.id
    cur.execute(
        "SELECT exam, topic, score, total, test_date FROM scores WHERE user_id=? ORDER BY id DESC LIMIT 5",
        (uid,)
    )
    rows = cur.fetchall()

    if not rows:
        await send("❌ No score history.", reply_markup=home_keyboard())
        return

    msg = "📊 *Your Recent Tests*\n\n"
    for r in rows:
        msg += f"{r[0]} | {r[1]} → {r[2]}/{r[3]} ({r[4]})\n"

    await send(
        msg,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result")],
            [InlineKeyboardButton("🔁 Start New Test", callback_data="start_new")]
        ])
    )

# ================= PDF (Hindi + Watermark) =================
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.colors import lightgrey

pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))

def generate_pdf(uid, exam, topic, attempts, score, total):
    file = f"result_{uid}.pdf"
    doc = SimpleDocTemplate(file, pagesize=A4)
    styles = getSampleStyleSheet()
    styles["Normal"].fontName = "HeiseiMin-W3"
    story = []

    story.append(Paragraph("📘 MyScoreCard – टेस्ट परिणाम", styles["Title"]))
    story.append(Paragraph(f"परीक्षा: {exam}", styles["Normal"]))
    story.append(Paragraph(f"विषय: {topic}", styles["Normal"]))
    story.append(Paragraph(f"स्कोर: {score}/{total}", styles["Normal"]))
    story.append(Spacer(1, 20))

    for i, a in enumerate(attempts, 1):
        story.append(Paragraph(f"<b>प्रश्न {i}:</b> {a['question']}", styles["Normal"]))
        for k, v in a["options"].items():
            story.append(Paragraph(f"{k}. {v}", styles["Normal"]))
        story.append(Paragraph(f"सही उत्तर: {a['correct']}", styles["Normal"]))
        story.append(Paragraph(f"व्याख्या: {a['explanation']}", styles["Normal"]))
        story.append(Spacer(1, 15))

    def watermark(c, d):
        c.saveState()
        c.setFont("HeiseiMin-W3", 40)
        c.setFillColor(lightgrey)
        c.translate(300, 400)
        c.rotate(45)
        c.drawCentredString(0, 0, "MyScoreCard")
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
        filename="MyScoreCard_Result.pdf"
    )

    await q.edit_message_text(
        "✅ *PDF Generated Successfully*",
        parse_mode="Markdown",
        reply_markup=post_pdf_keyboard(len(context.user_data["wrong"]) > 0)
    )

# ================= ADMIN + EXCEL =================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    cur.execute("SELECT COUNT(*) FROM mcq")
    mcq = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM scores")
    tests = cur.fetchone()[0]

    await update.message.reply_text(
        f"🛠 ADMIN DASHBOARD\n\nMCQs: {mcq}\nTests: {tests}\n\n/upload – Upload Excel"
    )

async def upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "📤 Upload Excel (.xlsx)\nColumns:\nexam, topic, question, a, b, c, d, correct, explanation"
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

    await update.message.reply_text(f"✅ {len(df)} MCQs uploaded")

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
    app.add_handler(CallbackQueryHandler(pdf_result, "^pdf_result$"))

    print("🤖 MyScoreCard Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
