# =====================================================
# PART-1 : CONFIG + DATABASE + CORE HELPERS
# =====================================================

import os
import sqlite3
import datetime
import unicodedata
import tempfile

import pandas as pd

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)
from telegram.error import BadRequest

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

# ================= CONFIG =================
#TOKEN = os.getenv("BOT_TOKEN") or "PUT_YOUR_BOT_TOKEN_HERE"

UPI_ID = "8085692143@ybl"

# 🔐 ADMIN IDS
ADMIN_IDS = [1977205811]

# ================= DATABASE =================
conn = sqlite3.connect("mcq.db", check_same_thread=False)
cur = conn.cursor()

# ---- USERS TABLE ----
cur.execute("""
CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    created_at TEXT
)
""")

# ---- MCQ TABLE ----
cur.execute("""
CREATE TABLE IF NOT EXISTS mcq(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam TEXT,
    topic TEXT,
    question TEXT,
    a TEXT,
    b TEXT,
    c TEXT,
    d TEXT,
    correct TEXT,
    explanation TEXT,
    is_active INTEGER DEFAULT 1
)
""")

# ---- SCORES TABLE ----
cur.execute("""
CREATE TABLE IF NOT EXISTS scores(
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

# ================= PDF FONT (UNICODE SAFE) =================
pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))

# ================= CORE HELPERS =================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def safe_text(text):
    """Unicode safe text for PDF & Telegram"""
    return unicodedata.normalize("NFKC", str(text)) if text else ""


def display_name(user):
    """Username priority fallback chain"""
    if user.username:
        return f"@{user.username}"
    name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return name if name else f"User_{user.id}"


async def safe_edit_or_send(query, text, keyboard=None):
    """
    Telegram safe edit:
    - edit if possible
    - else send new message
    """
    try:
        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except BadRequest:
        await query.message.reply_text(
            text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )


def is_duplicate_mcq(exam, topic, question):
    """
    DB-level duplicate MCQ detection
    """
    cur.execute("""
        SELECT 1 FROM mcq
        WHERE exam=? AND topic=? AND question=?
        LIMIT 1
    """, (exam, topic, question))
    return cur.fetchone() is not None


# ================= COMMON KEYBOARDS =================

def home_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="home")]
    ])
# =====================================================
# PART-2 : USER EXAM FLOW + SESSION SAFETY
# =====================================================

# ================= EXAM / TOPIC KEYBOARDS =================

def exam_kb():
    """
    Show only exams having at least one ACTIVE MCQ
    """
    cur.execute("""
        SELECT DISTINCT exam
        FROM mcq
        WHERE is_active=1
        ORDER BY exam
    """)
    rows = cur.fetchall()

    kb = []

    if rows:
        for (exam,) in rows:
            kb.append([InlineKeyboardButton(exam, callback_data=f"exam::{exam}")])
    else:
        kb.append([InlineKeyboardButton("⚠️ No Active Exams", callback_data="noop")])

    kb.append([InlineKeyboardButton("👤 My Profile", callback_data="profile")])
    kb.append([InlineKeyboardButton("💖 Donate", callback_data="donate")])

    if ADMIN_IDS:
        kb.append([InlineKeyboardButton("🛠 Admin", callback_data="admin_panel")])

    return InlineKeyboardMarkup(kb)


def topic_kb(exam):
    """
    Topics shown only if ACTIVE
    """
    cur.execute("""
        SELECT DISTINCT topic
        FROM mcq
        WHERE exam=? AND is_active=1
        ORDER BY topic
    """, (exam,))

    rows = cur.fetchall()

    kb = [[InlineKeyboardButton(t[0], callback_data=f"topic::{t[0]}")]
          for t in rows]

    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="home")])
    return InlineKeyboardMarkup(kb)


# ================= START / HOME =================

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # Insert user if not exists
    cur.execute("""
        INSERT OR IGNORE INTO users
        (user_id, username, first_name, last_name, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        user.id,
        user.username,
        user.first_name,
        user.last_name,
        datetime.date.today().isoformat()
    ))
    conn.commit()

    ctx.user_data.clear()

    await update.message.reply_text(
        "👋 *Select Exam*",
        parse_mode="Markdown",
        reply_markup=exam_kb()
    )


async def home(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data.clear()

    await safe_edit_or_send(
        q,
        "👋 *Select Exam*",
        exam_kb()
    )


# ================= EXAM SELECTION =================

async def exam_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    exam = q.data.split("::", 1)[1]

    ctx.user_data.clear()
    ctx.user_data["exam"] = exam

    await safe_edit_or_send(
        q,
        "📚 *Choose Topic*",
        topic_kb(exam)
    )


# ================= TOPIC SELECTION =================

async def topic_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    exam = ctx.user_data.get("exam")
    topic = q.data.split("::", 1)[1]

    # Load active MCQs randomly
    cur.execute("""
        SELECT *
        FROM mcq
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

    # SESSION STATE
    ctx.user_data.update({
        "exam": exam,
        "topic": topic,
        "questions": questions,
        "total": len(questions),
        "q_index": 0,
        "answers": {},          # mcq_id -> A/B/C/D
        "started_at": datetime.datetime.utcnow().isoformat()
    })

    await show_question(q, ctx)


# ================= QUESTION ENGINE =================

async def show_question(q, ctx):
    """
    Core MCQ renderer
    - highlights selected answer
    - supports skip
    """
    qs = ctx.user_data.get("questions")
    idx = ctx.user_data.get("q_index", 0)
    total = ctx.user_data.get("total", 0)

    if not qs or idx < 0 or idx >= total:
        await safe_edit_or_send(
            q,
            "⚠️ *Session expired or invalid.*\n\nPlease start again.",
            home_kb()
        )
        ctx.user_data.clear()
        return

    m = qs[idx]
    mcq_id = m[0]
    selected = ctx.user_data["answers"].get(mcq_id)

    def opt(label, value):
        return f"✅ {value}" if selected == label else value

    text = (
        f"❓ *Q {idx+1} / {total}*\n\n"
        f"{m[3]}\n\n"
        f"A. {opt('A', m[4])}\n"
        f"B. {opt('B', m[5])}\n"
        f"C. {opt('C', m[6])}\n"
        f"D. {opt('D', m[7])}"
    )

    kb = [
        [
            InlineKeyboardButton("A", callback_data="ans::A"),
            InlineKeyboardButton("B", callback_data="ans::B")
        ],
        [
            InlineKeyboardButton("C", callback_data="ans::C"),
            InlineKeyboardButton("D", callback_data="ans::D")
        ]
    ]

    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="prev"))
    if idx < total - 1:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="next"))
    if nav:
        kb.append(nav)

    kb.append([
        InlineKeyboardButton("✅ Finish Test", callback_data="finish"),
        InlineKeyboardButton("🏠 Home", callback_data="home")
    ])

    await safe_edit_or_send(
        q,
        text,
        InlineKeyboardMarkup(kb)
    )


# ================= ANSWER SELECT =================

async def answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    sel = q.data.split("::", 1)[1]

    qs = ctx.user_data.get("questions")
    idx = ctx.user_data.get("q_index", 0)

    if not qs:
        return

    mcq_id = qs[idx][0]
    ctx.user_data["answers"][mcq_id] = sel

    await show_question(q, ctx)


# ================= NAVIGATION =================

async def next_q(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if "q_index" in ctx.user_data:
        ctx.user_data["q_index"] += 1

    await show_question(q, ctx)


async def prev_q(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if "q_index" in ctx.user_data:
        ctx.user_data["q_index"] -= 1

    await show_question(q, ctx)
# =====================================================
# PART-3 : RESULT + REVIEW SYSTEM
# =====================================================

REVIEW_PAGE_SIZE = 5   # Telegram safe pagination


# ================= FINISH TEST =================

async def finish_test(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    qs = ctx.user_data.get("questions")
    answers = ctx.user_data.get("answers", {})

    if not qs:
        await safe_edit_or_send(
            q,
            "⚠️ *Session expired.*\nPlease start again.",
            home_kb()
        )
        ctx.user_data.clear()
        return

    score = 0
    attempts = []
    wrong_only = []

    for m in qs:
        mcq_id = m[0]
        chosen = answers.get(mcq_id)
        correct = m[8]

        if chosen == correct:
            score += 1
        else:
            wrong_only.append(m)

        attempts.append({
            "question": m[3],
            "chosen": m[4 + "ABCD".index(chosen)] if chosen else "Not Attempted",
            "correct": m[4 + "ABCD".index(correct)],
            "explanation": m[9]
        })

    total = len(qs)

    # 🔐 DUPLICATE SCORE PREVENTION
    cur.execute("""
        DELETE FROM scores
        WHERE user_id=? AND exam=? AND topic=?
    """, (
        q.from_user.id,
        ctx.user_data["exam"],
        ctx.user_data["topic"]
    ))

    cur.execute("""
        INSERT INTO scores
        VALUES (NULL, ?, ?, ?, ?, ?, ?)
    """, (
        q.from_user.id,
        ctx.user_data["exam"],
        ctx.user_data["topic"],
        score,
        total,
        datetime.date.today().isoformat()
    ))
    conn.commit()

    # STORE REVIEW DATA
    ctx.user_data.update({
        "score": score,
        "total": total,
        "attempts": attempts,
        "wrong_only": wrong_only,
        "review_index": 0
    })

    await safe_edit_or_send(
        q,
        f"🎯 *Test Completed*\n\n"
        f"Score: *{score} / {total}*",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Review All", callback_data="review_all")],
            [InlineKeyboardButton("❌ Wrong Only", callback_data="review_wrong")],
            [InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result")],
            [InlineKeyboardButton("🏠 Home", callback_data="home")]
        ])
    )


# ================= REVIEW ENTRY =================

async def review_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    ctx.user_data["review_mode"] = "all"
    ctx.user_data["review_index"] = 0

    await show_review(q, ctx)


async def review_wrong(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    ctx.user_data["review_mode"] = "wrong"
    ctx.user_data["review_index"] = 0

    await show_review(q, ctx)


# ================= REVIEW RENDER =================

async def show_review(q, ctx):
    mode = ctx.user_data.get("review_mode")
    index = ctx.user_data.get("review_index", 0)

    if mode == "wrong":
        data = [
            a for a in ctx.user_data["attempts"]
            if a["chosen"] != a["correct"]
        ]
        title = "❌ *Wrong Questions*"
    else:
        data = ctx.user_data.get("attempts", [])
        title = "📋 *Review All*"

    if not data:
        await safe_edit_or_send(
            q,
            "🎉 *No questions to review!*",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Result", callback_data="back_result")],
                [InlineKeyboardButton("🏠 Home", callback_data="home")]
            ])
        )
        return

    total_pages = (len(data) - 1) // REVIEW_PAGE_SIZE + 1
    start = index * REVIEW_PAGE_SIZE
    end = start + REVIEW_PAGE_SIZE
    page = data[start:end]

    text = f"{title}\n\nPage *{index+1} / {total_pages}*\n\n"

    for i, a in enumerate(page, start + 1):
        text += (
            f"*Q{i}.* {a['question']}\n"
            f"Your Answer: {a['chosen']}\n"
            f"Correct Answer: *{a['correct']}*\n"
            f"📘 {a['explanation']}\n\n"
        )

    kb = []
    nav = []

    if index > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="review_prev"))
    if end < len(data):
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="review_next"))

    if nav:
        kb.append(nav)

    kb.append([
        InlineKeyboardButton("⬅️ Back to Result", callback_data="back_result"),
        InlineKeyboardButton("🏠 Home", callback_data="home")
    ])

    await safe_edit_or_send(q, text, InlineKeyboardMarkup(kb))


# ================= REVIEW NAVIGATION =================

async def review_next(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    ctx.user_data["review_index"] += 1
    await show_review(q, ctx)


async def review_prev(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    ctx.user_data["review_index"] -= 1
    await show_review(q, ctx)


# ================= BACK TO RESULT =================

async def back_result(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    await safe_edit_or_send(
        q,
        f"🎯 *Test Completed*\n\n"
        f"Score: *{ctx.user_data.get('score')} / {ctx.user_data.get('total')}*",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Review All", callback_data="review_all")],
            [InlineKeyboardButton("❌ Wrong Only", callback_data="review_wrong")],
            [InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result")],
            [InlineKeyboardButton("🏠 Home", callback_data="home")]
        ])
    )
# =====================================================
# PART-4 : PDF RESULT GENERATION (UNICODE SAFE)
# =====================================================

# NOTE:
# - Uses reportlab + Unicode CID font (already registered in PART-1)
# - Generates per-user, per-test temporary PDF
# - Safe for Hindi + English text


def generate_result_pdf(user, exam, topic, score, total, attempts):
    """
    Create a Unicode-safe PDF result file and return file path
    """
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf_path = tmp.name
    tmp.close()

    doc = SimpleDocTemplate(pdf_path, pagesize=A4)
    styles = getSampleStyleSheet()
    styles["Normal"].fontName = "HeiseiMin-W3"

    story = []

    # ---------- HEADER ----------
    story.append(Paragraph(f"<b>Exam:</b> {safe_text(exam)}", styles["Normal"]))
    story.append(Paragraph(f"<b>Topic:</b> {safe_text(topic)}", styles["Normal"]))
    story.append(Paragraph(
        f"<b>User:</b> {safe_text(display_name(user))}",
        styles["Normal"]
    ))
    story.append(Paragraph(
        f"<b>Score:</b> {score} / {total}",
        styles["Normal"]
    ))
    story.append(Spacer(1, 12))

    # ---------- QUESTIONS ----------
    for i, a in enumerate(attempts, 1):
        story.append(Paragraph(
            f"<b>Q{i}.</b> {safe_text(a['question'])}",
            styles["Normal"]
        ))
        story.append(Paragraph(
            f"<b>Your Answer:</b> {safe_text(a['chosen'])}",
            styles["Normal"]
        ))
        story.append(Paragraph(
            f"<b>Correct Answer:</b> {safe_text(a['correct'])}",
            styles["Normal"]
        ))
        story.append(Paragraph(
            f"<b>Explanation:</b> {safe_text(a['explanation'])}",
            styles["Normal"]
        ))
        story.append(Spacer(1, 12))

    # ---------- BUILD ----------
    doc.build(story)
    return pdf_path


# ================= PDF CALLBACK =================

async def pdf_result(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    # Session safety
    if "attempts" not in ctx.user_data:
        await safe_edit_or_send(
            q,
            "⚠️ *Session expired.* Please take the test again.",
            home_kb()
        )
        return

    path = generate_result_pdf(
        user=q.from_user,
        exam=ctx.user_data.get("exam"),
        topic=ctx.user_data.get("topic"),
        score=ctx.user_data.get("score"),
        total=ctx.user_data.get("total"),
        attempts=ctx.user_data.get("attempts")
    )

    # Send PDF to user
    await ctx.bot.send_document(
        chat_id=q.from_user.id,
        document=open(path, "rb"),
        filename="MCQ_Result.pdf"
    )

    # Cleanup
    try:
        os.remove(path)
    except Exception:
        pass
# =====================================================
# PART-5 : USER PROFILE + LEADERBOARD + DONATE
# =====================================================

# ================= USER PROFILE =================

async def profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user = q.from_user

    cur.execute("""
        SELECT exam, topic, MAX(score) AS best_score, total, MAX(test_date) AS last_date
        FROM scores
        WHERE user_id=?
        GROUP BY exam, topic
        ORDER BY last_date DESC
    """, (user.id,))

    rows = cur.fetchall()

    text = f"👤 *{display_name(user)}*\n\n"

    if not rows:
        text += "_No tests attempted yet._"
    else:
        for exam, topic, best, total, date in rows:
            text += (
                f"• *{exam} / {topic}*\n"
                f"  Score: *{best}/{total}*\n"
                f"  Date: `{date}`\n\n"
            )

    await safe_edit_or_send(
        q,
        text,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Home", callback_data="home")]
        ])
    )


# ================= LEADERBOARD =================

async def leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    exam = ctx.user_data.get("exam")
    topic = ctx.user_data.get("topic")

    if not exam or not topic:
        await safe_edit_or_send(
            q,
            "⚠️ *No exam context found.*",
            home_kb()
        )
        return

    cur.execute("""
        SELECT u.username, u.first_name, u.last_name, MAX(s.score) AS best_score
        FROM scores s
        JOIN users u ON u.user_id = s.user_id
        WHERE s.exam=? AND s.topic=?
        GROUP BY s.user_id
        ORDER BY best_score DESC
        LIMIT 10
    """, (exam, topic))

    rows = cur.fetchall()

    text = f"🏆 *Leaderboard*\n*{exam} / {topic}*\n\n"

    if not rows:
        text += "_No attempts yet._"
    else:
        for i, (username, first, last, score) in enumerate(rows, 1):
            if username:
                name = f"@{username}"
            else:
                name = f"{first or ''} {last or ''}".strip() or "User"

            text += f"{i}. *{name}* → {score}\n"

    await safe_edit_or_send(
        q,
        text,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="back_result")],
            [InlineKeyboardButton("🏠 Home", callback_data="home")]
        ])
    )


# ================= DONATE =================

async def donate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    text = (
        "💖 *Support This Free MCQ Bot*\n\n"
        "Your contribution helps keep the platform running.\n\n"
        f"*UPI ID:*\n`{UPI_ID}`"
    )

    await safe_edit_or_send(
        q,
        text,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Copy UPI", callback_data="copy_upi")],
            [InlineKeyboardButton("🏠 Home", callback_data="home")]
        ])
    )


async def copy_upi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("UPI copied!", show_alert=False)

    await safe_edit_or_send(
        q,
        f"`{UPI_ID}`",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Home", callback_data="home")]
        ])
    )
# =====================================================
# PART-6 : ADMIN ANALYTICS + USER MANAGEMENT
# =====================================================

# ================= ADMIN PANEL ENTRY =================

# ================= ADMIN PANEL (FULL MENU) =================

async def admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await safe_edit_or_send(q, "⛔ Unauthorized", home_kb())
        return

    await safe_edit_or_send(
        q,
        "🛠 *Admin Control Panel*",
        InlineKeyboardMarkup([

            # ---- ANALYTICS & USERS ----
            [InlineKeyboardButton("📊 Analytics Dashboard", callback_data="admin_stats")],
            [InlineKeyboardButton("👥 Users", callback_data="admin_users")],

            # ---- MCQ DATA ----
            [InlineKeyboardButton("📤 Upload MCQs (Excel)", callback_data="admin_upload")],
            [InlineKeyboardButton("📊 Export MCQs (Excel)", callback_data="admin_export")],
            [InlineKeyboardButton("➕ Add MCQ (Manual)", callback_data="admin_add")],
            [InlineKeyboardButton("🔍 Search / Edit MCQ", callback_data="admin_search")],

            # ---- TEST CONTROL ----
            [InlineKeyboardButton("🚫 Enable / Disable Test", callback_data="admin_toggle_test")],
            [InlineKeyboardButton("🗑 Delete Test", callback_data="admin_delete_test")],

            # ---- UTILITIES ----
            [InlineKeyboardButton("📢 Broadcast Message", callback_data="admin_broadcast")],
            [InlineKeyboardButton("💾 Backup Database", callback_data="admin_backup")],
            [InlineKeyboardButton("♻ Restore Database", callback_data="admin_restore")],

            # ---- EXIT ----
            [InlineKeyboardButton("⬅️ Home", callback_data="home")]
        ])
    )

# ================= ADMIN ANALYTICS =================

async def admin_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    today = datetime.date.today().isoformat()
    last_7 = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()

    # ---- TOTAL USERS ----
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]

    # ---- ACTIVE TODAY ----
    cur.execute("""
        SELECT COUNT(DISTINCT user_id)
        FROM scores
        WHERE test_date=?
    """, (today,))
    active_today = cur.fetchone()[0]

    # ---- ACTIVE LAST 7 DAYS ----
    cur.execute("""
        SELECT COUNT(DISTINCT user_id)
        FROM scores
        WHERE test_date>=?
    """, (last_7,))
    active_7 = cur.fetchone()[0]

    # ---- TOTAL TESTS GIVEN ----
    cur.execute("SELECT COUNT(*) FROM scores")
    total_tests = cur.fetchone()[0]

    # ---- MOST POPULAR TEST ----
    cur.execute("""
        SELECT exam, topic, COUNT(*) AS c
        FROM scores
        GROUP BY exam, topic
        ORDER BY c DESC
        LIMIT 1
    """)
    row = cur.fetchone()
    popular = f"{row[0]} / {row[1]} ({row[2]} attempts)" if row else "N/A"

    # ---- TEST ANALYTICS ----
    cur.execute("SELECT COUNT(*) FROM mcq")
    total_mcqs = cur.fetchone()[0]

    cur.execute("""
        SELECT exam, topic, COUNT(*) AS c
        FROM mcq
        GROUP BY exam, topic
    """)
    per_test = cur.fetchall()

    weak_tests = [
        f"{e} / {t} → {c} MCQs"
        for e, t, c in per_test
        if c < 10
    ]

    weak_text = "\n".join(weak_tests) if weak_tests else "None 🎉"

    text = (
        "📊 *Admin Analytics Dashboard*\n\n"
        f"👥 *Total Users:* {total_users}\n"
        f"🟢 *Active Today:* {active_today}\n"
        f"📆 *Active Last 7 Days:* {active_7}\n"
        f"🧪 *Total Tests Given:* {total_tests}\n\n"
        f"🔥 *Most Popular Test:*\n{popular}\n\n"
        f"📊 *Test Analytics*\n"
        f"• Total MCQs: {total_mcqs}\n"
        f"• Weak Tests (<10 MCQs):\n{weak_text}"
    )

    await safe_edit_or_send(
        q,
        text,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]
        ])
    )


# ================= USER MANAGEMENT (READ-ONLY) =================

async def admin_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    cur.execute("""
        SELECT u.user_id, u.username, u.first_name, u.last_name,
               COUNT(s.id) AS test_count,
               MAX(s.test_date) AS last_active
        FROM users u
        LEFT JOIN scores s ON s.user_id = u.user_id
        GROUP BY u.user_id
        ORDER BY last_active DESC NULLS LAST
        LIMIT 20
    """)

    rows = cur.fetchall()

    text = "👥 *Users (Latest 20)*\n\n"

    if not rows:
        text += "_No users found._"
    else:
        for uid, username, first, last, tests, last_date in rows:
            name = (
                f"@{username}" if username
                else f"{first or ''} {last or ''}".strip()
                or f"User_{uid}"
            )
            text += (
                f"*{name}*\n"
                f"• Tests: {tests or 0}\n"
                f"• Last Active: {last_date or 'Never'}\n\n"
            )

    await safe_edit_or_send(
        q,
        text,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]
        ])
    )
# =====================================================
# PART-7 : EXCEL UPLOAD + EXPORT (MCQ DATA MANAGEMENT)
# =====================================================

# ================= REQUIRED COLUMNS =================

REQUIRED_EXCEL_COLUMNS = [
    "exam", "topic", "question",
    "a", "b", "c", "d",
    "correct", "explanation"
]


# ================= ADMIN UPLOAD ENTRY =================

async def admin_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await safe_edit_or_send(q, "⛔ Unauthorized", home_kb())
        return

    ctx.user_data["await_excel"] = True

    await q.message.reply_text(
        "📤 *Upload MCQ Excel File*\n\n"
        "*Required Columns:*\n"
        "`exam, topic, question, a, b, c, d, correct, explanation`\n\n"
        "• Duplicate MCQs will be skipped\n"
        "• `correct` must be A/B/C/D",
        parse_mode="Markdown"
    )


# ================= HANDLE EXCEL FILE =================

async def handle_excel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not ctx.user_data.get("await_excel"):
        return

    ctx.user_data["await_excel"] = False

    doc = update.message.document
    file = await doc.get_file()

    path = tempfile.mktemp(".xlsx")
    await file.download_to_drive(path)

    try:
        df = pd.read_excel(path)
    except Exception as e:
        await update.message.reply_text(f"❌ Excel read error: {e}")
        return

    # ---- VALIDATE COLUMNS ----
    missing = [c for c in REQUIRED_EXCEL_COLUMNS if c not in df.columns]
    if missing:
        await update.message.reply_text(
            f"❌ Missing required columns:\n{', '.join(missing)}"
        )
        return

    added = 0
    skipped = 0
    invalid = 0

    # ---- PROCESS ROWS ----
    for _, r in df.iterrows():
        try:
            exam = str(r["exam"]).strip()
            topic = str(r["topic"]).strip()
            question = str(r["question"]).strip()
            a = str(r["a"]).strip()
            b = str(r["b"]).strip()
            c = str(r["c"]).strip()
            d = str(r["d"]).strip()
            correct = str(r["correct"]).strip().upper()
            explanation = str(r["explanation"]).strip()

            if correct not in ("A", "B", "C", "D"):
                invalid += 1
                continue

            # ---- DUPLICATE DETECTION ----
            if is_duplicate_mcq(exam, topic, question):
                skipped += 1
                continue

            cur.execute("""
                INSERT INTO mcq
                (exam, topic, question, a, b, c, d, correct, explanation, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                exam, topic, question,
                a, b, c, d,
                correct, explanation
            ))
            added += 1

        except Exception:
            invalid += 1

    conn.commit()

    await update.message.reply_text(
        "✅ *Upload Summary*\n\n"
        f"➕ Added: {added}\n"
        f"⏭ Skipped (Duplicate): {skipped}\n"
        f"⚠️ Invalid Rows: {invalid}",
        parse_mode="Markdown"
    )


# ================= EXPORT MCQ DB =================

async def admin_export(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await safe_edit_or_send(q, "⛔ Unauthorized", home_kb())
        return

    cur.execute("""
        SELECT exam, topic, question, a, b, c, d, correct, explanation, is_active
        FROM mcq
        ORDER BY exam, topic
    """)
    rows = cur.fetchall()

    if not rows:
        await safe_edit_or_send(q, "⚠️ No MCQs found.", home_kb())
        return

    df = pd.DataFrame(rows, columns=[
        "exam", "topic", "question",
        "a", "b", "c", "d",
        "correct", "explanation", "is_active"
    ])

    path = tempfile.mktemp(".xlsx")
    df.to_excel(path, index=False)

    await ctx.bot.send_document(
        chat_id=q.from_user.id,
        document=open(path, "rb"),
        filename="MCQ_Database_Export.xlsx"
    )

    try:
        os.remove(path)
    except Exception:
        pass
# =====================================================
# PART-8 : MANUAL MCQ WIZARD + SEARCH / EDIT MCQ
# =====================================================

# ================= MANUAL ADD ENTRY =================

async def admin_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await safe_edit_or_send(q, "⛔ Unauthorized", home_kb())
        return

    # Initialize wizard
    ctx.user_data["mcq_wizard"] = {
        "step": 1,
        "data": {},
        "force": False
    }

    await q.message.reply_text(
        "✍️ *Manual MCQ Add*\n\n"
        "📝 *Step 1/9*\n"
        "Enter *Exam Name:*",
        parse_mode="Markdown"
    )


# ================= WIZARD TEXT ROUTER =================

async def admin_text_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    text = update.message.text.strip()

    # -------- FORCE ADD DUPLICATE --------
    if text == "/force_add" and ctx.user_data.get("pending_duplicate"):
        ctx.user_data["mcq_wizard"]["force"] = True
        await finalize_mcq(update, ctx)
        return

    wizard = ctx.user_data.get("mcq_wizard")

    if not wizard:
        return

    step = wizard["step"]
    data = wizard["data"]

    fields = [
        "exam", "topic", "question",
        "a", "b", "c", "d",
        "correct", "explanation"
    ]

    # ---------- CANCEL ----------
    if text.lower() == "/cancel":
        ctx.user_data.pop("mcq_wizard", None)
        await update.message.reply_text("❌ MCQ add cancelled.")
        return

    # ---------- STORE DATA ----------
    key = fields[step - 1]
    data[key] = text.strip()

    wizard["step"] += 1

    # ---------- NEXT PROMPT ----------
    prompts = [
        "Enter *Topic Name:*",
        "Enter *Question:*",
        "Enter *Option A:*",
        "Enter *Option B:*",
        "Enter *Option C:*",
        "Enter *Option D:*",
        "Enter *Correct Answer* (A/B/C/D):",
        "Enter *Explanation:*"
    ]

    if wizard["step"] <= 9:
        await update.message.reply_text(
            f"📝 *Step {wizard['step']}/9*\n{prompts[wizard['step'] - 2]}",
            parse_mode="Markdown"
        )
    else:
        await preview_mcq(update, ctx)


# ================= PREVIEW MCQ =================

async def preview_mcq(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    wizard = ctx.user_data.get("mcq_wizard")
    data = wizard["data"]

    # Normalize correct option
    data["correct"] = data["correct"].upper()

    text = (
        "👀 *Preview MCQ*\n\n"
        f"*Exam:* {data['exam']}\n"
        f"*Topic:* {data['topic']}\n\n"
        f"*Q.* {data['question']}\n\n"
        f"A. {data['a']}\n"
        f"B. {data['b']}\n"
        f"C. {data['c']}\n"
        f"D. {data['d']}\n\n"
        f"✅ *Correct:* {data['correct']}\n"
        f"📘 *Explanation:* {data['explanation']}"
    )

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Save", callback_data="wizard_save")],
            [InlineKeyboardButton("❌ Cancel", callback_data="wizard_cancel")]
        ])
    )


# ================= FINALIZE MCQ =================

async def finalize_mcq(update_or_message, ctx: ContextTypes.DEFAULT_TYPE):
    wizard = ctx.user_data.get("mcq_wizard")

    # 🔐 SAFETY GUARD
    if not wizard or "data" not in wizard:
        try:
            await update_or_message.reply_text(
                "⚠️ MCQ session expired.\nPlease start manual add again."
            )
        except Exception:
            pass
        return

    data = wizard["data"]

    # ---- NORMALIZE ----
    data["correct"] = data["correct"].upper()

    # ---- DUPLICATE CHECK ----
    if not wizard.get("force") and is_duplicate_mcq(
        data["exam"], data["topic"], data["question"]
    ):
        ctx.user_data["pending_duplicate"] = True
        await update_or_message.reply_text(
            "⚠️ *Duplicate MCQ detected!*\n\n"
            "Send `/force_add` to save anyway\n"
            "or `/cancel` to abort.",
            parse_mode="Markdown"
        )
        return

    # ---- SAVE MCQ ----
    cur.execute("""
        INSERT INTO mcq
        (exam, topic, question, a, b, c, d, correct, explanation, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (
        data["exam"], data["topic"], data["question"],
        data["a"], data["b"], data["c"], data["d"],
        data["correct"], data["explanation"]
    ))
    conn.commit()

    # ---- CLEAN STATE ----
    ctx.user_data.pop("mcq_wizard", None)
    ctx.user_data.pop("pending_duplicate", None)

    await update_or_message.reply_text("✅ MCQ added successfully!")

# ================= WIZARD CALLBACKS =================

async def wizard_save(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await finalize_mcq(q.message, ctx)


async def wizard_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    ctx.user_data.pop("mcq_wizard", None)
    ctx.user_data.pop("pending_duplicate", None)

    await q.message.reply_text("❌ MCQ add cancelled.")


# ================= SEARCH MCQ =================

async def admin_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        return

    ctx.user_data["admin_mode"] = "search"
    await q.message.reply_text("🔍 Send keyword to search MCQ")


# ================= SEARCH RESULT =================

async def admin_search_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if ctx.user_data.get("admin_mode") != "search":
        return

    text = update.message.text.strip()

    cur.execute("""
        SELECT id, question
        FROM mcq
        WHERE question LIKE ?
        LIMIT 20
    """, (f"%{text}%",))

    rows = cur.fetchall()

    if not rows:
        await update.message.reply_text("❌ No MCQ found.")
        return

    kb = [[InlineKeyboardButton(
        f"MCQ {r[0]}: {r[1][:40]}…",
        callback_data=f"edit_mcq::{r[0]}"
    )] for r in rows]

    await update.message.reply_text(
        "🔍 Select MCQ to edit:",
        reply_markup=InlineKeyboardMarkup(kb)
    )


# ================= EDIT MCQ MENU =================

async def edit_mcq_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    mcq_id = int(q.data.split("::")[1])
    ctx.user_data["edit_mcq_id"] = mcq_id

    await safe_edit_or_send(
        q,
        f"✏️ *Edit MCQ #{mcq_id}*\nSelect field:",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("Question", callback_data="edit_field::question")],
            [InlineKeyboardButton("Option A", callback_data="edit_field::a")],
            [InlineKeyboardButton("Option B", callback_data="edit_field::b")],
            [InlineKeyboardButton("Option C", callback_data="edit_field::c")],
            [InlineKeyboardButton("Option D", callback_data="edit_field::d")],
            [InlineKeyboardButton("Correct (A/B/C/D)", callback_data="edit_field::correct")],
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]
        ])
    )


# ================= EDIT FIELD SELECT =================

async def edit_field(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    field = q.data.split("::")[1]
    ctx.user_data["admin_mode"] = "edit"
    ctx.user_data["edit_field"] = field

    await q.message.reply_text(
        f"✏️ Send new value for *{field}*:",
        parse_mode="Markdown"
    )


# ================= APPLY EDIT =================

async def admin_edit_apply(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if ctx.user_data.get("admin_mode") != "edit":
        return

    text = update.message.text.strip()
    field = ctx.user_data.get("edit_field")
    mcq_id = ctx.user_data.get("edit_mcq_id")

    value = text.upper() if field == "correct" else text

    cur.execute(f"UPDATE mcq SET {field}=? WHERE id=?", (value, mcq_id))
    conn.commit()

    # Cleanup
    ctx.user_data.pop("admin_mode", None)
    ctx.user_data.pop("edit_field", None)
    ctx.user_data.pop("edit_mcq_id", None)

    await update.message.reply_text("✅ MCQ updated successfully.")
# =====================================================
# PART-9 : ENABLE / DISABLE TEST + DELETE TEST
# =====================================================

# ================= ENABLE / DISABLE TEST =================

async def admin_toggle_test(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await safe_edit_or_send(q, "⛔ Unauthorized", home_kb())
        return

    # Fetch distinct exam-topic with current state
    cur.execute("""
        SELECT exam, topic, MAX(is_active)
        FROM mcq
        GROUP BY exam, topic
        ORDER BY exam, topic
    """)
    rows = cur.fetchall()

    if not rows:
        await safe_edit_or_send(q, "⚠️ No tests found.", home_kb())
        return

    kb = []
    for exam, topic, active in rows:
        status = "🟢 ON" if active else "🔴 OFF"
        kb.append([
            InlineKeyboardButton(
                f"{exam} | {topic} — {status}",
                callback_data=f"toggle_test::{exam}::{topic}"
            )
        ])

    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")])

    await safe_edit_or_send(
        q,
        "🚫 *Enable / Disable Tests*\nTap to toggle status:",
        InlineKeyboardMarkup(kb)
    )


async def admin_toggle_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        return

    _, exam, topic = q.data.split("::", 2)

    # Get current state
    cur.execute("""
        SELECT is_active
        FROM mcq
        WHERE exam=? AND topic=?
        LIMIT 1
    """, (exam, topic))
    row = cur.fetchone()

    if not row:
        await q.message.reply_text("⚠️ Test not found.")
        return

    new_state = 0 if row[0] == 1 else 1

    cur.execute("""
        UPDATE mcq
        SET is_active=?
        WHERE exam=? AND topic=?
    """, (new_state, exam, topic))
    conn.commit()

    await q.message.reply_text(
        f"✅ Test `{exam} / {topic}` set to "
        f"{'ENABLED' if new_state else 'DISABLED'}",
        parse_mode="Markdown"
    )


# ================= DELETE TEST (DANGEROUS) =================

async def admin_delete_test(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await safe_edit_or_send(q, "⛔ Unauthorized", home_kb())
        return

    cur.execute("""
        SELECT DISTINCT exam, topic
        FROM mcq
        ORDER BY exam, topic
    """)
    rows = cur.fetchall()

    if not rows:
        await safe_edit_or_send(q, "⚠️ No tests found.", home_kb())
        return

    kb = [
        [InlineKeyboardButton(
            f"{exam} | {topic}",
            callback_data=f"delete_test::{exam}::{topic}"
        )]
        for exam, topic in rows
    ]

    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")])

    await safe_edit_or_send(
        q,
        "🗑 *DELETE TEST (Dangerous)*\nSelect exam/topic:",
        InlineKeyboardMarkup(kb)
    )


async def admin_delete_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        return

    _, exam, topic = q.data.split("::", 2)

    # Confirmation screen
    await safe_edit_or_send(
        q,
        "⚠️ *CONFIRM DELETE*\n\n"
        f"Exam: *{exam}*\n"
        f"Topic: *{topic}*\n\n"
        "❗ This will permanently delete:\n"
        "• All MCQs\n"
        "• All Scores\n\n"
        "*This action is IRREVERSIBLE!*",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="admin_panel")],
            [InlineKeyboardButton(
                "🔥 YES, DELETE",
                callback_data=f"delete_final::{exam}::{topic}"
            )]
        ])
    )


async def admin_delete_final(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        return

    _, exam, topic = q.data.split("::", 2)

    # Delete MCQs and scores
    cur.execute("DELETE FROM mcq WHERE exam=? AND topic=?", (exam, topic))
    cur.execute("DELETE FROM scores WHERE exam=? AND topic=?", (exam, topic))
    conn.commit()

    await q.message.reply_text(
        f"✅ Test `{exam} / {topic}` deleted permanently.",
        parse_mode="Markdown"
    )
# =====================================================
# PART-10 : BROADCAST + BACKUP / RESTORE
# =====================================================

# ================= BROADCAST =================

async def admin_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await safe_edit_or_send(q, "⛔ Unauthorized", home_kb())
        return

    ctx.user_data["admin_mode"] = "broadcast"

    await q.message.reply_text(
        "📢 *Broadcast Mode*\n\n"
        "Send the message you want to broadcast to all users.\n\n"
        "❌ Send `/cancel` to abort.",
        parse_mode="Markdown"
    )


async def broadcast_text_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if ctx.user_data.get("admin_mode") != "broadcast":
        return

    text = update.message.text

    # Cancel broadcast
    if text.lower() == "/cancel":
        ctx.user_data.pop("admin_mode", None)
        await update.message.reply_text("❌ Broadcast cancelled.")
        return

    cur.execute("SELECT user_id FROM users")
    users = cur.fetchall()

    success = 0
    failed = 0

    for (uid,) in users:
        try:
            await ctx.bot.send_message(uid, text)
            success += 1
        except Exception:
            failed += 1

    ctx.user_data.pop("admin_mode", None)

    await update.message.reply_text(
        "✅ *Broadcast Complete*\n\n"
        f"📨 Sent: {success}\n"
        f"❌ Failed: {failed}",
        parse_mode="Markdown"
    )


# ================= BACKUP DATABASE =================

async def admin_backup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await safe_edit_or_send(q, "⛔ Unauthorized", home_kb())
        return

    await ctx.bot.send_document(
        chat_id=q.from_user.id,
        document=open("mcq.db", "rb"),
        filename="mcq_backup.db"
    )


# ================= RESTORE DATABASE =================

async def admin_restore(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        return

    ctx.user_data["admin_mode"] = "restore"

    await q.message.reply_text(
        "♻️ *Database Restore*\n\n"
        "Upload `.db` file to restore database.\n\n"
        "⚠️ This will overwrite current DB.\n"
        "Bot restart required after restore.",
        parse_mode="Markdown"
    )


async def handle_restore(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if ctx.user_data.get("admin_mode") != "restore":
        return

    doc = update.message.document

    if not doc.file_name.endswith(".db"):
        await update.message.reply_text("❌ Invalid file. Upload `.db` only.")
        return

    file = await doc.get_file()
    path = tempfile.mktemp(".db")
    await file.download_to_drive(path)

    try:
        conn.close()
        os.replace(path, "mcq.db")
    except Exception as e:
        await update.message.reply_text(f"❌ Restore failed: {e}")
        return

    ctx.user_data.pop("admin_mode", None)

    await update.message.reply_text(
        "✅ *Database restored successfully!*\n\n"
        "⚠️ Please restart the bot now to apply changes.",
        parse_mode="Markdown"
    )
# =====================================================
# PART-11 : HANDLERS REGISTRATION + MAIN RUNNER
# =====================================================

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # ================= USER COMMANDS =================
    app.add_handler(CommandHandler("start", start))

    # ================= COMMON NAVIGATION =================
    app.add_handler(CallbackQueryHandler(home, "^home$"))

    # ================= USER EXAM FLOW =================
    app.add_handler(CallbackQueryHandler(exam_select, "^exam::"))
    app.add_handler(CallbackQueryHandler(topic_select, "^topic::"))
    app.add_handler(CallbackQueryHandler(answer, "^ans::"))
    app.add_handler(CallbackQueryHandler(next_q, "^next$"))
    app.add_handler(CallbackQueryHandler(prev_q, "^prev$"))
    app.add_handler(CallbackQueryHandler(finish_test, "^finish$"))

    # ================= REVIEW SYSTEM =================
    app.add_handler(CallbackQueryHandler(review_all, "^review_all$"))
    app.add_handler(CallbackQueryHandler(review_wrong, "^review_wrong$"))
    app.add_handler(CallbackQueryHandler(review_next, "^review_next$"))
    app.add_handler(CallbackQueryHandler(review_prev, "^review_prev$"))
    app.add_handler(CallbackQueryHandler(back_result, "^back_result$"))

    # ================= PDF =================
    app.add_handler(CallbackQueryHandler(pdf_result, "^pdf_result$"))

    # ================= PROFILE / LEADERBOARD / DONATE =================
    app.add_handler(CallbackQueryHandler(profile, "^profile$"))
    app.add_handler(CallbackQueryHandler(leaderboard, "^leaderboard$"))
    app.add_handler(CallbackQueryHandler(donate, "^donate$"))
    app.add_handler(CallbackQueryHandler(copy_upi, "^copy_upi$"))

    # ================= ADMIN PANEL =================
    app.add_handler(CallbackQueryHandler(admin_panel, "^admin_panel$"))
    app.add_handler(CallbackQueryHandler(admin_stats, "^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_users, "^admin_users$"))

    # ================= ADMIN DATA MANAGEMENT =================
    app.add_handler(CallbackQueryHandler(admin_upload, "^admin_upload$"))
    app.add_handler(CallbackQueryHandler(admin_export, "^admin_export$"))

    # ================= ADMIN MANUAL MCQ =================
    app.add_handler(CallbackQueryHandler(admin_add, "^admin_add$"))
    app.add_handler(CallbackQueryHandler(wizard_save, "^wizard_save$"))
    app.add_handler(CallbackQueryHandler(wizard_cancel, "^wizard_cancel$"))

    # ================= SEARCH / EDIT MCQ =================
    app.add_handler(CallbackQueryHandler(admin_search, "^admin_search$"))
    app.add_handler(CallbackQueryHandler(edit_mcq_menu, "^edit_mcq::"))
    app.add_handler(CallbackQueryHandler(edit_field, "^edit_field::"))

    # ================= ENABLE / DISABLE & DELETE TEST =================
    app.add_handler(CallbackQueryHandler(admin_toggle_test, "^admin_toggle_test$"))
    app.add_handler(CallbackQueryHandler(admin_toggle_action, "^toggle_test::"))
    app.add_handler(CallbackQueryHandler(admin_delete_test, "^admin_delete_test$"))
    app.add_handler(CallbackQueryHandler(admin_delete_confirm, "^delete_test::"))
    app.add_handler(CallbackQueryHandler(admin_delete_final, "^delete_final::"))

    # ================= BROADCAST / BACKUP / RESTORE =================
    app.add_handler(CallbackQueryHandler(admin_broadcast, "^admin_broadcast$"))
    app.add_handler(CallbackQueryHandler(admin_backup, "^admin_backup$"))
    app.add_handler(CallbackQueryHandler(admin_restore, "^admin_restore$"))

    # ================= TEXT ROUTERS (ADMIN) =================
    app.add_handler(
        MessageHandler(filters.TEXT & filters.User(ADMIN_IDS), admin_text_router)
    )
    app.add_handler(
        MessageHandler(filters.TEXT & filters.User(ADMIN_IDS), admin_search_router)
    )
    app.add_handler(
        MessageHandler(filters.TEXT & filters.User(ADMIN_IDS), broadcast_text_router)
    )

    # ================= FILE HANDLERS (ADMIN) =================
    app.add_handler(
        MessageHandler(filters.Document.ALL & filters.User(ADMIN_IDS), handle_excel)
    )
    app.add_handler(
        MessageHandler(filters.Document.ALL & filters.User(ADMIN_IDS), handle_restore)
    )

    print("🤖 MCQ EXAM BOT — PRODUCTION RUNNING...")
    app.run_polling()


if __name__ == "__main__":
    main()
