# ================= IMPORTS =================
import os, sqlite3, datetime, pandas as pd, unicodedata, tempfile
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from telegram.error import BadRequest

# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [1977205811]   # 👈 अपनी Telegram numeric ID

# ================= DATABASE =================
conn = sqlite3.connect("mcq.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS mcq (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam TEXT,
    topic TEXT,
    question TEXT,
    a TEXT, b TEXT, c TEXT, d TEXT,
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
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return
        try:
            await q.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except:
            pass

def safe_hindi(text):
    return unicodedata.normalize("NFKC", str(text)) if text else ""

def is_admin(uid):
    return uid in ADMIN_IDS

# ================= UI HELPERS =================
def home_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="start_new")],
        [InlineKeyboardButton("📊 My Score", callback_data="myscore")],
        [InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result")]
    ])

def exam_kb():
    cur.execute("SELECT DISTINCT exam FROM mcq")
    exams = [r[0] for r in cur.fetchall()]
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(e, callback_data=f"exam_{e}")] for e in exams] +
        ([[InlineKeyboardButton("🛠 Admin", callback_data="admin_panel")]] if exams else [])
    )

def topic_kb(exam):
    cur.execute("SELECT DISTINCT topic FROM mcq WHERE exam=?", (exam,))
    topics = [r[0] for r in cur.fetchall()]
    kb = [[InlineKeyboardButton(t, callback_data=f"topic_{t}")] for t in topics]
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="start_new")])
    return InlineKeyboardMarkup(kb)

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
    context.user_data.update({
        "topic": topic, "score": 0, "q_no": 0,
        "limit": total, "asked": [], "wrong": [], "attempts": []
    })
    await send_mcq(q, context)

# ================= MCQ FLOW =================
async def send_mcq(q, context):
    exam, topic = context.user_data["exam"], context.user_data["topic"]
    asked = context.user_data["asked"]

    if asked:
        ph = ",".join("?" * len(asked))
        cur.execute(
            f"SELECT * FROM mcq WHERE exam=? AND topic=? AND id NOT IN ({ph}) ORDER BY RANDOM() LIMIT 1",
            [exam, topic] + asked
        )
    else:
        cur.execute("SELECT * FROM mcq WHERE exam=? AND topic=? ORDER BY RANDOM() LIMIT 1",
                    (exam, topic))

    mcq = cur.fetchone()
    if not mcq:
        await show_result(q, context)
        return

    context.user_data["asked"].append(mcq[0])
    context.user_data["current"] = mcq

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
        "explanation": mcq[9],
        "chosen": selected
    })

    if selected != mcq[8]:
        context.user_data["wrong"].append(mcq)
    else:
        context.user_data["score"] += 1

    context.user_data["q_no"] += 1
    await send_mcq(q, context)

# ================= RESULT + REVIEW =================
async def show_result(q, context):
    cur.execute(
        "INSERT INTO scores VALUES (NULL,?,?,?,?,?,?)",
        (q.from_user.id, context.user_data["exam"],
         context.user_data["topic"], context.user_data["score"],
         context.user_data["q_no"], datetime.date.today().isoformat())
    )
    conn.commit()

    await safe_edit_or_send(
        q,
        f"🎯 *Test Completed*\n\nScore: *{context.user_data['score']}/{context.user_data['q_no']}*",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Review All Questions", callback_data="review_all")],
            [InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )

async def review_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["review_idx"] = 0
    await show_review(q, context)

async def show_review(q, context):
    i = context.user_data["review_idx"]
    data = context.user_data["attempts"]
    if i >= len(data):
        await safe_edit_or_send(q, "✅ Review Completed", home_kb())
        return

    a = data[i]
    await safe_edit_or_send(
        q,
        f"*Q{i+1}*\n{a['question']}\n\n"
        f"Your: {a['chosen']} | Correct: {a['correct']}\n\n📘 {a['explanation']}",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Prev", callback_data="rev_prev"),
             InlineKeyboardButton("➡️ Next", callback_data="rev_next")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )

async def rev_next(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["review_idx"] += 1
    await show_review(q, context)

async def rev_prev(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["review_idx"] = max(0, context.user_data["review_idx"] - 1)
    await show_review(q, context)

# ================= MY SCORE =================
async def myscore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cur.execute("SELECT exam, topic, score, total FROM scores WHERE user_id=? ORDER BY id DESC LIMIT 5", (uid,))
    rows = cur.fetchall()
    msg = "📊 *Your Recent Tests*\n\n"
    for r in rows:
        msg += f"{r[0]} | {r[1]} → {r[2]}/{r[3]}\n"
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=home_kb())

# ================= PDF (HINDI SAFE) =================
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4

pdfmetrics.registerFont(TTFont("Hindi", "NotoSansDevanagari-Regular.ttf"))

def generate_pdf(uid, context):
    file = f"MyScore_{uid}.pdf"
    doc = SimpleDocTemplate(file, pagesize=A4)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H", fontName="Hindi", fontSize=11))
    story = [Paragraph("MyScoreCard – टेस्ट परिणाम", styles["H"]), Spacer(1, 10)]

    for i, a in enumerate(context.user_data["attempts"], 1):
        story.append(Paragraph(f"प्रश्न {i}: {safe_hindi(a['question'])}", styles["H"]))
        story.append(Paragraph(f"सही: {a['correct']}", styles["H"]))
        story.append(Paragraph(f"व्याख्या: {safe_hindi(a['explanation'])}", styles["H"]))
        story.append(Spacer(1, 8))

    doc.build(story)
    return file

async def pdf_result(update, context):
    q = update.callback_query
    await q.answer()
    file = generate_pdf(q.from_user.id, context)
    await context.bot.send_document(q.from_user.id, open(file, "rb"))

# ================= ADMIN PANEL =================
async def admin_panel(update, context):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id): return
    await safe_edit_or_send(
        q,
        "🛠 *Admin Dashboard*",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Upload Excel", callback_data="admin_upload")],
            [InlineKeyboardButton("🧾 Export Excel", callback_data="admin_export_excel")],
            [InlineKeyboardButton("⬅️ Back", callback_data="start_new")]
        ])
    )

async def admin_export_excel(update, context):
    q = update.callback_query
    await q.answer()
    df = pd.read_sql("SELECT * FROM mcq", conn)
    path = tempfile.mktemp(".xlsx")
    df.to_excel(path, index=False)
    await context.bot.send_document(q.from_user.id, open(path, "rb"))

# ================= EXCEL UPLOAD =================
async def upload(update, context):
    if not is_admin(update.effective_user.id): return
    file = await update.message.document.get_file()
    path = tempfile.mktemp(".xlsx")
    await file.download_to_drive(path)
    df = pd.read_excel(path)
    for _, r in df.iterrows():
        cur.execute(
            "INSERT INTO mcq VALUES (NULL,?,?,?,?,?,?,?,?,?)",
            (r.exam, r.topic, r.question, r.a, r.b, r.c, r.d, r.correct, r.explanation)
        )
    conn.commit()
    await update.message.reply_text("✅ MCQs Uploaded")

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myscore", myscore))
    app.add_handler(CommandHandler("upload", upload))

    app.add_handler(CallbackQueryHandler(start_new, "^start_new$"))
    app.add_handler(CallbackQueryHandler(exam_select, "^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select, "^topic_"))
    app.add_handler(CallbackQueryHandler(answer, "^ans_"))
    app.add_handler(CallbackQueryHandler(review_all, "^review_all$"))
    app.add_handler(CallbackQueryHandler(rev_next, "^rev_next$"))
    app.add_handler(CallbackQueryHandler(rev_prev, "^rev_prev$"))
    app.add_handler(CallbackQueryHandler(pdf_result, "^pdf_result$"))
    app.add_handler(CallbackQueryHandler(admin_panel, "^admin_panel$"))
    app.add_handler(CallbackQueryHandler(admin_export_excel, "^admin_export_excel$"))

    print("🤖 Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
