# ================= IMPORTS =================
import os, sqlite3, datetime, unicodedata
import pandas as pd

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

def safe_hindi(t):
    return unicodedata.normalize("NFKC", str(t)) if t else ""

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
    rows = cur.fetchall()
    kb = [[InlineKeyboardButton(r[0], callback_data=f"topic_{r[0]}")] for r in rows]
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="start_new")])
    return InlineKeyboardMarkup(kb)

def home_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="start_new")],
        [InlineKeyboardButton("📊 My Score", callback_data="myscore")],
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
    if not exam:
        await safe_edit_or_send(q, "⚠️ Session expired", home_kb())
        return

    cur.execute("SELECT COUNT(*) FROM mcq WHERE exam=? AND topic=?", (exam, topic))
    total = cur.fetchone()[0]
    if total == 0:
        await safe_edit_or_send(q, "❌ No MCQs in this topic", home_kb())
        return

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
        cur.execute("SELECT * FROM mcq WHERE exam=? AND topic=? ORDER BY RANDOM() LIMIT 1", (exam, topic))

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
    sel = q.data.split("_")[1]

    context.user_data["attempts"].append({
        "question": mcq[3], "correct": mcq[8], "explanation": mcq[9]
    })

    if sel == mcq[8]:
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
        (q.from_user.id, context.user_data["exam"], context.user_data["topic"],
         context.user_data["score"], context.user_data["q_no"],
         datetime.date.today().isoformat())
    )
    conn.commit()

    await safe_edit_or_send(
        q,
        f"🎯 *Test Completed*\n\nScore: *{context.user_data['score']}/{context.user_data['q_no']}*",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Wrong Practice", callback_data="wrong_only")],
            [InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )

# ================= WRONG ONLY =================
async def wrong_only(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not context.user_data.get("wrong"):
        await safe_edit_or_send(q, "🎉 No wrong questions", home_kb())
        return
    context.user_data["widx"] = 0
    await show_wrong(q, context)

async def show_wrong(q, context):
    w = context.user_data["wrong"]
    i = context.user_data["widx"]
    if i >= len(w):
        await safe_edit_or_send(q, "✅ Completed", home_kb())
        return
    m = w[i]
    await safe_edit_or_send(
        q,
        f"❌ *Wrong {i+1}/{len(w)}*\n\n{m[3]}\n\n✅ {m[8]}\n📘 {m[9]}",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Prev", callback_data="wrong_prev"),
             InlineKeyboardButton("➡️ Next", callback_data="wrong_next")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )

async def wrong_next(update, context):
    q = update.callback_query; await q.answer()
    context.user_data["widx"] += 1
    await show_wrong(q, context)

async def wrong_prev(update, context):
    q = update.callback_query; await q.answer()
    context.user_data["widx"] = max(0, context.user_data["widx"] - 1)
    await show_wrong(q, context)

# ================= MY SCORE =================
async def myscore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    send = update.message.reply_text if update.message else update.callback_query.edit_message_text
    cur.execute(
        "SELECT exam,topic,score,total,test_date FROM scores WHERE user_id=? ORDER BY id DESC LIMIT 5",
        (update.effective_user.id,)
    )
    rows = cur.fetchall()
    if not rows:
        await send("❌ No score history", reply_markup=home_kb())
        return
    msg = "📊 *Recent Tests*\n\n"
    for r in rows:
        msg += f"{r[0]} | {r[1]} → {r[2]}/{r[3]} ({r[4]})\n"
    await send(msg, parse_mode="Markdown", reply_markup=home_kb())

# ================= PDF (HINDI SAFE) =================
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

pdfmetrics.registerFont(TTFont("Hindi", "NotoSansDevanagari-Regular.ttf"))

def generate_pdf(uid, exam, topic, attempts, score, total):
    f = f"MyScoreCard_{uid}.pdf"
    doc = SimpleDocTemplate(f, pagesize=A4)
    st = getSampleStyleSheet()
    st.add(ParagraphStyle("H", fontName="Hindi", fontSize=11, leading=16))
    st.add(ParagraphStyle("T", fontName="Hindi", fontSize=16))
    s = [Paragraph("MyScoreCard – टेस्ट परिणाम", st["T"]), Spacer(1,10)]
    s += [
        Paragraph(f"परीक्षा : {safe_hindi(exam)}", st["H"]),
        Paragraph(f"विषय : {safe_hindi(topic)}", st["H"]),
        Paragraph(f"स्कोर : {score}/{total}", st["H"]), Spacer(1,10)
    ]
    for i,a in enumerate(attempts,1):
        s.append(Paragraph(f"प्रश्न {i}: {safe_hindi(a['question'])}", st["H"]))
        s.append(Paragraph(f"उत्तर: {safe_hindi(a['correct'])}", st["H"]))
        s.append(Paragraph(f"व्याख्या: {safe_hindi(a['explanation'])}", st["H"]))
        s.append(Spacer(1,8))
    doc.build(s)
    return f

async def pdf_result(update, context):
    q = update.callback_query; await q.answer()
    f = generate_pdf(
        q.from_user.id,
        context.user_data["exam"],
        context.user_data["topic"],
        context.user_data["attempts"],
        context.user_data["score"],
        context.user_data["q_no"]
    )
    await context.bot.send_document(q.from_user.id, open(f,"rb"), filename=f)
    await context.bot.send_message(q.from_user.id, "📄 PDF Generated", reply_markup=home_kb())

# ================= ADMIN =================
async def admin(update, context):
    if not is_admin(update.effective_user.id): return
    cur.execute("SELECT exam,COUNT(*) FROM mcq GROUP BY exam")
    msg = "🛠 *ADMIN DASHBOARD*\n\n"
    for e,c in cur.fetchall():
        msg += f"{e} : {c} MCQs\n"
    msg += "\n/upload – Upload Excel\n/export – Download DB"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def export_db(update, context):
    if not is_admin(update.effective_user.id): return
    df = pd.read_sql("SELECT * FROM mcq", conn)
    path = "MCQ_DATABASE.xlsx"
    df.to_excel(path, index=False)
    await update.message.reply_document(open(path,"rb"), filename=path)

async def upload(update, context):
    if not is_admin(update.effective_user.id): return
    await update.message.reply_text("Upload Excel with columns:\nexam,topic,question,a,b,c,d,correct,explanation")

async def handle_excel(update, context):
    if not is_admin(update.effective_user.id): return
    f = await update.message.document.get_file()
    await f.download_to_drive("upload.xlsx")
    df = pd.read_excel("upload.xlsx")
    required = {"exam","topic","question","a","b","c","d","correct","explanation"}
    if not required.issubset(df.columns):
        await update.message.reply_text("❌ Invalid Excel format")
        return
    for _,r in df.iterrows():
        cur.execute("INSERT INTO mcq VALUES(NULL,?,?,?,?,?,?,?,?,?)",
            (r.exam,r.topic,r.question,r.a,r.b,r.c,r.d,r.correct,r.explanation))
    conn.commit()
    await update.message.reply_text(f"✅ {len(df)} MCQs added")

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myscore", myscore))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("upload", upload))
    app.add_handler(CommandHandler("export", export_db))

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
