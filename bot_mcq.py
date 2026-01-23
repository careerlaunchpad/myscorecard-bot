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

# ---- SAFE MIGRATION FOR TEST ENABLE / DISABLE ----
cur.execute("PRAGMA table_info(mcq)")
cols = [c[1] for c in cur.fetchall()]

if "is_active" not in cols:
    cur.execute("ALTER TABLE mcq ADD COLUMN is_active INTEGER DEFAULT 1")
    conn.commit()


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

def normalize_question(q):
    return " ".join(q.lower().split())



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

def get_mcq_by_id(mcq_id):
    cur.execute("SELECT * FROM mcq WHERE id=?", (mcq_id,))
    return cur.fetchone()

def is_duplicate_mcq(exam, topic, question):
    nq = normalize_question(question)

    cur.execute("""
        SELECT COUNT(*) FROM mcq
        WHERE exam=? AND topic=? AND lower(question)=?
    """, (exam, topic, nq))

    return cur.fetchone()[0] > 0

#-----------admin analytics-------------------------
def get_admin_analytics():
    # Total users
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0] or 0

    # Active today
    today = datetime.date.today().isoformat()
    cur.execute(
        "SELECT COUNT(DISTINCT user_id) FROM scores WHERE test_date=?",
        (today,)
    )
    active_today = cur.fetchone()[0] or 0

    # Active last 7 days
    cur.execute("""
        SELECT COUNT(DISTINCT user_id)
        FROM scores
        WHERE test_date >= date('now','-7 day')
    """)
    active_7d = cur.fetchone()[0] or 0

    # Total tests given
    cur.execute("SELECT COUNT(*) FROM scores")
    total_tests = cur.fetchone()[0] or 0

    # Most attempted exam/topic
    cur.execute("""
        SELECT exam, topic, COUNT(*) as cnt
        FROM scores
        GROUP BY exam, topic
        ORDER BY cnt DESC
        LIMIT 1
    """)
    row = cur.fetchone()

    if row:
        popular_test = f"{row[0]} / {row[1]} ({row[2]} attempts)"
    else:
        popular_test = "No data yet"

    return {
        "total_users": total_users,
        "active_today": active_today,
        "active_7d": active_7d,
        "total_tests": total_tests,
        "popular_test": popular_test
    }

# ================= UI =================
def home_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="start_new")]])

#------exam button----------
def exam_kb():
    cur.execute("SELECT DISTINCT exam FROM mcq WHERE is_active=1")
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
    cur.execute("SELECT COUNT(*) FROM mcq WHERE exam=? AND topic=? AND is_active=1", (exam, topic))
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
        cur.execute("SELECT * FROM mcq WHERE exam=? AND topic=? AND is_active=1 ORDER BY RANDOM() LIMIT 1", (exam, topic))
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
    q = update.callback_query
    await q.answer()

    exam = ctx.user_data.get("exam")
    topic = ctx.user_data.get("topic")

    if not exam or not topic:
        await safe_edit_or_send(
            q,
            "⚠️ Leaderboard देखने के लिए पहले कोई test complete करें",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
            ])
        )
        return

    cur.execute("""
        SELECT u.username, MAX(s.score)
        FROM scores s
        JOIN users u ON u.user_id = s.user_id
        WHERE s.exam=? AND s.topic=?
        GROUP BY s.user_id
        ORDER BY MAX(s.score) DESC
        LIMIT 10
    """, (exam, topic))

    rows = cur.fetchall()

    text = f"🏆 *Leaderboard — {exam} / {topic}*\n\n"
    for i, r in enumerate(rows, 1):
        name = r[0] or "User"
        text += f"{i}. *{name}* → {r[1]}\n"

    await safe_edit_or_send(
        q,
        text,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="back_result")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )

# ================= PROFILE =================
async def profile(update, ctx):
    q=update.callback_query; await q.answer()
    u=q.from_user
    cur.execute(
        """SELECT exam, topic, MAX(score) as score, total, MAX(test_date)
        FROM scores
        WHERE user_id=?
        GROUP BY exam, topic
        ORDER BY MAX(test_date) DESC""",
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
    q = update.callback_query
    await q.answer()

    text = (
        "❤️ *Support This Free Learning Bot*\n\n"
        "यह MCQ Bot सभी students के लिए हमेशा *FREE* रहेगा 📚\n"
        "आपका छोटा-सा contribution हमें help करता है:\n\n"
        "• Server & hosting cost\n"
        "• New exams & features add करने में\n"
        "• Bot को fast & reliable रखने में\n\n"
        "🙏 *Donate only if you truly find this useful.*\n\n"
        f"💳 *UPI ID:*\n`{UPI_ID}`\n\n"
        "_Thank you for supporting free education 💙_"
    )

    await safe_edit_or_send(
        q,
        text,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Copy UPI ID", callback_data="copy_upi")],
            [InlineKeyboardButton("⬅️ Back", callback_data="start_new")]
        ])
    )
async def copy_upi(update, ctx):
    await update.callback_query.answer("UPI ID copied 👍")

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

# ================= ADMIN PANEL =================
async def admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await safe_edit_or_send(
            q,
            "⛔ You are not authorized to access admin panel",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
            ])
        )
        return

    stats = get_admin_analytics()

    text = (
        "🛠 *Admin Analytics Dashboard*\n\n"
        f"👥 *Total Users:* {stats['total_users']}\n"
        f"🔥 *Active Today:* {stats['active_today']}\n"
        f"📆 *Active (7 Days):* {stats['active_7d']}\n"
        f"📝 *Total Tests Given:* {stats['total_tests']}\n\n"
        f"🏆 *Most Popular Test:*\n{stats['popular_test']}"
    )

    await safe_edit_or_send(
        q,
        text,
        InlineKeyboardMarkup([
            #[InlineKeyboardButton("📊 Analytics", callback_data="admin_stats")],
            [InlineKeyboardButton("👥 User Management", callback_data="admin_users")],
            [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
            [InlineKeyboardButton("💾 Backup Database", callback_data="admin_backup")],
            [InlineKeyboardButton("♻️ Restore Database", callback_data="admin_restore")],
            [InlineKeyboardButton("➕ Add MCQ (Manual)", callback_data="admin_add_mcq")],

            [InlineKeyboardButton("🚫 Enable / Disable Test", callback_data="admin_toggle_test")],

            
            [InlineKeyboardButton("🔁 Duplicate MCQs", callback_data="admin_duplicates")],
            
            [InlineKeyboardButton("🔍 Search / Edit MCQ", callback_data="admin_search")],
            
            [InlineKeyboardButton("📤 Upload MCQs (Excel)", callback_data="admin_upload")],
            [InlineKeyboardButton("🧾 Export MCQ DB", callback_data="admin_export")],
            
            [InlineKeyboardButton("⬅️ Back", callback_data="start_new")]
        ])
    )
#---------force add ----------
async def force_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    d = ctx.user_data.get("force_mcq")
    if not d:
        await update.message.reply_text("❌ No MCQ pending for force add")
        return

    cur.execute("""
        INSERT INTO mcq (exam, topic, question, a, b, c, d, correct, explanation)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        d["exam"], d["topic"], d["question"],
        d["a"], d["b"], d["c"], d["d"],
        d["correct"], d["explanation"]
    ))
    conn.commit()

    ctx.user_data.clear()
    await update.message.reply_text("✅ Duplicate MCQ force-added successfully")

#------------admin upload file------------------------
async def admin_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["awaiting_excel"] = True

    await safe_edit_or_send(
        q,
        "📤 *Upload Excel file*\n\nColumns:\nexam, topic, question, a, b, c, d, correct, explanation",
        InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]])
    )
#-------------excel handle-----------------------
async def handle_excel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # 🔐 Admin only
    if update.effective_user.id not in ADMIN_IDS:
        return

    if not ctx.user_data.get("awaiting_excel"):
        return

    ctx.user_data["awaiting_excel"] = False

    doc = update.message.document
    if not doc.file_name.endswith((".xlsx", ".xls")):
        await update.message.reply_text("❌ Please upload a valid Excel file (.xlsx)")
        return

    file = await doc.get_file()
    path = tempfile.mktemp(suffix=".xlsx")
    await file.download_to_drive(path)

    try:
        df = pd.read_excel(path)
    except Exception as e:
        await update.message.reply_text(f"❌ Excel read error:\n{e}")
        return

    required_cols = {"exam","topic","question","a","b","c","d","correct","explanation"}
    if not required_cols.issubset(df.columns):
        await update.message.reply_text(
            "❌ Invalid Excel format\n\nRequired columns:\n"
            "exam, topic, question, a, b, c, d, correct, explanation"
        )
        return

    added = 0
    skipped = 0

    for _, r in df.iterrows():
        if is_duplicate_mcq(r.exam, r.topic, r.question):
            skipped += 1
            continue

        cur.execute("""
            INSERT INTO mcq (
                exam, topic, question,
                a, b, c, d,
                correct, explanation,
                is_active
            )

            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)

        """, (
            str(r.exam).strip(),
            str(r.topic).strip(),
            str(r.question).strip(),
            str(r.a).strip(),
            str(r.b).strip(),
            str(r.c).strip(),
            str(r.d).strip(),
            str(r.correct).strip().upper(),
            str(r.explanation).strip()
        ))

        added += 1

    conn.commit()

    await update.message.reply_text(
        f"✅ *Excel Upload Complete*\n\n"
        f"➕ Added: {added}\n"
        f"⏭ Skipped (Duplicates): {skipped}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Admin", callback_data="admin_panel")]
        ])
    )

#-----------admin export ------------------
async def admin_export(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    df = pd.read_sql("SELECT * FROM mcq", conn)
    path = tempfile.mktemp(".xlsx")
    df.to_excel(path, index=False)

    await ctx.bot.send_document(q.from_user.id, open(path, "rb"))

#------------Admin Search / Edit MCQ------------
async def admin_search(update, ctx):
    q = update.callback_query
    await q.answer()

    ctx.user_data.clear()
    ctx.user_data["admin_mode"] = "search"

    await safe_edit_or_send(

        q,
        "🔍 *Search MCQ*\n\n"
        "Type any keyword from:\n"
        "• Question text\n"
        "• Options (A/B/C/D)\n\n"
        "_Example:_ constitution / GDP / Article",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]
        ])
    )

#---------------------Admin text router (SEARCH + EDIT SAVE)------------
async def admin_text_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    text = update.message.text.strip()

    # ❌ CANCEL ANY ADMIN MODE
    if text == "/cancel":
        ctx.user_data.clear()
        await update.message.reply_text("❌ Admin operation cancelled")
        return

    mode = ctx.user_data.get("admin_mode")

    # ===============================
    # 📢 BROADCAST MODE
    # ===============================
    if mode == "broadcast":
        cur.execute("SELECT user_id FROM users")
        users = cur.fetchall()

        sent = failed = 0
        for (uid,) in users:
            try:
                await ctx.bot.send_message(uid, text)
                sent += 1
            except:
                failed += 1

        ctx.user_data.clear()
        await update.message.reply_text(
            f"✅ Broadcast Completed\n\n📨 Sent: {sent}\n❌ Failed: {failed}"
        )
        return

    # ===============================
    # ✍️ MANUAL MCQ ADD MODE
    # ===============================
    if update.message.text.lower() == "/cancel":

        ctx.user_data.clear()
        await update.message.reply_text(
            "❌ Manual MCQ add cancelled",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Admin", callback_data="admin_panel")]
            ])
        )
        return

    if ctx.user_data.get("admin_add"):
        await admin_add_mcq_text(update, ctx)
        return

    # ===============================
    # 🔍 SEARCH MODE
    # ===============================
    if mode == "search":
        kw = text
        cur.execute(
            "SELECT id, question FROM mcq WHERE question LIKE ? LIMIT 20",
            (f"%{kw}%",)
        )
        rows = cur.fetchall()

        if not rows:
            await update.message.reply_text("❌ No MCQ found")
            return

        kb = [[InlineKeyboardButton(
                f"❓ MCQ {r[0]}: {r[1][:35]}…",
                callback_data=f"admin_mcq_{r[0]}"
            )
            ]
            for r in rows
        ]
        kb.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")])

        await update.message.reply_text(
            "📋 Select MCQ to Edit",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

   

# ✏️ EDIT FIELD SAVE MODE (AUTO REFRESH)
# ===============================
    if ctx.user_data.get("admin_mode") == "edit_text":
        field = ctx.user_data["edit_field"]
        mcq_id = ctx.user_data["edit_id"]
        value = update.message.text.strip()

        cur.execute(
            f"UPDATE mcq SET {field}=? WHERE id=?",
            (value, mcq_id)
        )
        conn.commit()

    # ❗ clear only edit flags
        ctx.user_data.pop("admin_mode", None)
        ctx.user_data.pop("edit_field", None)

        await update.message.reply_text(
            "✅ *MCQ Updated Successfully*",
            parse_mode="Markdown"
        )

    # 🔁 AUTO REFRESH EDIT MENU (STEP-5.7)
        fake_update = Update(
            update.update_id,
            callback_query=type(
                "obj",
                (),
                {
                    "data": f"admin_mcq_{mcq_id}",
                    "message": update.message,
                    "answer": lambda *a, **k: None
                }
            )
        )

        await admin_mcq_menu(fake_update, ctx)
        return


    elif ctx.user_data.get("admin_mode") == "edit_field":

        field = ctx.user_data["field"]
        mcq_id = ctx.user_data["edit_id"]
        value = update.message.text.strip()

    if field == "correct":
        value = value.upper()
        if value not in ["A", "B", "C", "D"]:
            await update.message.reply_text(
                "❌ Invalid correct option\nSend only: A / B / C / D"
            )
            return

    cur.execute(
        f"UPDATE mcq SET {field}=? WHERE id=?",
        (value, mcq_id)
    )
    conn.commit()

    ctx.user_data.clear()

    await update.message.reply_text(
        "✅ *MCQ Updated Successfully*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Admin", callback_data="admin_panel")]
        ])
    )

# ===== ADMIN: SET CORRECT ANSWER =====
async def admin_set_correct(update, ctx):
    q = update.callback_query
    await q.answer()

    if ctx.user_data.get("admin_mode") != "set_correct":
        await q.message.reply_text("⚠️ Invalid state")
        return

    mcq_id = ctx.user_data.get("edit_id")
    correct = q.data[-1]   # A / B / C / D

    cur.execute(
        "UPDATE mcq SET correct=? WHERE id=?",
        (correct, mcq_id)
    )
    conn.commit()

    ctx.user_data.clear()

    await q.message.reply_text(
        f"✅ *Correct Answer Updated:* `{correct}`",
        parse_mode="Markdown"
    )

    # 🔁 AUTO REFRESH EDIT MENU (SAFE)
    fake_update = Update(
        update.update_id,
        callback_query=update.callback_query
    )
    fake_update.callback_query.data = f"admin_mcq_{mcq_id}"

    await admin_mcq_menu(fake_update, ctx)

#------MCQ Edit Menu-------------
async def admin_mcq_menu(update, ctx):
    q = update.callback_query
    await q.answer()

    mcq_id = int(q.data.split("_")[-1])
    ctx.user_data["edit_id"] = mcq_id

    cur.execute("SELECT * FROM mcq WHERE id=?", (mcq_id,))
    m = cur.fetchone()

    await safe_edit_or_send(
        q,
        f"✏️ *Edit MCQ*\n\n"
        f"*MCQ ID:* {m[0]}\n\n"
        f"❓ {m[3][:200]}",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("✏ Question", callback_data="edit_question")],
            [InlineKeyboardButton("🅰 A", callback_data="edit_a"),
             InlineKeyboardButton("🅱 B", callback_data="edit_b")],
            [InlineKeyboardButton("🅲 C", callback_data="edit_c"),
             InlineKeyboardButton("🅳 D", callback_data="edit_d")],
            [InlineKeyboardButton("✔ Correct", callback_data="edit_correct")],
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]
        ])
    )
#------Edit field selector----------
async def admin_edit_field(update, ctx):
    q = update.callback_query
    await q.answer()

    field = q.data.replace("edit_", "")
    mcq_id = ctx.user_data.get("edit_id")

    m = get_mcq_by_id(mcq_id)
    if not m:
        await q.message.reply_text("❌ MCQ not found")
        return

    field_map = {
        "question": ("Question", m[3]),
        "a": ("Option A", m[4]),
        "b": ("Option B", m[5]),
        "c": ("Option C", m[6]),
        "d": ("Option D", m[7]),
    }

    # 🔴 Correct answer handled separately
    if field == "correct":
        await q.message.reply_text(
            "✔ Select Correct Answer",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("A", callback_data="set_correct_A"),
                 InlineKeyboardButton("B", callback_data="set_correct_B")],
                [InlineKeyboardButton("C", callback_data="set_correct_C"),
                 InlineKeyboardButton("D", callback_data="set_correct_D")],
            ])
        )
        ctx.user_data["admin_mode"] = "set_correct"
        return

    label, old_value = field_map[field]

    ctx.user_data["admin_mode"] = "edit_text"
    ctx.user_data["edit_field"] = field

    await q.message.reply_text(
        f"✏️ *Edit {label}*\n\n"
        f"*OLD:*\n{old_value}\n\n"
        f"अब नया value भेजें 👇",
        parse_mode="Markdown"
    )


#--------admin user control------------------
async def admin_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        return

    cur.execute("""
        SELECT 
            u.user_id,
            u.username,
            u.first_name,
            u.last_name,
            COUNT(s.id) as tests,
            MAX(s.test_date) as last_active
        FROM users u
        LEFT JOIN scores s ON u.user_id = s.user_id
        GROUP BY u.user_id
        ORDER BY last_active DESC
        LIMIT 20
    """)
    rows = cur.fetchall()

    if not rows:
        await safe_edit_or_send(
            q,
            "👥 No users found",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]
            ])
        )
        return

    text = "👥 *User Management (Read-Only)*\n\n"

    kb = []

    for r in rows:
        uid, username, fn, ln, tests, last = r

        name = (
            f"@{username}" if username
            else f"{fn or ''} {ln or ''}".strip()
            or f"User_{uid}"
        )

        text += (
            f"👤 *{name}*\n"
            f"📝 Tests: {tests or 0}\n"
            f"📅 Last Active: {last or 'N/A'}\n\n"
        )

        kb.append([
            InlineKeyboardButton(
                f"🔍 {name[:25]}",
                callback_data=f"admin_user_{uid}"
            )
        ])

    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")])

    await safe_edit_or_send(q, text, InlineKeyboardMarkup(kb))

#-------admin user history------- ------------
async def admin_user_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        return

    user_id = int(q.data.split("_")[-1])

    cur.execute(
        "SELECT exam, topic, score, total, test_date FROM scores WHERE user_id=? ORDER BY id DESC",
        (user_id,)
    )
    rows = cur.fetchall()

    cur.execute(
        "SELECT username, first_name, last_name FROM users WHERE user_id=?",
        (user_id,)
    )
    u = cur.fetchone()

    name = (
        f"@{u[0]}" if u and u[0]
        else f"{u[1] or ''} {u[2] or ''}".strip()
        if u else f"User_{user_id}"
    )

    text = f"👤 *{name}*\n\n"

    if not rows:
        text += "_No tests given yet_"
    else:
        for r in rows:
            text += (
                f"📚 {r[0]} / {r[1]} → *{r[2]}/{r[3]}* ({r[4]})\n"
            )

    await safe_edit_or_send(
        q,
        text,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_users")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )
#-------------admin duplicataed--------------
async def admin_duplicates(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        return

    cur.execute("""
        SELECT exam, topic, question, COUNT(*) as cnt
        FROM mcq
        GROUP BY exam, topic, question
        HAVING cnt > 1
        ORDER BY cnt DESC
        LIMIT 50
    """)

    rows = cur.fetchall()

    if not rows:
        await safe_edit_or_send(
            q,
            "✅ *No duplicate MCQs found!*",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]
            ])
        )
        return

    text = "🔁 *Duplicate MCQs Detected*\n\n"

    for i, r in enumerate(rows, 1):
        exam, topic, question, cnt = r
        short_q = question[:80] + ("…" if len(question) > 80 else "")
        text += (
            f"*{i}.* `{cnt} times`\n"
            f"📘 {exam} / {topic}\n"
            f"❓ {short_q}\n\n"
        )

    await safe_edit_or_send(
        q,
        text,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]
        ])
    )

#------admin add mcq--------------
async def admin_add_mcq(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id not in ADMIN_IDS:
        return

    ctx.user_data.clear()
    ctx.user_data["admin_add"] = {"step": "exam"}

    await q.message.reply_text(
        "✍️ *Manual MCQ Add*\n\n👉 Step 1/9\n\n*Enter Exam Name:*",
        parse_mode="Markdown"
    )

#-------admin add mcq text---------------------
async def admin_add_mcq_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # ❌ CANCEL MANUAL MCQ ADD
    if update.message.text.lower() == "/cancel":
        ctx.user_data.clear()
        await update.message.reply_text(
            "❌ Manual MCQ add cancelled",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Admin", callback_data="admin_panel")]
            ])
        )
        return

    if update.effective_user.id not in ADMIN_IDS:
        return

    data = ctx.user_data.get("admin_add")
    if not data:
        return  # not in manual add mode

    text = update.message.text.strip()
    step = data["step"]

    if step == "exam":
        data["exam"] = text
        data["step"] = "topic"
        await update.message.reply_text("👉 Step 2/9\n\n*Enter Topic:*", parse_mode="Markdown")

    elif step == "topic":
        data["topic"] = text
        data["step"] = "question"
        await update.message.reply_text("👉 Step 3/9\n\n*Enter Question:*", parse_mode="Markdown")

    elif step == "question":
        data["question"] = text
        data["step"] = "a"
        await update.message.reply_text("👉 Step 4/9\n\n*Option A:*", parse_mode="Markdown")

    elif step == "a":
        data["a"] = text
        data["step"] = "b"
        await update.message.reply_text("👉 Step 5/9\n\n*Option B:*", parse_mode="Markdown")

    elif step == "b":
        data["b"] = text
        data["step"] = "c"
        await update.message.reply_text("👉 Step 6/9\n\n*Option C:*", parse_mode="Markdown")

    elif step == "c":
        data["c"] = text
        data["step"] = "d"
        await update.message.reply_text("👉 Step 7/9\n\n*Option D:*", parse_mode="Markdown")

    elif step == "d":
        data["d"] = text
        data["step"] = "correct"
        await update.message.reply_text(
            "👉 Step 8/9\n\n*Correct Option?*\nSend one letter: A / B / C / D",
            parse_mode="Markdown"
        )
    elif step == "correct":

        ans = text.upper().strip()
        if ans not in ["A", "B", "C", "D"]:
            await update.message.reply_text(
                "❌ Invalid input\nSend only: A / B / C / D"
                )
            return

        data["correct"] = ans
        data["step"] = "explanation"

        await update.message.reply_text(
            "👉 Step 9/9\n\n*Explanation:*",
            parse_mode="Markdown"
        )

    elif step == "explanation":
        data["explanation"] = text

        d = data  # short reference

        preview = f"""
    📘 *Preview MCQ*

    *Exam:* {d['exam']}
    *Topic:* {d['topic']}

    ❓ {d['question']}

    A. {d['a']}
    B. {d['b']}
    C. {d['c']}
    D. {d['d']}

    ✔ Correct: *{d['correct']}*

    📘 Explanation:
    {d['explanation']}
    """

        await update.message.reply_text(
            preview,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Save MCQ", callback_data="admin_confirm_save")],
                [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel_save")]
            ])
        )

    """elif step == "correct":
        if text.upper() not in ["A", "B", "C", "D"]:
            await update.message.reply_text("❌ Please send only A / B / C / D")
            return
        data["correct"] = text.upper()
        data["step"] = "explanation"
        await update.message.reply_text("👉 Step 9/9\n\n*Explanation:*", parse_mode="Markdown")
    """
    

#---save and cancel handler-------
async def confirm_save_mcq(update, ctx):
    q = update.callback_query; await q.answer()

    d = ctx.user_data.get("admin_add")
    if not d:
        return

    cur.execute("""
        INSERT INTO mcq (exam, topic, question, a, b, c, d, correct, explanation)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        d["exam"], d["topic"], d["question"],
        d["a"], d["b"], d["c"], d["d"],
        d["correct"], d["explanation"]
    ))
    conn.commit()

    ctx.user_data.clear()

    await q.message.reply_text(
        "✅ MCQ Saved Successfully",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Another MCQ", callback_data="admin_add_mcq")],
            [InlineKeyboardButton("⬅️ Back to Admin", callback_data="admin_panel")]
        ])
    )
#------cancel handler--------
async def cancel_save_mcq(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data.clear()

    await q.message.reply_text(
        "❌ MCQ not saved",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Admin", callback_data="admin_panel")]
        ])
    )

#----------------save manual mcq-------------
async def save_manual_mcq(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = ctx.user_data["admin_add"]
        # 🚨 DUPLICATE CHECK
    if is_duplicate_mcq(
        d["exam"], d["topic"], d["question"]
    ):
        
        await update.message.reply_text(
        "⚠️ *Duplicate MCQ Detected!*\n\n"
        "Same question already exists.\n\n"
        "अगर फिर भी add करना है तो /force_add भेजें",
        parse_mode="Markdown"
        )
        ctx.user_data["force_mcq"] = d
        ctx.user_data.pop("admin_add", None)
        return


    cur.execute("""
        INSERT INTO mcq (exam, topic, question, a, b, c, d, correct, explanation)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        d["exam"], d["topic"], d["question"],
        d["a"], d["b"], d["c"], d["d"],
        d["correct"], d["explanation"]
    ))
    conn.commit()

    ctx.user_data.clear()

    await update.message.reply_text(
        "✅ *MCQ Added Successfully!*\n\nYou can add another or go back.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✍️ Add Another MCQ", callback_data="admin_add_mcq")],
            [InlineKeyboardButton("⬅️ Back to Admin", callback_data="admin_panel")]
        ])
    )
#-----------------admin toggle button--------
async def admin_toggle_test(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id not in ADMIN_IDS:
        return

    cur.execute("""
        SELECT exam, topic, is_active
        FROM mcq
        GROUP BY exam, topic
        ORDER BY exam
    """)
    rows = cur.fetchall()

    kb = []
    for exam, topic, active in rows:
        status = "🟢 ON" if active else "🔴 OFF"
        cb = f"toggle::{exam}::{topic}"
        kb.append([InlineKeyboardButton(f"{exam} | {topic} — {status}", callback_data=cb)])

    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")])

    await q.message.reply_text(
        "🚫 *Enable / Disable Tests*\n\nTap to toggle 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

#----------admin toggle button action-------------
async def admin_toggle_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id not in ADMIN_IDS:
        return

    _, exam, topic = q.data.split("::")

    cur.execute(
        "SELECT is_active FROM mcq WHERE exam=? AND topic=? LIMIT 1",
        (exam, topic)
    )
    current = cur.fetchone()[0]

    new_state = 0 if current == 1 else 1

    cur.execute(
        "UPDATE mcq SET is_active=? WHERE exam=? AND topic=?",
        (new_state, exam, topic)
    )
    conn.commit()

    status = "Enabled 🟢" if new_state else "Disabled 🔴"

    await q.message.reply_text(
        f"✅ *{exam} / {topic}* is now *{status}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_toggle_test")]
        ])
    )
#------broadcast start handler----------
async def admin_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id not in ADMIN_IDS:
        return

    ctx.user_data.clear()
    ctx.user_data["admin_mode"] = "broadcast"

    await q.message.reply_text(
        "📢 *Broadcast Mode*\n\n"
        "अब जो message आप भेजेंगे,\n"
        "वह सभी users को जाएगा 👇\n\n"
        "_Cancel करने के लिए /cancel भेजें_",
        parse_mode="Markdown"
    )
#----------Restore Start--------
async def admin_restore(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id not in ADMIN_IDS:
        return

    ctx.user_data.clear()
    ctx.user_data["admin_mode"] = "restore_db"

    await q.message.reply_text(
        "♻️ *Restore Database*\n\n"
        "अब `.db` backup file upload करें ⚠️\n\n"
        "❗ Existing data overwrite हो जाएगा",
        parse_mode="Markdown"
    )
#------upload db file------------
async def admin_restore_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    if ctx.user_data.get("admin_mode") != "restore_db":
        return

    doc = update.message.document
    if not doc.file_name.endswith(".db"):
        await update.message.reply_text("❌ Please upload a valid .db file")
        return

    file = await doc.get_file()

    fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    await file.download_to_drive(temp_path)

    try:
        conn.close()
    except:
        pass

    backup = f"mcq_backup_before_restore_{datetime.date.today()}.db"

    if os.path.exists("mcq.db"):
        os.replace("mcq.db", backup)

    os.replace(temp_path, "mcq.db")

    await update.message.reply_text(
        "✅ *Database Restored Successfully*\n\n"
        "🔁 Bot restart करना जरूरी है",
        parse_mode="Markdown"
    )

    os._exit(0)

#------------backup handler----------
async def admin_backup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id not in ADMIN_IDS:
        return

    db_path = "mcq.db"
    backup_name = f"mcq_backup_{datetime.date.today()}.db"

    await ctx.bot.send_document(
        chat_id=q.from_user.id,
        document=open(db_path, "rb"),
        filename=backup_name,
        caption="💾 *Database Backup*\nKeep this file safe!",
        parse_mode="Markdown"
    )

#--------noop handler--------------
async def noop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("No exams available yet")


# ================= MAIN =================
def main():
    
    app=ApplicationBuilder().token(TOKEN).build()
    # ---- BASIC ----
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(noop, "^noop$"))

    #-----------------main excel handle---------
    
    app.add_handler(CallbackQueryHandler(admin_backup, "^admin_backup$"))
    app.add_handler(CallbackQueryHandler(admin_restore, "^admin_restore$"))
    
    # ✅ Excel upload FIRST
    app.add_handler(MessageHandler(filters.Document.ALL & filters.User(ADMIN_IDS), handle_excel))

    # ✅ Restore DB AFTER
    app.add_handler(MessageHandler(filters.Document.ALL & filters.User(ADMIN_IDS), admin_restore_handler))

    #app.add_handler(MessageHandler(filters.Document.ALL & filters.User(ADMIN_IDS), admin_restore_handler))

    #app.add_handler(MessageHandler(filters.Document.ALL & filters.User(ADMIN_IDS), handle_excel))

    #--------admin panel call back----------
    app.add_handler(CallbackQueryHandler(admin_export, "^admin_export$"))
    app.add_handler(CallbackQueryHandler(admin_upload, "^admin_upload$"))
    app.add_handler(CallbackQueryHandler(admin_search, "^admin_search$"))
    app.add_handler(CallbackQueryHandler(admin_mcq_menu, "^admin_mcq_"))
    app.add_handler(CallbackQueryHandler(admin_edit_field, "^edit_"))
    app.add_handler(CallbackQueryHandler(admin_add_mcq, "^admin_add_mcq$"))
    app.add_handler(CommandHandler("force_add", force_add))

    app.add_handler(CallbackQueryHandler(confirm_save_mcq, "^admin_confirm_save$"))
    app.add_handler(CallbackQueryHandler(cancel_save_mcq, "^admin_cancel_save$"))



    app.add_handler(CallbackQueryHandler(admin_users, "^admin_users$"))
    app.add_handler(CallbackQueryHandler(admin_user_history, "^admin_user_"))
    app.add_handler(CallbackQueryHandler(admin_duplicates, "^admin_duplicates$"))

    app.add_handler(CallbackQueryHandler(admin_toggle_test, "^admin_toggle_test$"))
    app.add_handler(CallbackQueryHandler(admin_toggle_action, "^toggle::"))
    app.add_handler(CallbackQueryHandler(admin_set_correct, "^set_correct_"))

    app.add_handler(CallbackQueryHandler(admin_broadcast, "^admin_broadcast$"))
    app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_IDS), admin_text_router))


# ---- TOP LEVEL BUTTONS (FIRST) ----
    app.add_handler(CallbackQueryHandler(admin_panel, "^admin_panel$"))
    app.add_handler(CallbackQueryHandler(donate, "^donate$"))
    app.add_handler(CallbackQueryHandler(copy_upi, "^copy_upi$"))

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

    
    print("🤖 Bot Running...")
    app.run_polling()

if __name__=="__main__":
    main()









