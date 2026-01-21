# =========================================================
# FINAL STABLE MCQ BOT — STEP 5 COMPLETE
# User Profile + History + Review + Wrong Nav + Admin
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

async def safe_edit_or_send(q, text, kb=None):
    try:
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    except BadRequest:
        await q.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

def display_name(user):
    if user.username:
        return f"@{user.username}"
    name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return name if name else f"User_{user.id}"

# ================= UI =================
def home_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
    ])

def exam_kb():
    cur.execute("SELECT DISTINCT exam FROM mcq")
    exams = [r[0] for r in cur.fetchall()]

    kb = [
        [InlineKeyboardButton("💖 Donate", callback_data="donate")],
        [InlineKeyboardButton("👤 My Profile", callback_data="profile")]
    ]

    for e in exams:
        kb.append([InlineKeyboardButton(e, callback_data=f"exam_{e}")])

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
    await update.message.reply_text(
        "👋 *Select Exam*",
        parse_mode="Markdown",
        reply_markup=exam_kb()
    )

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
        await safe_edit_or_send(q, "⚠️ No questions found", home_kb())
        return

    ctx.user_data.update({
        "exam": exam,
        "topic": topic,
        "score": 0,
        "q_no": 0,
        "asked": [],
        "wrong": [],
        "attempts": []
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
        cur.execute(
            "SELECT * FROM mcq WHERE exam=? AND topic=? ORDER BY RANDOM() LIMIT 1",
            (exam, topic)
        )

    m = cur.fetchone()
    if not m:
        await show_result(q, ctx)
        return

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
        await safe_edit_or_send(q, "⚠️ Session expired", home_kb())
        return

    m = ctx.user_data["current"]
    sel = q.data[-1]

    chosen = m[4 if sel=="A" else 5 if sel=="B" else 6 if sel=="C" else 7]
    correct = m[4 if m[8]=="A" else 5 if m[8]=="B" else 6 if m[8]=="C" else 7]

    ctx.user_data["attempts"].append({
        "question": m[3],
        "chosen": chosen,
        "correct": correct,
        "explanation": m[9]
    })

    if sel == m[8]:
        ctx.user_data["score"] += 1
    else:
        ctx.user_data["wrong"].append(m)

    ctx.user_data["q_no"] += 1
    ctx.user_data.pop("current", None)
    await send_mcq(q, ctx)

# ================= RESULT =================
"""async def show_result(q, ctx):
    u = q.from_user
    cur.execute(
        "INSERT INTO scores VALUES(NULL,?,?,?,?,?)",
        (u.id, ctx.user_data["exam"], ctx.user_data["topic"],
         ctx.user_data["score"], ctx.user_data["q_no"],
         datetime.date.today().isoformat())
    )
    conn.commit()

    ctx.user_data["result_ctx"] = True

    await safe_edit_or_send(
        q,
        f"🎯 *Result*\n\nScore: *{ctx.user_data['score']}/{ctx.user_data['q_no']}*",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("💖 Donate", callback_data="donate")],
            [InlineKeyboardButton("🔍 Review All", callback_data="review_all")],
            [InlineKeyboardButton("❌ Wrong Only", callback_data="wrong_only")],
            [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
            [InlineKeyboardButton("📄 PDF", callback_data="pdf_result")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )
    """
async def show_result(q, ctx):
    # 🔐 SAFETY
    exam = ctx.user_data.get("exam")
    topic = ctx.user_data.get("topic")
    score = ctx.user_data.get("score", 0)
    total = ctx.user_data.get("q_no", 0)

    if not exam or not topic or total == 0:
        await safe_edit_or_send(
            q,
            "⚠️ Test data incomplete. Please start again.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
            ])
        )
        return

    # ⭐ SAVE LAST SCREEN
    ctx.user_data["last_screen"] = "result"

    cur.execute(
        "INSERT INTO scores VALUES(NULL,?,?,?,?,?,?)",
        (
            q.from_user.id,
            exam,
            topic,
            score,
            total,
            datetime.date.today().isoformat()
        )
    )
    conn.commit()

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
#------back to result--------------------
async def back_to_result(update, ctx):
    q = update.callback_query
    await q.answer()

    if ctx.user_data.get("last_screen") == "result":
        await show_result(q, ctx)
    else:
        await safe_edit_or_send(
            q,
            "⚠️ Session expired.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
            ])
        )


# ================= REVIEW =================
async def review_all(update, ctx):
    q = update.callback_query
    await q.answer()

    ctx.user_data["last_screen"] = "result"

    text = "📋 *Review All Questions*\n\n"
    for i, a in enumerate(ctx.user_data.get("attempts", []), 1):
        text += (
            f"*Q{i}.* {a['question']}\n"
            f"Your: {a['chosen']}\n"
            f"Correct: {a['correct']}\n"
            f"📘 {a['explanation']}\n\n"
        )

    await safe_edit_or_send(
        q,
        text,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="back_result")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )

# ================= WRONG =================
async def wrong_only(update, ctx):
    q = update.callback_query
    await q.answer()

    if not ctx.user_data.get("wrong"):
        await safe_edit_or_send(
            q,
            "🎉 No wrong questions",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="back_result")],
                [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
            ])
        )
        return

    ctx.user_data["wrong_index"] = 0
    ctx.user_data["last_screen"] = "result"
    await show_wrong_question(q, ctx)

#--------- show wrong------------------
async def show_wrong(q, ctx):
    i = ctx.user_data["wrong_i"]
    m = ctx.user_data["wrong"][i]
    correct = m[4 if m[8]=="A" else 5 if m[8]=="B" else 6 if m[8]=="C" else 7]

    kb = []
    nav = []
    if i > 0: nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="wrong_prev"))
    if i < len(ctx.user_data["wrong"])-1:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="wrong_next"))
    if nav: kb.append(nav)
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="back_result")])
    kb.append([InlineKeyboardButton("🏠 Home", callback_data="start_new")])

    await safe_edit_or_send(
        q,
        f"❌ *Wrong {i+1}*\n\n{m[3]}\n\n✅ {correct}\n📘 {m[9]}",
        InlineKeyboardMarkup(kb)
    )
#---- show wrong question------------
async def show_wrong_question(q, ctx):
    idx = ctx.user_data["wrong_index"]
    wrong_list = ctx.user_data["wrong"]

    m = wrong_list[idx]
    correct = m[4 if m[8]=="A" else 5 if m[8]=="B" else 6 if m[8]=="C" else 7]

    text = (
        f"❌ *Wrong Question {idx+1}/{len(wrong_list)}*\n\n"
        f"{m[3]}\n\n"
        f"✅ *Correct:* {correct}\n"
        f"📘 {m[9]}"
    )

    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="wrong_prev"))
    if idx < len(wrong_list) - 1:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="wrong_next"))

    kb = []
    if nav:
        kb.append(nav)

    kb.append([
        InlineKeyboardButton("⬅️ Back", callback_data="back_result")
    ])
    kb.append([
        InlineKeyboardButton("🏠 Home", callback_data="start_new")
    ])

    await safe_edit_or_send(q, text, InlineKeyboardMarkup(kb))

#-------wrong next-------------
async def wrong_next(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data["wrong_i"] += 1
    await show_wrong(q, ctx)

#------wrong previous---------------
async def wrong_prev(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data["wrong_i"] -= 1
    await show_wrong(q, ctx)

# ================= BACK =================
async def back_result(update, ctx):
    q = update.callback_query; await q.answer()
    await show_result(q, ctx)

# ================= LEADERBOARD =================
async def leaderboard(update, ctx):
    q = update.callback_query
    await q.answer()

    exam = ctx.user_data.get("exam")
    topic = ctx.user_data.get("topic")

    if not exam or not topic:
        await safe_edit_or_send(
            q,
            "⚠️ Leaderboard देखने के लिए पहले कोई test complete करें",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="start_new")],
                [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
            ])
        )
        return

    cur.execute("""
        SELECT username, MAX(score)
        FROM scores
        WHERE exam=? AND topic=?
        GROUP BY user_id
        ORDER BY MAX(score) DESC
        LIMIT 10
    """, (exam, topic))

    rows = cur.fetchall()

    if not rows:
        text = "📊 अभी तक कोई result नहीं मिला"
    else:
        text = f"🏆 *Leaderboard — {exam} / {topic}*\n\n"
        for i, r in enumerate(rows, 1):
            name = r[0] if r[0] else "Unknown User"
            text += f"{i}. *{name}* → {r[1]}\n"

    await safe_edit_or_send(
        q,
        text,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="review_all")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )


# ================= PROFILE =================
async def profile(update, ctx):
    q = update.callback_query; await q.answer()
    u = q.from_user

    cur.execute(
        "SELECT exam, topic, score, total, test_date FROM scores WHERE user_id=? ORDER BY id DESC",
        (u.id,)
    )
    rows = cur.fetchall()

    name = display_name(u)
    txt = f"👤 *{name}*\n\n📚 *Your Tests*\n\n"

    if not rows:
        txt += "_No tests yet_"

    for r in rows:
        txt += f"{r[0]} / {r[1]} → *{r[2]}/{r[3]}* ({r[4]})\n"

    await safe_edit_or_send(q, txt, home_kb())

# ================= DONATE =================
async def donate(update, ctx):
    q = update.callback_query; await q.answer()
    await safe_edit_or_send(
        q,
        f"🙏 *Support This Free Bot*\n\n`{UPI_ID}`",
        InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="start_new")]])
    )
# ================= PDF RESULT =================
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4

pdfmetrics.registerFont(TTFont("Hindi", "NotoSansDevanagari-Regular.ttf"))

async def pdf_result(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if "attempts" not in ctx.user_data or not ctx.user_data["attempts"]:
        await safe_edit_or_send(
            q,
            "⚠️ PDF बनाने के लिए कोई test data नहीं है",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="review_all")],
                [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
            ])
        )
        return

    file_path = f"MyScore_{q.from_user.id}.pdf"
    doc = SimpleDocTemplate(file_path, pagesize=A4)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H", fontName="Hindi", fontSize=11))

    story = [
        Paragraph("MyScoreCard – Test Result", styles["H"]),
        Spacer(1, 12)
    ]

    for i, a in enumerate(ctx.user_data["attempts"], 1):
        story.extend([
            Paragraph(f"Q{i}: {safe_hindi(a['question'])}", styles["H"]),
            Paragraph(f"Your Answer: {safe_hindi(a['chosen'])}", styles["H"]),
            Paragraph(f"Correct Answer: {safe_hindi(a['correct'])}", styles["H"]),
            Paragraph(f"Explanation: {safe_hindi(a['explanation'])}", styles["H"]),
            Spacer(1, 10)
        ])

    doc.build(story)

    await ctx.bot.send_document(
        chat_id=q.from_user.id,
        document=open(file_path, "rb")
    )

    await ctx.bot.send_message(
        chat_id=q.from_user.id,
        text="📄 PDF Generated Successfully",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="review_all")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(CallbackQueryHandler(donate, "^donate$"))
    app.add_handler(CallbackQueryHandler(profile, "^profile$"))
    app.add_handler(CallbackQueryHandler(start_new, "^start_new$"))
    app.add_handler(CallbackQueryHandler(back_result, "^back_result$"))
    app.add_handler(CallbackQueryHandler(back_to_result, "^back_result$"))


    app.add_handler(CallbackQueryHandler(exam_select, "^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select, "^topic_"))
    app.add_handler(CallbackQueryHandler(answer, "^ans_"))

    app.add_handler(CallbackQueryHandler(review_all, "^review_all$"))
    app.add_handler(CallbackQueryHandler(wrong_only, "^wrong_only$"))
    app.add_handler(CallbackQueryHandler(wrong_next, "^wrong_next$"))
    app.add_handler(CallbackQueryHandler(wrong_prev, "^wrong_prev$"))

    app.add_handler(CallbackQueryHandler(leaderboard, "^leaderboard$"))
    app.add_handler(CallbackQueryHandler(pdf_result, "^pdf_result$"))

    print("🤖 Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()





