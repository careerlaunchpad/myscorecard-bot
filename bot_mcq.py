# =========================================================
# FINAL STABLE MCQ BOT — FULL FEATURED (PRODUCTION READY)
# =========================================================

import os, sqlite3, datetime, tempfile, unicodedata, pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from telegram.error import BadRequest

# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [1977205811]
UPI_ID = "8085692143@ybl"

# ================= DATABASE =================
conn = sqlite3.connect("mcq.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users(
 user_id INTEGER PRIMARY KEY,
 username TEXT,
 first_name TEXT,
 last_name TEXT,
 mobile TEXT,
 created_at TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS mcq(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 exam TEXT, topic TEXT, question TEXT,
 a TEXT, b TEXT, c TEXT, d TEXT,
 correct TEXT, explanation TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS scores(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER,
 exam TEXT, topic TEXT,
 score INTEGER, total INTEGER,
 test_date TEXT
)
""")
conn.commit()

# ================= HELPERS =================
def is_admin(uid): return uid in ADMIN_IDS
def safe_hindi(t): return unicodedata.normalize("NFKC", str(t)) if t else ""

def display_name(u):
    if u.username:
        return f"@{u.username}"
    name = f"{u.first_name or ''} {u.last_name or ''}".strip()
    return name if name else f"User_{u.id}"

async def safe_edit_or_send(q, text, kb=None):
    try:
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    except BadRequest:
        await q.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

# ================= UI =================
def home_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="start_new")]])

#------exam button----------
def exam_kb():
    cur.execute("SELECT DISTINCT exam FROM mcq")
    exams = [r[0] for r in cur.fetchall()]

    kb = [
        [InlineKeyboardButton("💖 Donate", callback_data="donate")],
        [InlineKeyboardButton("👤 My Profile", callback_data="profile")]
    ]

    if exams:
        for e in exams:
            kb.append([InlineKeyboardButton(e, callback_data=f"exam_{e}")])
    else:
        kb.append([InlineKeyboardButton("⚠️ No Exams Available", callback_data="noop")])

    kb.append([InlineKeyboardButton("🛠 Admin", callback_data="admin_panel")])
    return InlineKeyboardMarkup(kb)


def topic_kb(exam):
    cur.execute("SELECT DISTINCT topic FROM mcq WHERE exam=?", (exam,))
    kb = [[InlineKeyboardButton(t[0], callback_data=f"topic_{t[0]}")] for t in cur.fetchall()]
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="start_new")])
    return InlineKeyboardMarkup(kb)

# ================= START =================
async def start(update: Update, ctx):
    u = update.effective_user
    cur.execute(
        "INSERT OR IGNORE INTO users VALUES(?,?,?,?,?,?)",
        (u.id, u.username, u.first_name, u.last_name, None, datetime.date.today().isoformat())
    )
    conn.commit()
    ctx.user_data.clear()
    await update.message.reply_text("👋 *Select Exam*", parse_mode="Markdown", reply_markup=exam_kb())

async def start_new(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data.clear()
    await safe_edit_or_send(q, "👋 *Select Exam*", exam_kb())

# ================= EXAM FLOW =================
async def exam_select(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data.clear()
    ctx.user_data["exam"] = q.data.replace("exam_", "")
    await safe_edit_or_send(q, "📚 Choose Topic", topic_kb(ctx.user_data["exam"]))

async def topic_select(update, ctx):
    q = update.callback_query; await q.answer()
    exam = ctx.user_data["exam"]
    topic = q.data.replace("topic_", "")
    cur.execute("SELECT COUNT(*) FROM mcq WHERE exam=? AND topic=?", (exam, topic))
    total = cur.fetchone()[0]
    if total == 0:
        await safe_edit_or_send(q, "⚠️ No questions found", home_kb()); return
    ctx.user_data.update({
        "exam": exam, "topic": topic,
        "score": 0, "q_no": 0,
        "asked": [], "wrong": [], "attempts": []
    })
    await send_mcq(q, ctx)

# ================= MCQ =================
async def send_mcq(q, ctx):
    exam, topic = ctx.user_data["exam"], ctx.user_data["topic"]
    asked = ctx.user_data["asked"]
    if asked:
        ph = ",".join("?" * len(asked))
        cur.execute(
            f"SELECT * FROM mcq WHERE exam=? AND topic=? AND id NOT IN ({ph}) ORDER BY RANDOM() LIMIT 1",
            [exam, topic] + asked
        )
    else:
        cur.execute("SELECT * FROM mcq WHERE exam=? AND topic=? ORDER BY RANDOM() LIMIT 1", (exam, topic))
    m = cur.fetchone()
    if not m:
        await show_result(q, ctx); return
    ctx.user_data["current"] = m
    ctx.user_data["asked"].append(m[0])
    await safe_edit_or_send(
        q,
        f"❓ *Q{ctx.user_data['q_no']+1}*\n\n{m[3]}\n\n"
        f"A. {m[4]}\nB. {m[5]}\nC. {m[6]}\nD. {m[7]}",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("A", callback_data="ans_A"),
             InlineKeyboardButton("B", callback_data="ans_B")],
            [InlineKeyboardButton("C", callback_data="ans_C"),
             InlineKeyboardButton("D", callback_data="ans_D")],
            [InlineKeyboardButton("🏠 Home (Abort)", callback_data="start_new")]
        ])
    )

async def answer(update, ctx):
    q = update.callback_query; await q.answer()
    if "current" not in ctx.user_data:
        await safe_edit_or_send(q, "⚠️ Session expired", home_kb()); return
    m = ctx.user_data["current"]
    sel = q.data[-1]
    chosen = m[4 if sel=="A" else 5 if sel=="B" else 6 if sel=="C" else 7]
    correct = m[4 if m[8]=="A" else 5 if m[8]=="B" else 6 if m[8]=="C" else 7]
    ctx.user_data["attempts"].append({
        "question": m[3], "chosen": chosen,
        "correct": correct, "explanation": m[9]
    })
    if sel == m[8]: ctx.user_data["score"] += 1
    else: ctx.user_data["wrong"].append(m)
    ctx.user_data["q_no"] += 1
    ctx.user_data.pop("current", None)
    await send_mcq(q, ctx)

# ================= RESULT =================
async def show_result(q, ctx):
    exam, topic = ctx.user_data.get("exam"), ctx.user_data.get("topic")
    score, total = ctx.user_data.get("score", 0), ctx.user_data.get("q_no", 0)
    if not exam or not topic or total == 0:
        await safe_edit_or_send(q, "⚠️ Test data incomplete", home_kb()); return
    cur.execute(
        "INSERT INTO scores VALUES(NULL,?,?,?,?,?,?)",
        (q.from_user.id, exam, topic, score, total, datetime.date.today().isoformat())
    )
    conn.commit()
    ctx.user_data["last_screen"] = "result"
    await safe_edit_or_send(
        q,
        f"🎯 *Test Completed*\n\nScore: *{score}/{total}*",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("💖 Donate", callback_data="donate")],
            [InlineKeyboardButton("🔍 Review All", callback_data="review_all")],
            [InlineKeyboardButton("❌ Wrong Only", callback_data="wrong_only")],
            [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
            [InlineKeyboardButton("📄 PDF", callback_data="pdf_result")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )

# ================= REVIEW =================
async def review_all(update, ctx):
    q = update.callback_query; await q.answer()
    text = "📋 *Review*\n\n"
    for i,a in enumerate(ctx.user_data.get("attempts", []),1):
        text += f"*Q{i}.* {a['question']}\nYour: {a['chosen']}\nCorrect: {a['correct']}\n📘 {a['explanation']}\n\n"
    await safe_edit_or_send(
        q, text,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="back_result")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )

# ================= WRONG =================
async def wrong_only(update, ctx):
    q = update.callback_query; await q.answer()
    if not ctx.user_data.get("wrong"):
        await safe_edit_or_send(
            q, "🎉 No wrong questions",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="back_result")],
                [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
            ])
        ); return
    ctx.user_data["wrong_index"] = 0
    await show_wrong_question(q, ctx)

async def show_wrong_question(q, ctx):
    idx = ctx.user_data["wrong_index"]
    wrong = ctx.user_data["wrong"]
    m = wrong[idx]
    correct = m[4 if m[8]=="A" else 5 if m[8]=="B" else 6 if m[8]=="C" else 7]
    nav=[]
    if idx>0: nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="wrong_prev"))
    if idx<len(wrong)-1: nav.append(InlineKeyboardButton("➡️ Next", callback_data="wrong_next"))
    kb=[]
    if nav: kb.append(nav)
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="back_result")])
    kb.append([InlineKeyboardButton("🏠 Home", callback_data="start_new")])
    await safe_edit_or_send(
        q,
        f"❌ *Wrong {idx+1}/{len(wrong)}*\n\n{m[3]}\n\n✅ {correct}\n📘 {m[9]}",
        InlineKeyboardMarkup(kb)
    )

async def wrong_next(update, ctx):
    q=update.callback_query; await q.answer()
    ctx.user_data["wrong_index"]+=1
    await show_wrong_question(q, ctx)

async def wrong_prev(update, ctx):
    q=update.callback_query; await q.answer()
    ctx.user_data["wrong_index"]-=1
    await show_wrong_question(q, ctx)

async def back_result(update, ctx):
    q=update.callback_query; await q.answer()
    await show_result(q, ctx)

# ================= LEADERBOARD =================
async def leaderboard(update, ctx):
    q=update.callback_query; await q.answer()
    exam,topic=ctx.user_data.get("exam"),ctx.user_data.get("topic")
    if not exam or not topic:
        await safe_edit_or_send(q,"⚠️ Complete a test first",home_kb()); return
    cur.execute("""
        SELECT u.username, MAX(s.score)
        FROM scores s JOIN users u ON u.user_id=s.user_id
        WHERE s.exam=? AND s.topic=?
        GROUP BY s.user_id
        ORDER BY MAX(s.score) DESC
        LIMIT 10
    """,(exam,topic))
    rows=cur.fetchall()
    text=f"🏆 *Leaderboard — {exam}/{topic}*\n\n"
    for i,r in enumerate(rows,1):
        text+=f"{i}. *{r[0] or 'User'}* → {r[1]}\n"
    await safe_edit_or_send(q,text,home_kb())

# ================= PROFILE =================
async def profile(update, ctx):
    q=update.callback_query; await q.answer()
    u=q.from_user
    cur.execute(
        "SELECT exam,topic,score,total,test_date FROM scores WHERE user_id=? ORDER BY id DESC",
        (u.id,)
    )
    rows=cur.fetchall()
    text=f"👤 *{display_name(u)}*\n\n"
    if not rows: text+="_No tests yet_"
    for r in rows:
        text+=f"{r[0]}/{r[1]} → *{r[2]}/{r[3]}* ({r[4]})\n"
    await safe_edit_or_send(q,text,home_kb())

# ================= DONATE =================
async def donate(update, ctx):
    q=update.callback_query; await q.answer()
    await safe_edit_or_send(
        q,
        f"🙏 *Support this free bot*\n\n`{UPI_ID}`",
        InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="start_new")]])
    )

# ================= PDF =================
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4

pdfmetrics.registerFont(TTFont("Hindi","NotoSansDevanagari-Regular.ttf"))

async def pdf_result(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    if not ctx.user_data.get("attempts"):
        await safe_edit_or_send(q,"⚠️ No data",home_kb()); return
    path=f"MyScore_{q.from_user.id}.pdf"
    doc=SimpleDocTemplate(path,pagesize=A4)
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H",fontName="Hindi",fontSize=11))
    story=[Paragraph("MyScoreCard",styles["H"]),Spacer(1,10)]
    for i,a in enumerate(ctx.user_data["attempts"],1):
        story+=[
            Paragraph(f"Q{i}: {safe_hindi(a['question'])}",styles["H"]),
            Paragraph(f"Your: {safe_hindi(a['chosen'])}",styles["H"]),
            Paragraph(f"Correct: {safe_hindi(a['correct'])}",styles["H"]),
            Paragraph(f"Explanation: {safe_hindi(a['explanation'])}",styles["H"]),
            Spacer(1,8)
        ]
    doc.build(story)
    await ctx.bot.send_document(q.from_user.id,open(path,"rb"))

# ================= MAIN =================
def main():
    
    app=ApplicationBuilder().token(TOKEN).build()
    # ---- BASIC ----
    app.add_handler(CommandHandler("start", start))

# ---- TOP LEVEL BUTTONS (FIRST) ----
    #app.add_handler(CallbackQueryHandler(admin_panel, "^admin_panel$"))
    app.add_handler(CallbackQueryHandler(donate, "^donate$"))
    app.add_handler(CallbackQueryHandler(profile, "^profile$"))

# ---- NAVIGATION ----
    app.add_handler(CallbackQueryHandler(start_new, "^start_new$"))
    app.add_handler(CallbackQueryHandler(back_result, "^back_result$"))

# ---- EXAM FLOW ----
    app.add_handler(CallbackQueryHandler(exam_select, "^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select, "^topic_"))
    app.add_handler(CallbackQueryHandler(answer, "^ans_"))

# ---- RESULT FLOW ----
    app.add_handler(CallbackQueryHandler(review_all, "^review_all$"))
    app.add_handler(CallbackQueryHandler(wrong_only, "^wrong_only$"))
    app.add_handler(CallbackQueryHandler(wrong_next, "^wrong_next$"))
    app.add_handler(CallbackQueryHandler(wrong_prev, "^wrong_prev$"))
    app.add_handler(CallbackQueryHandler(leaderboard, "^leaderboard$"))
    app.add_handler(CallbackQueryHandler(pdf_result, "^pdf_result$"))

    """
    app=ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CallbackQueryHandler(start_new,"^start_new$"))
    app.add_handler(CallbackQueryHandler(exam_select,"^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select,"^topic_"))
    app.add_handler(CallbackQueryHandler(answer,"^ans_"))
    app.add_handler(CallbackQueryHandler(review_all,"^review_all$"))
    app.add_handler(CallbackQueryHandler(wrong_only,"^wrong_only$"))
    app.add_handler(CallbackQueryHandler(wrong_next,"^wrong_next$"))
    app.add_handler(CallbackQueryHandler(wrong_prev,"^wrong_prev$"))
    app.add_handler(CallbackQueryHandler(back_result,"^back_result$"))
    app.add_handler(CallbackQueryHandler(leaderboard,"^leaderboard$"))
    app.add_handler(CallbackQueryHandler(pdf_result,"^pdf_result$"))
    app.add_handler(CallbackQueryHandler(profile,"^profile$"))
    app.add_handler(CallbackQueryHandler(donate,"^donate$"))"""
    
    print("🤖 Bot Running...")
    app.run_polling()

if __name__=="__main__":
    main()



