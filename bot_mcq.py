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
TOKEN = os.getenv("BOT_TOKEN") or "PASTE_YOUR_TOKEN_HERE"
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
 correct TEXT, explanation TEXT,
 is_active INTEGER DEFAULT 1
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

def home_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="start_new")]])

# ================= USER FLOW =================
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

def exam_kb():
    cur.execute("""
        SELECT DISTINCT exam
        FROM mcq
        WHERE is_active=1
    """)
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
    cur.execute("""
        SELECT DISTINCT topic
        FROM mcq
        WHERE exam=? AND is_active=1
    """, (exam,))
    kb = [[InlineKeyboardButton(t[0], callback_data=f"topic_{t[0]}")] for t in cur.fetchall()]
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="start_new")])
    return InlineKeyboardMarkup(kb)

async def exam_select(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data.clear()
    ctx.user_data["exam"] = q.data.replace("exam_", "")
    await safe_edit_or_send(q, "📚 Choose Topic", topic_kb(ctx.user_data["exam"]))

# ================= TEST START =================
async def topic_select(update, ctx):
    q = update.callback_query; await q.answer()
    exam = ctx.user_data.get("exam")
    topic = q.data.replace("topic_", "")

    if not exam:
        await safe_edit_or_send(q, "⚠️ Session expired", home_kb())
        return

    cur.execute("""
        SELECT * FROM mcq
        WHERE exam=? AND topic=? AND is_active=1
        ORDER BY RANDOM()
    """, (exam, topic))

    questions = cur.fetchall()
    if not questions:
        await safe_edit_or_send(
            q,
            "⛔ *This test is currently disabled or empty*",
            home_kb()
        )
        return

    ctx.user_data.clear()
    ctx.user_data.update({
        "exam": exam,
        "topic": topic,
        "questions": questions,
        "q_index": 0,
        "answers": {}
    })

    await show_question(q, ctx)

# ================= MCQ ENGINE =================
async def show_question(q, ctx):
    qs = ctx.user_data.get("questions")
    if not qs:
        await safe_edit_or_send(q, "⚠️ Test expired", home_kb())
        return

    idx = ctx.user_data["q_index"]
    idx = max(0, min(idx, len(qs) - 1))
    ctx.user_data["q_index"] = idx

    m = qs[idx]

    text = (
        f"❓ *Question {idx+1} / {len(qs)}*\n\n"
        f"{m[3]}\n\n"
        f"A. {m[4]}\n"
        f"B. {m[5]}\n"
        f"C. {m[6]}\n"
        f"D. {m[7]}"
    )

    kb = [
        [InlineKeyboardButton("A", callback_data="ans_A"),
         InlineKeyboardButton("B", callback_data="ans_B")],
        [InlineKeyboardButton("C", callback_data="ans_C"),
         InlineKeyboardButton("D", callback_data="ans_D")]
    ]

    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="prev_q"))
    if idx < len(qs) - 1:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="next_q"))

    if nav:
        kb.append(nav)

    kb.append([
        InlineKeyboardButton("✅ Submit Test", callback_data="finish_test"),
        InlineKeyboardButton("🏠 Home", callback_data="start_new")
    ])

    await safe_edit_or_send(q, text, InlineKeyboardMarkup(kb))

async def answer(update, ctx):
    q = update.callback_query; await q.answer()
    idx = ctx.user_data["q_index"]
    m = ctx.user_data["questions"][idx]
    ctx.user_data["answers"][m[0]] = q.data[-1]
    await show_question(q, ctx)

async def next_q(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data["q_index"] += 1
    await show_question(q, ctx)

async def prev_q(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data["q_index"] -= 1
    await show_question(q, ctx)

# ================= RESULT =================
async def finish_test(update, ctx):
    q = update.callback_query; await q.answer()

    qs = ctx.user_data["questions"]
    ans = ctx.user_data["answers"]

    score = 0
    attempts = []

    for m in qs:
        chosen = ans.get(m[0])
        if chosen == m[8]:
            score += 1

        attempts.append({
            "question": m[3],
            "chosen": chosen or "—",
            "correct": m[8],
            "explanation": m[9]
        })

    cur.execute(
        "INSERT INTO scores VALUES(NULL,?,?,?,?,?,?)",
        (
            q.from_user.id,
            ctx.user_data["exam"],
            ctx.user_data["topic"],
            score,
            len(qs),
            datetime.date.today().isoformat()
        )
    )
    conn.commit()

    ctx.user_data["attempts"] = attempts

    await safe_edit_or_send(
        q,
        f"🎯 *Test Completed*\n\nScore: *{score}/{len(qs)}*",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Review All", callback_data="review_all")],
            [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )

# ================= REVIEW (PAGINATED) =================
REVIEW_PAGE_SIZE = 5

async def review_all(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data["review_index"] = 0
    await show_review_page(q, ctx)

async def show_review_page(q, ctx):
    attempts = ctx.user_data["attempts"]
    idx = ctx.user_data["review_index"]

    start = idx * REVIEW_PAGE_SIZE
    end = start + REVIEW_PAGE_SIZE
    page = attempts[start:end]
    total_pages = (len(attempts) - 1) // REVIEW_PAGE_SIZE + 1

    text = f"📋 *Review All* (Page {idx+1}/{total_pages})\n\n"
    for i, a in enumerate(page, start + 1):
        text += (
            f"*Q{i}.* {a['question']}\n"
            f"Your: {a['chosen']}\n"
            f"Correct: {a['correct']}\n"
            f"📘 {a['explanation']}\n\n"
        )

    kb = []
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="review_prev"))
    if end < len(attempts):
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="review_next"))
    if nav:
        kb.append(nav)

    kb.append([InlineKeyboardButton("🏠 Home", callback_data="start_new")])
    await safe_edit_or_send(q, text, InlineKeyboardMarkup(kb))

async def review_next(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data["review_index"] += 1
    await show_review_page(q, ctx)

async def review_prev(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data["review_index"] -= 1
    await show_review_page(q, ctx)

# ================= OTHER =================
async def donate(update, ctx):
    q = update.callback_query; await q.answer()
    await safe_edit_or_send(
        q,
        f"❤️ *Support This Bot*\n\nUPI: `{UPI_ID}`",
        InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="start_new")]])
    )

async def profile(update, ctx):
    q = update.callback_query; await q.answer()
    cur.execute("SELECT COUNT(*) FROM scores WHERE user_id=?", (q.from_user.id,))
    c = cur.fetchone()[0]
    await safe_edit_or_send(q, f"👤 *Profile*\n\nTests Given: {c}", home_kb())

async def leaderboard(update, ctx):
    q = update.callback_query; await q.answer()
    exam = ctx.user_data["exam"]
    topic = ctx.user_data["topic"]

    cur.execute("""
        SELECT u.username, MAX(s.score)
        FROM scores s
        JOIN users u ON u.user_id=s.user_id
        WHERE exam=? AND topic=?
        GROUP BY s.user_id
        ORDER BY MAX(s.score) DESC
        LIMIT 10
    """, (exam, topic))

    text = "🏆 *Leaderboard*\n\n"
    for i, r in enumerate(cur.fetchall(), 1):
        text += f"{i}. {r[0] or 'User'} → {r[1]}\n"

    await safe_edit_or_send(q, text, home_kb())

async def noop(update, ctx):
    await update.callback_query.answer("No exams available")

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(start_new, "^start_new$"))
    app.add_handler(CallbackQueryHandler(exam_select, "^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select, "^topic_"))

    app.add_handler(CallbackQueryHandler(answer, "^ans_"))
    app.add_handler(CallbackQueryHandler(next_q, "^next_q$"))
    app.add_handler(CallbackQueryHandler(prev_q, "^prev_q$"))
    app.add_handler(CallbackQueryHandler(finish_test, "^finish_test$"))

    app.add_handler(CallbackQueryHandler(review_all, "^review_all$"))
    app.add_handler(CallbackQueryHandler(review_next, "^review_next$"))
    app.add_handler(CallbackQueryHandler(review_prev, "^review_prev$"))

    app.add_handler(CallbackQueryHandler(profile, "^profile$"))
    app.add_handler(CallbackQueryHandler(leaderboard, "^leaderboard$"))
    app.add_handler(CallbackQueryHandler(donate, "^donate$"))
    app.add_handler(CallbackQueryHandler(noop, "^noop$"))

    print("🤖 Bot Running (PRODUCTION READY)")
    app.run_polling()

if __name__ == "__main__":
    main()
