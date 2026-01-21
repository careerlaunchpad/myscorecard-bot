# =========================================================
# FINAL STABLE MCQ BOT — PRODUCTION READY
# Admin Edit/Delete UI + All User Features
# =========================================================

import os, sqlite3, datetime, unicodedata, pandas as pd, tempfile
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

# ---- SAFE MIGRATION FOR USERNAME ----
cur.execute("PRAGMA table_info(scores)")
cols = [c[1] for c in cur.fetchall()]
if "username" not in cols:
    cur.execute("ALTER TABLE scores ADD COLUMN username TEXT")
    conn.commit()

# total users
cur.execute("SELECT COUNT(DISTINCT user_id) FROM scores")
total_users = cur.fetchone()[0]

# active users (last 7 days)
cur.execute("""
    SELECT COUNT(DISTINCT user_id)
    FROM scores
    WHERE test_date >= date('now','-7 day')
""")
active_users = cur.fetchone()[0]

# most attempted exam
cur.execute("""
    SELECT exam, COUNT(*) as c
    FROM scores
    GROUP BY exam
    ORDER BY c DESC
    LIMIT 1
""")
row = cur.fetchone()
popular_exam = row[0] if row else "N/A"

# ================= HELPERS =================
def is_admin(uid): return uid in ADMIN_IDS
def safe_hindi(t): return unicodedata.normalize("NFKC", str(t)) if t else ""

async def safe_edit_or_send(q, text, kb=None):
    try:
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    except BadRequest:
        try:
            await q.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
        except:
            pass

# ================= UI =================
def home_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="start_new")],
        [InlineKeyboardButton("📊 My Score", callback_data="myscore")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")]
    ])
#------------exam start point--------
def exam_kb():
    cur.execute("SELECT DISTINCT exam FROM mcq")
    exams = [r[0] for r in cur.fetchall()]

    kb = []

    # 💖 DONATE BUTTON (TOP)
    kb.append([
        InlineKeyboardButton(
            "💖 Donate (UPI)",
            callback_data="donate"
        )
    ])

    # 📚 Exams
    for e in exams:
        kb.append([InlineKeyboardButton(e, callback_data=f"exam_{e}")])

    # 🛠 Admin
    kb.append([InlineKeyboardButton("🛠 Admin", callback_data="admin_panel")])

    return InlineKeyboardMarkup(kb)


def topic_kb(exam):
    cur.execute("SELECT DISTINCT topic FROM mcq WHERE exam=?",(exam,))
    t=[r[0] for r in cur.fetchall()]
    kb=[[InlineKeyboardButton(x,callback_data=f"topic_{x}")] for x in t]
    kb.append([InlineKeyboardButton("⬅️ Back",callback_data="start_new")])
    return InlineKeyboardMarkup(kb)

# ================= START =================
async def start(update,ctx):
    ctx.user_data.clear()
    await update.message.reply_text(
        "👋 *Select Exam*",
        parse_mode="Markdown",
        reply_markup=exam_kb()
    )

async def start_new(update,ctx):
    q=update.callback_query; await q.answer()
    ctx.user_data.clear()
    await safe_edit_or_send(q,"👋 *Select Exam*",exam_kb())

# ================= EXAM / TOPIC =================
async def exam_select(update,ctx):
    q=update.callback_query; await q.answer()
    ctx.user_data.clear()
    ctx.user_data["exam"]=q.data.replace("exam_","")
    await safe_edit_or_send(q,"Choose Topic 👇",topic_kb(ctx.user_data["exam"]))

async def topic_select(update,ctx):
    q=update.callback_query; await q.answer()
    exam=ctx.user_data["exam"]
    topic=q.data.replace("topic_","")

    cur.execute("SELECT COUNT(*) FROM mcq WHERE exam=? AND topic=?",(exam,topic))
    total=cur.fetchone()[0]

    ctx.user_data.update({
        "topic":topic,"score":0,"q_no":0,
        "limit":total,"asked":[],
        "wrong":[], "attempts":[]
    })
    await send_mcq(q,ctx)

# ================= MCQ FLOW =================
async def send_mcq(q,ctx):
    exam,topic=ctx.user_data["exam"],ctx.user_data["topic"]
    asked=ctx.user_data["asked"]

    if asked:
        ph=",".join("?"*len(asked))
        cur.execute(
            f"SELECT * FROM mcq WHERE exam=? AND topic=? AND id NOT IN ({ph}) ORDER BY RANDOM() LIMIT 1",
            [exam,topic]+asked
        )
    else:
        cur.execute(
            "SELECT * FROM mcq WHERE exam=? AND topic=? ORDER BY RANDOM() LIMIT 1",
            (exam,topic)
        )

    m=cur.fetchone()
    if not m:
        await show_result(q,ctx); return

    ctx.user_data["current"]=m
    ctx.user_data["asked"].append(m[0])

    await safe_edit_or_send(
        q,
        f"❓ *Q{ctx.user_data['q_no']+1}/{ctx.user_data['limit']}*\n\n{m[3]}\n\n"
        f"A. {m[4]}\nB. {m[5]}\nC. {m[6]}\nD. {m[7]}",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("A",callback_data="ans_A"),
             InlineKeyboardButton("B",callback_data="ans_B")],
            [InlineKeyboardButton("C",callback_data="ans_C"),
             InlineKeyboardButton("D",callback_data="ans_D")]
        ])
    )

async def answer(update, ctx):
    q = update.callback_query
    await q.answer()

    # 🔐 SAFETY CHECK (VERY IMPORTANT)
    if "current" not in ctx.user_data:
        await safe_edit_or_send(
            q,
            "⚠️ This question is no longer active.\nPlease start a new test.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
            ])
        )
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
    await send_mcq(q, ctx)

# ================= RESULT =================
async def show_result(q,ctx):
    user = q.from_user
username = (
    f"@{user.username}"
    if user.username
    else f"{user.first_name or ''} {user.last_name or ''}".strip()
    or f"User_{user.id}"
)

cur.execute(
    """
    INSERT INTO scores
    (user_id, exam, topic, score, total, test_date, username)
    VALUES (?,?,?,?,?,?,?)
    """,
    (
        user.id,
        ctx.user_data["exam"],
        ctx.user_data["topic"],
        ctx.user_data["score"],
        ctx.user_data["q_no"],
        datetime.date.today().isoformat(),
        username
    )
)
conn.commit()


    await safe_edit_or_send(
        q,
        f"🎯 *Completed*\nScore: *{ctx.user_data['score']}/{ctx.user_data['q_no']}*",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Review All",callback_data="review_all")],
            [InlineKeyboardButton("❌ Wrong Only",callback_data="wrong_only")],
            [InlineKeyboardButton("🏆 Leaderboard",callback_data="leaderboard")],
            [InlineKeyboardButton("📄 Download PDF", callback_data="pdf_result")],
            [InlineKeyboardButton("🏠 Home",callback_data="start_new")]
        ])
    )

# ================= REVIEW =================
async def review_all(update,ctx):
    q=update.callback_query; await q.answer()
    txt="📋 *Review*\n\n"
    for i,a in enumerate(ctx.user_data["attempts"],1):
        txt+=f"*Q{i}.* {a['question']}\nYour: {a['chosen']}\nCorrect: {a['correct']}\n📘 {a['explanation']}\n\n"
    await safe_edit_or_send(q,txt,home_kb())

# ================= WRONG =================
"""async def wrong_only(update,ctx):
    q=update.callback_query; await q.answer()
    if not ctx.user_data["wrong"]:
        await safe_edit_or_send(q,"🎉 No wrong questions",home_kb()); return
    m=ctx.user_data["wrong"][0]
    correct=m[4 if m[8]=="A" else 5 if m[8]=="B" else 6 if m[8]=="C" else 7]
    await safe_edit_or_send(q,f"{m[3]}\n\n✅ {correct}\n📘 {m[9]}",home_kb())"""
async def wrong_only(update, ctx):
    q = update.callback_query
    await q.answer()

    if not ctx.user_data.get("wrong"):
        await safe_edit_or_send(q, "🎉 No wrong questions", home_kb())
        return

    ctx.user_data["wrong_index"] = 0
    await show_wrong_question(q, ctx)

#--------show wrong question----------------
async def show_wrong_question(q, ctx):
    idx = ctx.user_data["wrong_index"]
    wrong_list = ctx.user_data["wrong"]

    if idx < 0 or idx >= len(wrong_list):
        return

    m = wrong_list[idx]
    correct = m[4 if m[8]=="A" else 5 if m[8]=="B" else 6 if m[8]=="C" else 7]

    text = (
        f"❌ *Wrong Question {idx+1}/{len(wrong_list)}*\n\n"
        f"{m[3]}\n\n"
        f"✅ *Correct Answer:* {correct}\n"
        f"📘 {m[9]}"
    )

    kb = []

    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="wrong_prev"))
    if idx < len(wrong_list) - 1:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="wrong_next"))

    if nav:
        kb.append(nav)

    kb.append([InlineKeyboardButton("🏠 Home", callback_data="start_new")])

    await safe_edit_or_send(q, text, InlineKeyboardMarkup(kb))

#--------Next / Prev handlers-----
async def wrong_next(update, ctx):
    q = update.callback_query
    await q.answer()
    ctx.user_data["wrong_index"] += 1
    await show_wrong_question(q, ctx)

async def wrong_prev(update, ctx):
    q = update.callback_query
    await q.answer()
    ctx.user_data["wrong_index"] -= 1
    await show_wrong_question(q, ctx)


# ================= LEADERBOARD =================
async def leaderboard(update,ctx):
    q=update.callback_query; await q.answer()
    e,t=ctx.user_data.get("exam"),ctx.user_data.get("topic")
    cur.execute("""
    SELECT username, MAX(score)
    FROM scores
    WHERE exam=? AND topic=?
    GROUP BY user_id
    ORDER BY MAX(score) DESC
    LIMIT 10""",(e,t))

    rows=cur.fetchall()
    #txt=f"🏆 *{e}/{t}*\n\n"
    name = r[0] or "Unknown User" #new update code
    txt += f"{i}. *{name}* → {r[1]}\n"

    for i,r in enumerate(rows,1):
        txt+=f"{i}. `{r[0]}` → {r[1]}\n"
    await safe_edit_or_send(q,txt,home_kb())
# ================= MY SCORE =================
async def myscore(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    display_name = (
    f"@{user.username}"
    if user.username
    else f"{user.first_name or ''} {user.last_name or ''}".strip()
    or f"User_{user.id}"
    )

    msg = update.effective_message   # 🔥 FIX
    uid = update.effective_user.id

    cur.execute("""
        SELECT exam, topic, score, total, test_date
        FROM scores
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 5
    """, (uid,))
    rows = cur.fetchall()

    if not rows:
        await msg.reply_text(
            "📊 *No test history yet*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="start_new")]
            ])
        )
        return
        
    text = f"👤 *Profile: {display_name}*\n\n" #update
    text = "📊 *Your Recent Tests*\n\n"
    
    for r in rows:
        text += f"{r[0]} / {r[1]} → *{r[2]}/{r[3]}* ({r[4]})\n"

    await msg.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="start_new")]
        ])
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

    if "attempts" not in ctx.user_data:
        await safe_edit_or_send(q, "⚠️ No test data available", home_kb())
        return

    file_path = f"MyScore_{q.from_user.id}.pdf"
    doc = SimpleDocTemplate(file_path, pagesize=A4)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H", fontName="Hindi", fontSize=11))

    story = [
        Paragraph("MyScoreCard – टेस्ट परिणाम", styles["H"]),
        Spacer(1, 10)
    ]

    for i, a in enumerate(ctx.user_data["attempts"], 1):
        story.extend([
            Paragraph(f"प्रश्न {i}: {safe_hindi(a['question'])}", styles["H"]),
            Paragraph(f"आपका उत्तर: {safe_hindi(a['chosen'])}", styles["H"]),
            Paragraph(f"सही उत्तर: {safe_hindi(a['correct'])}", styles["H"]),
            Paragraph(f"व्याख्या: {safe_hindi(a['explanation'])}", styles["H"]),
            Spacer(1, 8)
        ])

    doc.build(story)

    await ctx.bot.send_document(
        chat_id=q.from_user.id,
        document=open(file_path, "rb")
    )

    await ctx.bot.send_message(
        chat_id=q.from_user.id,
        text="📄 PDF Generated Successfully",
        reply_markup=home_kb()
    )
# ================= ADMIN PANEL =================
async def admin_panel(update,ctx):
    q=update.callback_query; await q.answer()
    if not is_admin(q.from_user.id): return
    ctx.user_data.clear()
    await safe_edit_or_send(
        q,f"""
        🛠 *Admin Dashboard*
        
        👥 Total Users: *{total_users}*
        🔥 Active Users (7d): *{active_users}*
        🏆 Most Popular Exam: *{popular_exam}*
        """,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 User Analytics", callback_data="admin_stats")],
            
            [InlineKeyboardButton("🔍 Search MCQ",callback_data="admin_search")],
            [InlineKeyboardButton("📤 Upload Excel",callback_data="admin_upload")],
            [InlineKeyboardButton("🧾 Export DB",callback_data="admin_export")],
            [InlineKeyboardButton("⬅️ Back",callback_data="start_new")]
        ])
    )

# ================= ADMIN SEARCH =================
async def admin_search(update,ctx):
    q=update.callback_query; await q.answer()
    ctx.user_data.clear()
    ctx.user_data["admin_mode"]="search"
    await q.message.reply_text("🔍 Send keyword to search MCQ")

async def admin_text_router(update,ctx):
    if not is_admin(update.effective_user.id): return
    if ctx.user_data.get("admin_mode")=="search":
        kw=update.message.text
        cur.execute(
            "SELECT id,question FROM mcq WHERE question LIKE ? LIMIT 20",
            (f"%{kw}%",)
        )
        rows=cur.fetchall()
        if not rows:
            await update.message.reply_text("❌ No MCQ found"); return

        kb=[[InlineKeyboardButton(r[1][:40]+"…",callback_data=f"admin_mcq_{r[0]}")] for r in rows]
        kb.append([InlineKeyboardButton("⬅️ Back",callback_data="admin_panel")])
        await update.message.reply_text("📋 Select MCQ",reply_markup=InlineKeyboardMarkup(kb))
        
async def admin_do_search(update, ctx):
    kw = update.message.text.strip()
    cur.execute(
        "SELECT id, question FROM mcq WHERE question LIKE ? LIMIT 20",
        (f"%{kw}%",)
    )
    rows = cur.fetchall()

    if not rows:
        await update.message.reply_text("❌ No MCQ found")
        return

    kb = [
        [InlineKeyboardButton(r[1][:40]+"…", callback_data=f"admin_mcq_{r[0]}")]
        for r in rows
    ]
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")])

    await update.message.reply_text(
        "📋 Select MCQ to Edit",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ================= ADMIN EDIT =================
async def admin_mcq_menu(update,ctx):
    q=update.callback_query; await q.answer()
    mcq_id=int(q.data.split("_")[-1])
    ctx.user_data["edit_id"]=mcq_id

    cur.execute("SELECT * FROM mcq WHERE id=?",(mcq_id,))
    m=cur.fetchone()

    txt=f"*Edit MCQ*\n\nQ: {m[3]}\nA:{m[4]}\nB:{m[5]}\nC:{m[6]}\nD:{m[7]}\n✔ {m[8]}"

    await safe_edit_or_send(
        q,txt,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("✏ Question",callback_data="edit_question")],
            [InlineKeyboardButton("🅰 A",callback_data="edit_a"),
             InlineKeyboardButton("🅱 B",callback_data="edit_b")],
            [InlineKeyboardButton("🅲 C",callback_data="edit_c"),
             InlineKeyboardButton("🅳 D",callback_data="edit_d")],
            [InlineKeyboardButton("✔ Correct",callback_data="edit_correct")],
            [InlineKeyboardButton("🗑 Delete",callback_data="delete_mcq")],
            [InlineKeyboardButton("⬅️ Back",callback_data="admin_panel")]
        ])
    )

async def admin_edit_field(update,ctx):
    q=update.callback_query; await q.answer()
    ctx.user_data["admin_mode"]="edit_field"
    ctx.user_data["field"]=q.data.replace("edit_","")
    await q.message.reply_text("✏️ Send new value")
    
    if ctx.user_data["field"] == "correct": #update
        await q.message.reply_text("Select correct option",
            reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("A", callback_data="set_correct_A"),
             InlineKeyboardButton("B", callback_data="set_correct_B")],
            [InlineKeyboardButton("C", callback_data="set_correct_C"),
             InlineKeyboardButton("D", callback_data="set_correct_D")]
        ])
    )
    return


async def admin_save_edit(update,ctx):
    if ctx.user_data.get("admin_mode")!="edit_field": return
    field=ctx.user_data["field"]
    mcq_id=ctx.user_data["edit_id"]
    col={"question":"question","a":"a","b":"b","c":"c","d":"d","correct":"correct"}[field]
    cur.execute(f"UPDATE mcq SET {col}=? WHERE id=?",(update.message.text,mcq_id))
    conn.commit()
    ctx.user_data.clear()
    await update.message.reply_text("✅ Updated")

#-----admin delete mcq-------------
async def admin_delete_mcq(update, ctx):
    q = update.callback_query
    await q.answer()

    mcq_id = ctx.user_data["edit_id"]
    cur.execute("SELECT * FROM mcq WHERE id=?", (mcq_id,))
    ctx.user_data["undo"] = cur.fetchone()

    cur.execute("DELETE FROM mcq WHERE id=?", (mcq_id,))
    conn.commit()

    ctx.user_data["admin_mode"] = "undo_available"

    await q.message.reply_text(
        "🗑 MCQ Deleted",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("↩ Undo", callback_data="undo_delete")],
            [InlineKeyboardButton("🏠 Home", callback_data="start_new")]
        ])
    )
#------------------admin undo----------
async def admin_undo(update, ctx):
    q = update.callback_query
    await q.answer()

    m = ctx.user_data.get("undo")
    if not m:
        return

    cur.execute(
        "INSERT INTO mcq VALUES(NULL,?,?,?,?,?,?,?,?,?)",
        m[1:]
    )
    conn.commit()

    await q.message.reply_text("♻️ Undo successful")

#---------admin set correct-------------------------
async def admin_set_correct(update, ctx):
    q = update.callback_query
    await q.answer()
    mcq_id = ctx.user_data["edit_id"]
    correct = q.data[-1]
    cur.execute("UPDATE mcq SET correct=? WHERE id=?", (correct, mcq_id))
    conn.commit()
    ctx.user_data.clear()
    await q.message.reply_text("✅ Correct option updated")

#------------admin upload------------------------
async def admin_upload(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data["awaiting_excel"] = True
    await q.message.reply_text(
        "📤 Upload Excel (.xlsx)\n\n"
        "Columns:\nexam, topic, question, a, b, c, d, correct, explanation"
    )

async def handle_excel(update: Update, ctx):
    if not is_admin(update.effective_user.id): return
    if not ctx.user_data.get("awaiting_excel"): return

    ctx.user_data["awaiting_excel"] = False
    file = await update.message.document.get_file()
    path = tempfile.mktemp(".xlsx")
    await file.download_to_drive(path)

    df = pd.read_excel(path)
    for _, r in df.iterrows():
        cur.execute(
            "INSERT INTO mcq VALUES(NULL,?,?,?,?,?,?,?,?,?)",
            (r.exam,r.topic,r.question,r.a,r.b,r.c,r.d,r.correct,r.explanation)
        )
    conn.commit()

    await update.message.reply_text(
        f"✅ {len(df)} MCQs uploaded successfully",
        reply_markup=home_kb()
    )

async def admin_export(update, ctx):
    q = update.callback_query; await q.answer()
    df = pd.read_sql("SELECT * FROM mcq", conn)
    path = tempfile.mktemp(".xlsx")
    df.to_excel(path, index=False)
    await ctx.bot.send_document(q.from_user.id, open(path,"rb"))

#------------admin status---------------
async def admin_stats(update, ctx):
    q = update.callback_query
    await q.answer()

    # 1️⃣ Total unique users
    cur.execute("SELECT COUNT(DISTINCT user_id) FROM scores")
    total_users = cur.fetchone()[0] or 0

    # 2️⃣ Active users today
    today = datetime.date.today().isoformat()
    cur.execute(
        "SELECT COUNT(DISTINCT user_id) FROM scores WHERE test_date=?",
        (today,)
    )
    active_today = cur.fetchone()[0] or 0

    # 3️⃣ Total tests given
    cur.execute("SELECT COUNT(*) FROM scores")
    total_tests = cur.fetchone()[0] or 0

    # 4️⃣ Most attempted exam/topic
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

    text = (
        "📊 *User Analytics Dashboard*\n\n"
        f"👥 *Total Users:* {total_users}\n"
        f"🔥 *Active Today:* {active_today}\n"
        f"📝 *Total Tests Given:* {total_tests}\n\n"
        f"🏆 *Most Popular Test:*\n{popular_test}"
    )

    await safe_edit_or_send(
        q,
        text,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]
        ])
    )

#------Donate--------------
async def donate(update, ctx):
    q = update.callback_query
    await q.answer()

    text = (
        "🙏 *Support This Free MCQ Bot*\n\n"
        "यह bot सभी के लिए *FREE* है ❤️\n"
        "अगर आप support करना चाहें तो नीचे दी गई UPI ID पर donate कर सकते हैं 👇\n\n"
        f"`{UPI_ID}`\n\n"
        "📌 *UPI ID को long-press करके copy करें*"
    )

    await safe_edit_or_send(
        q,
        text,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="start_new")]
        ])
    )


# ================= MAIN =================
def main():
    app=ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",start))
    app.add_handler(CallbackQueryHandler(donate, "^donate$"))

    app.add_handler(CommandHandler("myscore",myscore))
    app.add_handler(CallbackQueryHandler(myscore, "^myscore$"))

    app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_IDS),admin_text_router))
    app.add_handler(MessageHandler(filters.Document.ALL & filters.User(ADMIN_IDS), handle_excel))
    app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_IDS),admin_save_edit))

    app.add_handler(CallbackQueryHandler(start_new,"^start_new$"))
    app.add_handler(CallbackQueryHandler(exam_select,"^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select,"^topic_"))
    app.add_handler(CallbackQueryHandler(answer,"^ans_"))
    app.add_handler(CallbackQueryHandler(review_all,"^review_all$"))
    
    app.add_handler(CallbackQueryHandler(wrong_only, "^wrong_only$"))
    app.add_handler(CallbackQueryHandler(wrong_next, "^wrong_next$"))
    app.add_handler(CallbackQueryHandler(wrong_prev, "^wrong_prev$"))

    app.add_handler(CallbackQueryHandler(leaderboard,"^leaderboard$"))
    app.add_handler(CallbackQueryHandler(pdf_result, "^pdf_result$"))

    app.add_handler(CallbackQueryHandler(admin_upload, "^admin_upload$"))
    app.add_handler(CallbackQueryHandler(admin_export, "^admin_export$"))

  
    app.add_handler(CallbackQueryHandler(admin_stats, "^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_panel,"^admin_panel$"))
    app.add_handler(CallbackQueryHandler(admin_search,"^admin_search$"))
    app.add_handler(CallbackQueryHandler(admin_mcq_menu,"^admin_mcq_"))
    
    app.add_handler(CallbackQueryHandler(admin_delete_mcq, "^delete_mcq$"))
    app.add_handler(CallbackQueryHandler(admin_undo, "^undo_delete$"))
    app.add_handler(CallbackQueryHandler(admin_edit_field,"^edit_"))
    app.add_handler(CallbackQueryHandler(admin_set_correct, "^set_correct_"))


    print("🤖 Bot Running...")
    app.run_polling()

if __name__=="__main__":
    main()



















