# ================= FINAL MERGED MCQ BOT =================
# All features included | No dead ends | Production safe

import os, sqlite3, datetime, unicodedata, pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from telegram.error import BadRequest

# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [1977205811]
QUESTION_TIME = 30  # seconds

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
 user_id INTEGER, exam TEXT, topic TEXT,
 score INTEGER, total INTEGER, test_date TEXT
)
""")
conn.commit()
# ================= SAFE TIMER CANCEL =================
def cancel_timer(ctx):
    job = ctx.user_data.get("timer")
    if job:
        try:
            job.schedule_removal()
        except Exception:
            pass
        ctx.user_data["timer"] = None

# ================= HELPERS =================
def is_admin(uid): return uid in ADMIN_IDS

def safe_hindi(t): return unicodedata.normalize("NFKC", str(t)) if t else ""

async def safe_edit_or_send(q, text, kb=None):
    try:
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return
        try:
            await q.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
        except:
            pass

# ================= UI =================
def home_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="start_new")],
        [InlineKeyboardButton("📊 My Score", callback_data="myscore")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
        [InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result")]
    ])

def exam_kb():
    cur.execute("SELECT DISTINCT exam FROM mcq")
    exams = [r[0] for r in cur.fetchall()]
    return InlineKeyboardMarkup([[InlineKeyboardButton(e, callback_data=f"exam_{e}")] for e in exams]) \
        if exams else InlineKeyboardMarkup([[InlineKeyboardButton("No Exam", callback_data="noop")]])

def topic_kb(exam):
    cur.execute("SELECT DISTINCT topic FROM mcq WHERE exam=?", (exam,))
    t = [r[0] for r in cur.fetchall()]
    btn = [[InlineKeyboardButton(x, callback_data=f"topic_{x}")] for x in t]
    btn.append([InlineKeyboardButton("⬅️ Back", callback_data="start_new")])
    return InlineKeyboardMarkup(btn)

# ================= START =================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("👋 *Select Exam*", parse_mode="Markdown", reply_markup=exam_kb())

async def start_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data.clear()
    await safe_edit_or_send(q, "👋 *Select Exam*", exam_kb())

# ================= EXAM / TOPIC =================
async def exam_select(update: Update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data.clear()
    ctx.user_data["exam"] = q.data.replace("exam_", "")
    await safe_edit_or_send(q, "Choose Topic 👇", topic_kb(ctx.user_data["exam"]))

async def topic_select(update: Update, ctx):
    q = update.callback_query; await q.answer()
    exam = ctx.user_data.get("exam")
    topic = q.data.replace("topic_", "")
    if not exam:
        await safe_edit_or_send(q, "⚠️ Session expired", home_kb()); return

    cur.execute("SELECT COUNT(*) FROM mcq WHERE exam=? AND topic=?", (exam, topic))
    total = cur.fetchone()[0]
    if total == 0:
        await safe_edit_or_send(q, "❌ No questions", home_kb()); return

    ctx.user_data.update({
        "topic": topic, "score": 0, "q_no": 0,
        "limit": total, "asked": [], "wrong": [],
        "attempts": [], "timer": None
    })
    await send_mcq(q, ctx)

# ================= TIMER =================
async def timeout(ctx: ContextTypes.DEFAULT_TYPE):
    if "current" not in ctx.user_data: return
    q = ctx.job.data["q"]
    m = ctx.user_data["current"]
    ctx.user_data["attempts"].append({
        "question": m[3], "correct": m[8],
        "explanation": m[9], "selected": "⏱ Time Up"
    })
    ctx.user_data["q_no"] += 1
    await send_mcq(q, ctx)

# ================= MCQ =================
async def send_mcq(q, ctx):
    if ctx.user_data.get("timer"):
        ctx.user_data["timer"].cancel_timer(ctx)

    exam, topic = ctx.user_data["exam"], ctx.user_data["topic"]
    asked = ctx.user_data["asked"]

    if asked:
        ph = ",".join("?" * len(asked))
        cur.execute(f"SELECT * FROM mcq WHERE exam=? AND topic=? AND id NOT IN ({ph}) ORDER BY RANDOM() LIMIT 1",
                    [exam, topic] + asked)
    else:
        cur.execute("SELECT * FROM mcq WHERE exam=? AND topic=? ORDER BY RANDOM() LIMIT 1", (exam, topic))

    m = cur.fetchone()
    if not m:
        await show_result(q, ctx); return

    ctx.user_data["current"] = m
    ctx.user_data["asked"].append(m[0])

    await safe_edit_or_send(
        q,
        f"❓ *Q{ctx.user_data['q_no']+1}/{ctx.user_data['limit']}*\n\n{m[3]}\n\n"
        f"A. {m[4]}\nB. {m[5]}\nC. {m[6]}\nD. {m[7]}\n\n⏱ {QUESTION_TIME}s",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("A", callback_data="ans_A"),
             InlineKeyboardButton("B", callback_data="ans_B")],
            [InlineKeyboardButton("C", callback_data="ans_C"),
             InlineKeyboardButton("D", callback_data="ans_D")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )

    ctx.user_data["timer"] = ctx.application.job_queue.run_once(
        timeout, QUESTION_TIME, data={"q": q}, chat_id=q.message.chat_id
    )

async def answer(update: Update, ctx):
    q = update.callback_query; await q.answer()
    if ctx.user_data.get("timer"):
        ctx.user_data["timer"].cancel_timer(ctx)

    m = ctx.user_data["current"]
    sel = q.data.split("_")[1]

    ctx.user_data["attempts"].append({
        "question": m[3], "correct": m[8],
        "explanation": m[9], "selected": sel
    })

    if sel == m[8]: ctx.user_data["score"] += 1
    else: ctx.user_data["wrong"].append(m)

    ctx.user_data["q_no"] += 1
    await send_mcq(q, ctx)

# ================= RESULT =================
async def show_result(q, ctx):
    cur.execute(
        "INSERT INTO scores VALUES (NULL,?,?,?,?,?,?)",
        (q.from_user.id, ctx.user_data["exam"], ctx.user_data["topic"],
         ctx.user_data["score"], ctx.user_data["q_no"],
         datetime.date.today().isoformat())
    )
    conn.commit()

    await safe_edit_or_send(
        q,
        f"🎯 *Test Completed*\n\nScore: *{ctx.user_data['score']}/{ctx.user_data['q_no']}*",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Review All", callback_data="review_all")],
            [InlineKeyboardButton("❌ Wrong Only", callback_data="wrong_only")],
            [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
            [InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )

# ================= REVIEW / WRONG =================
async def review_all(update, ctx):
    q = update.callback_query; await q.answer()
    text = "📋 *Review All*\n\n"
    for i,a in enumerate(ctx.user_data.get("attempts", []),1):
        text += f"*Q{i}.* {a['question']}\nYour: {a['selected']} | Correct: {a['correct']}\n📘 {a['explanation']}\n\n"
    await safe_edit_or_send(q, text, home_kb())

async def wrong_only(update, ctx):
    q = update.callback_query; await q.answer()
    w = ctx.user_data.get("wrong", [])
    if not w:
        await safe_edit_or_send(q, "🎉 No wrong questions", home_kb()); return
    ctx.user_data["widx"] = 0
    await show_wrong(q, ctx)

async def show_wrong(q, ctx):
    i = ctx.user_data["widx"]
    w = ctx.user_data["wrong"]
    if i >= len(w):
        await safe_edit_or_send(q, "✅ Completed", home_kb()); return
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

async def wrong_next(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data["widx"] += 1
    await show_wrong(q, ctx)

async def wrong_prev(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data["widx"] = max(0, ctx.user_data["widx"]-1)
    await show_wrong(q, ctx)

# ================= LEADERBOARD =================
async def leaderboard(update, ctx):
    q = update.callback_query; await q.answer()
    e,t = ctx.user_data.get("exam"), ctx.user_data.get("topic")
    if not e or not t:
        await safe_edit_or_send(q, "⚠️ Take a test first", home_kb()); return
    cur.execute("""SELECT user_id, MAX(score) FROM scores
                   WHERE exam=? AND topic=? GROUP BY user_id
                   ORDER BY MAX(score) DESC LIMIT 10""",(e,t))
    rows = cur.fetchall()
    text = f"🏆 *{e}/{t}*\n\n" + "\n".join([f"{i+1}. `{r[0]}` → {r[1]}" for i,r in enumerate(rows)])
    await safe_edit_or_send(q, text or "No data", home_kb())

# ================= PDF =================
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import lightgrey

pdfmetrics.registerFont(TTFont("Hindi", "NotoSansDevanagari-Regular.ttf"))

def generate_pdf(uid, exam, topic, att, sc, tot):
    f = f"MyScoreCard_{uid}.pdf"
    d = SimpleDocTemplate(f, pagesize=A4)
    s = getSampleStyleSheet()
    s.add(ParagraphStyle(name="H", fontName="Hindi", fontSize=11))
    s.add(ParagraphStyle(name="T", fontName="Hindi", fontSize=16))
    st=[Paragraph("MyScoreCard – टेस्ट परिणाम", s["T"]), Spacer(1,10),
        Paragraph(f"परीक्षा: {exam}",s["H"]),
        Paragraph(f"विषय: {topic}",s["H"]),
        Paragraph(f"स्कोर: {sc}/{tot}",s["H"]), Spacer(1,10)]
    for i,a in enumerate(att,1):
        st+= [Paragraph(f"<b>Q{i}:</b> {a['question']}",s["H"]),
              Paragraph(f"आपका: {a['selected']} | सही: {a['correct']}",s["H"]),
              Paragraph(f"📘 {a['explanation']}",s["H"]), Spacer(1,8)]
    def wm(c,d):
        c.saveState(); c.setFont("Hindi",28); c.setFillColor(lightgrey)
        c.translate(300,420); c.rotate(45)
        c.drawCentredString(0,0,"MyScoreCard Bot"); c.restoreState()
    d.build(st,onFirstPage=wm,onLaterPages=wm)
    return f

async def pdf_result(update, ctx):
    q = update.callback_query; await q.answer()
    if "exam" not in ctx.user_data:
        await safe_edit_or_send(q,"⚠️ No active test",home_kb()); return
    f = generate_pdf(q.from_user.id, ctx.user_data["exam"],
                     ctx.user_data["topic"], ctx.user_data["attempts"],
                     ctx.user_data["score"], ctx.user_data["q_no"])
    await ctx.bot.send_document(q.from_user.id, open(f,"rb"))
    await ctx.bot.send_message(q.from_user.id,"📄 PDF Ready",reply_markup=home_kb())

# ================= ADMIN =================
async def admin(update, ctx):
    if not is_admin(update.effective_user.id): return
    cur.execute("SELECT exam, topic, COUNT(*) FROM mcq GROUP BY exam, topic")
    rows = cur.fetchall()
    t="👨‍💼 *ADMIN*\n\n"+ "\n".join([f"{r[0]}/{r[1]} → {r[2]}" for r in rows])
    await update.message.reply_text(
        t, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Upload Excel", callback_data="admin_upload")],
            [InlineKeyboardButton("🧾 Export DB", callback_data="admin_export")]
        ])
    )

async def admin_upload(update, ctx):
    q=update.callback_query; await q.answer()
    await q.message.reply_text("📤 Upload Excel (.xlsx)")

async def upload(update, ctx):
    if not is_admin(update.effective_user.id): return
    await update.message.reply_text("📤 Upload Excel (.xlsx)")

async def handle_excel(update, ctx):
    if not is_admin(update.effective_user.id): return
    f = await update.message.document.get_file()
    await f.download_to_drive("upload.xlsx")
    df=pd.read_excel("upload.xlsx")
    for _,r in df.iterrows():
        cur.execute("INSERT INTO mcq VALUES(NULL,?,?,?,?,?,?,?,?,?)",
                    (r.exam,r.topic,r.question,r.a,r.b,r.c,r.d,r.correct,r.explanation))
    conn.commit()
    await update.message.reply_text(f"✅ {len(df)} MCQs added")

async def admin_export(update, ctx):
    q=update.callback_query; await q.answer()
    df=pd.read_sql_query("SELECT * FROM mcq",conn)
    df.to_excel("MCQ_DB.xlsx",index=False)
    await ctx.bot.send_document(q.from_user.id,open("MCQ_DB.xlsx","rb"))

# ================= MY SCORE =================
async def myscore(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        send = q.edit_message_text
    else:
        send = update.message.reply_text

    cur.execute("""
        SELECT exam, topic, score, total, test_date
        FROM scores
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 5
    """, (update.effective_user.id,))
    rows = cur.fetchall()

    if not rows:
        await send("❌ *No test history found.*", parse_mode="Markdown", reply_markup=home_kb())
        return

    text = "📊 *My Recent Tests*\n\n"
    for r in rows:
        text += f"{r[0]} / {r[1]} → {r[2]}/{r[3]} ({r[4]})\n"

    await send(text, parse_mode="Markdown", reply_markup=home_kb())

# ================= MAIN =================
def main():
    app=ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("admin",admin))
    app.add_handler(CommandHandler("upload",upload))
    app.add_handler(CommandHandler("myscore",myscore))

    app.add_handler(MessageHandler(filters.Document.ALL,handle_excel))

    app.add_handler(CallbackQueryHandler(start_new,"^start_new$"))
    app.add_handler(CallbackQueryHandler(exam_select,"^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select,"^topic_"))
    app.add_handler(CallbackQueryHandler(answer,"^ans_"))
    app.add_handler(CallbackQueryHandler(wrong_only,"^wrong_only$"))
    app.add_handler(CallbackQueryHandler(wrong_next,"^wrong_next$"))
    app.add_handler(CallbackQueryHandler(wrong_prev,"^wrong_prev$"))
    app.add_handler(CallbackQueryHandler(review_all,"^review_all$"))
    app.add_handler(CallbackQueryHandler(myscore,"^myscore$"))
    app.add_handler(CallbackQueryHandler(leaderboard,"^leaderboard$"))
    app.add_handler(CallbackQueryHandler(pdf_result,"^pdf_result$"))
    app.add_handler(CallbackQueryHandler(admin_upload,"^admin_upload$"))
    app.add_handler(CallbackQueryHandler(admin_export,"^admin_export$"))

    print("🤖 Bot Running...")
    app.run_polling()

if __name__=="__main__":
    main()


