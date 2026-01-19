import os
import sqlite3
import datetime
import pandas as pd
import unicodedata

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [1977205811]   # <-- अपनी Telegram numeric ID

# ================= DATABASE =================
conn = sqlite3.connect("mcq.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS mcq (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam TEXT, topic TEXT, question TEXT,
    a TEXT, b TEXT, c TEXT, d TEXT,
    correct TEXT, explanation TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    exam TEXT, topic TEXT,
    score INTEGER, total INTEGER,
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

def safe_hindi(t):
    return unicodedata.normalize("NFKC", str(t)) if t else ""

def is_admin(uid):
    return uid in ADMIN_IDS

# ================= KEYBOARDS =================
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

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Upload Excel", callback_data="admin_upload")],
        [InlineKeyboardButton("📊 Subject Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("📥 Download Excel", callback_data="admin_dl_excel")],
        [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
    ])

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 *Welcome to MyScoreCard Bot*\n\nSelect Exam 👇",
        parse_mode="Markdown", reply_markup=exam_kb()
    )

async def start_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    await safe_edit_or_send(q, "👋 *Welcome*\n\nSelect Exam 👇", exam_kb())

# ================= EXAM =================
async def exam_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    exam = q.data.split("_")[1]
    context.user_data.clear()
    context.user_data["exam"] = exam

    cur.execute("SELECT DISTINCT topic FROM mcq WHERE exam=?", (exam,))
    topics = cur.fetchall()

    if not topics:
        await safe_edit_or_send(q, "❌ No questions found.", home_kb())
        return

    buttons = [[InlineKeyboardButton(t[0], callback_data=f"topic_{t[0]}")] for t in topics]
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="start_new")])

    await safe_edit_or_send(q, "Choose Topic 👇", InlineKeyboardMarkup(buttons))

# ================= TOPIC =================
async def topic_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    topic = q.data.split("_", 1)[1]
    exam = context.user_data.get("exam")

    cur.execute("SELECT COUNT(*) FROM mcq WHERE exam=? AND topic=?", (exam, topic))
    total = cur.fetchone()[0]

    context.user_data.update({
        "topic": topic, "score": 0, "q_no": 0,
        "asked": [], "wrong": [], "attempts": [], "limit": total
    })

    await send_mcq(q, context)

# ================= MCQ =================
async def send_mcq(q, context):
    asked = context.user_data["asked"]
    exam = context.user_data["exam"]
    topic = context.user_data["topic"]

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

    await safe_edit_or_send(
        q,
        f"❓ *Q{context.user_data['q_no']+1}/{context.user_data['limit']}*\n\n"
        f"{mcq[3]}\n\nA. {mcq[4]}\nB. {mcq[5]}\nC. {mcq[6]}\nD. {mcq[7]}",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("A", callback_data="ans_A"),
             InlineKeyboardButton("B", callback_data="ans_B")],
            [InlineKeyboardButton("C", callback_data="ans_C"),
             InlineKeyboardButton("D", callback_data="ans_D")]
        ])
    )

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
            [InlineKeyboardButton("❌ Wrong Only", callback_data="wrong_only")],
            [InlineKeyboardButton("📄 PDF", callback_data="pdf_result")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )

# ================= WRONG ONLY =================
async def wrong_only(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
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
        f"{w[3]}\n\n✅ {w[8]}\n📘 {w[9]}",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Prev", callback_data="wrong_prev"),
             InlineKeyboardButton("➡️ Next", callback_data="wrong_next")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )

async def wrong_next(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["widx"] += 1
    await show_wrong(q, context)

async def wrong_prev(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["widx"] -= 1
    await show_wrong(q, context)

# ================= PDF (HINDI – FINAL STABLE) =================
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.pagesizes import A4

pdfmetrics.registerFont(TTFont("Hindi", "NotoSansDevanagari-Regular.ttf"))

def generate_pdf(uid, data):
    file = f"Result_{uid}.pdf"
    doc = SimpleDocTemplate(file, pagesize=A4)
    style = ParagraphStyle("h", fontName="Hindi", fontSize=11, leading=16)

    story = []
    for i, a in enumerate(data, 1):
        story.append(Paragraph(f"<b>प्रश्न {i}:</b> {safe_hindi(a['question'])}", style))
        story.append(Paragraph(f"<b>उत्तर:</b> {safe_hindi(a['correct'])}", style))
        story.append(Paragraph(f"<b>व्याख्या:</b> {safe_hindi(a['explanation'])}", style))
        story.append(Spacer(1, 12))

    doc.build(story)
    return file

async def pdf_result(update, context):
    q = update.callback_query
    await q.answer()

    file = generate_pdf(q.from_user.id, context.user_data["attempts"])
    await context.bot.send_document(q.from_user.id, open(file, "rb"))
    await context.bot.send_message(q.from_user.id, "📄 PDF Ready", reply_markup=home_kb())

# ================= ADMIN =================
async def admin(update, context):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("🧑‍💼 Admin Panel", reply_markup=admin_kb())

async def admin_stats(update, context):
    q = update.callback_query
    await q.answer()

    cur.execute("SELECT exam, topic, COUNT(*) FROM mcq GROUP BY exam, topic")
    rows = cur.fetchall()

    msg = "📊 Stats\n\n"
    for e, t, c in rows:
        msg += f"{e} | {t} → {c}\n"

    await safe_edit_or_send(q, msg, admin_kb())

async def admin_dl_excel(update, context):
    q = update.callback_query
    await q.answer()

    df = pd.read_sql("SELECT * FROM mcq", conn)
    file = "All_MCQs.xlsx"
    df.to_excel(file, index=False)
    await context.bot.send_document(q.from_user.id, open(file, "rb"))

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))

    app.add_handler(CallbackQueryHandler(start_new, "^start_new$"))
    app.add_handler(CallbackQueryHandler(exam_select, "^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select, "^topic_"))
    app.add_handler(CallbackQueryHandler(answer, "^ans_"))
    app.add_handler(CallbackQueryHandler(wrong_only, "^wrong_only$"))
    app.add_handler(CallbackQueryHandler(wrong_next, "^wrong_next$"))
    app.add_handler(CallbackQueryHandler(wrong_prev, "^wrong_prev$"))
    app.add_handler(CallbackQueryHandler(pdf_result, "^pdf_result$"))
    app.add_handler(CallbackQueryHandler(admin_stats, "^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_dl_excel, "^admin_dl_excel$"))

    print("🤖 BOT RUNNING")
    app.run_polling()

if __name__ == "__main__":
    main()
