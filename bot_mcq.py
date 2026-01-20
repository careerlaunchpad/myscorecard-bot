# ================= FINAL STABLE MCQ BOT =================
# Upload Excel + MyScore FIXED (Admin proof)

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
 user_id INTEGER, exam TEXT, topic TEXT,
 score INTEGER, total INTEGER, test_date TEXT
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
        try:
            await q.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
        except:
            pass

# ================= UI =================
def home_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="start_new")],
        [InlineKeyboardButton("📊 My Score", callback_data="myscore_cb")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
        [InlineKeyboardButton("📄 PDF", callback_data="pdf_result")]
    ])

def exam_kb():
    cur.execute("SELECT DISTINCT exam FROM mcq")
    exams=[r[0] for r in cur.fetchall()]
    kb=[[InlineKeyboardButton(e,callback_data=f"exam_{e}")] for e in exams]
    kb.append([InlineKeyboardButton("🛠 Admin",callback_data="admin_panel")])
    return InlineKeyboardMarkup(kb)

def topic_kb(exam):
    cur.execute("SELECT DISTINCT topic FROM mcq WHERE exam=?",(exam,))
    t=[r[0] for r in cur.fetchall()]
    kb=[[InlineKeyboardButton(x,callback_data=f"topic_{x}")] for x in t]
    kb.append([InlineKeyboardButton("⬅️ Back",callback_data="start_new")])
    return InlineKeyboardMarkup(kb)

# ================= START =================
async def start(update:Update,ctx):
    ctx.user_data.clear()
    await update.message.reply_text(
        "👋 *Select Exam*",parse_mode="Markdown",reply_markup=exam_kb()
    )

async def start_new(update,ctx):
    q=update.callback_query; await q.answer()
    ctx.user_data.clear()
    await safe_edit_or_send(q,"👋 *Select Exam*",exam_kb())

# ================= MCQ FLOW =================
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
             InlineKeyboardButton("D",callback_data="ans_D")],
            [InlineKeyboardButton("🏠 Home",callback_data="start_new")]
        ])
    )

async def answer(update,ctx):
    q=update.callback_query; await q.answer()
    m=ctx.user_data["current"]
    sel=q.data[-1]

    chosen=m[4 if sel=="A" else 5 if sel=="B" else 6 if sel=="C" else 7]
    correct=m[4 if m[8]=="A" else 5 if m[8]=="B" else 6 if m[8]=="C" else 7]

    ctx.user_data["attempts"].append({
        "question":m[3],
        "chosen":chosen,
        "correct":correct,
        "explanation":m[9]
    })

    if sel==m[8]: ctx.user_data["score"]+=1
    else: ctx.user_data["wrong"].append(m)

    ctx.user_data["q_no"]+=1
    await send_mcq(q,ctx)

# ================= RESULT =================
async def show_result(q,ctx):
    cur.execute(
        "INSERT INTO scores VALUES(NULL,?,?,?,?,?,?)",
        (q.from_user.id,ctx.user_data["exam"],
         ctx.user_data["topic"],ctx.user_data["score"],
         ctx.user_data["q_no"],datetime.date.today().isoformat())
    )
    conn.commit()

    await safe_edit_or_send(
        q,
        f"🎯 *Completed*\nScore: *{ctx.user_data['score']}/{ctx.user_data['q_no']}*",
        home_kb()
    )

# ================= MYSCORE (COMMAND + BUTTON) =================
async def myscore(update,ctx):
    uid=update.effective_user.id
    cur.execute(
        "SELECT exam,topic,score,total FROM scores WHERE user_id=? ORDER BY id DESC LIMIT 5",
        (uid,)
    )
    rows=cur.fetchall()

    if not rows:
        txt="📊 *No test history yet*"
    else:
        txt="📊 *My Score*\n\n"
        for r in rows:
            txt+=f"{r[0]}/{r[1]} → {r[2]}/{r[3]}\n"

    if update.message:
        await update.message.reply_text(txt,parse_mode="Markdown",reply_markup=home_kb())
    else:
        await safe_edit_or_send(update.callback_query,txt,home_kb())

# ================= ADMIN EXCEL UPLOAD (AUTO FIXED) =================
async def handle_excel(update:Update,ctx):
    if not is_admin(update.effective_user.id): return

    file=await update.message.document.get_file()
    path=tempfile.mktemp(".xlsx")
    await file.download_to_drive(path)

    df=pd.read_excel(path)
    for _,r in df.iterrows():
        cur.execute(
            "INSERT INTO mcq VALUES(NULL,?,?,?,?,?,?,?,?,?)",
            (r.exam,r.topic,r.question,r.a,r.b,r.c,r.d,r.correct,r.explanation)
        )
    conn.commit()

    await update.message.reply_text(f"✅ {len(df)} MCQs uploaded",reply_markup=home_kb())

# ================= MAIN =================
def main():
    app=ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("myscore",myscore))

    app.add_handler(MessageHandler(filters.Document.ALL & filters.User(ADMIN_IDS),handle_excel))

    app.add_handler(CallbackQueryHandler(start_new,"^start_new$"))
    app.add_handler(CallbackQueryHandler(exam_select,"^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select,"^topic_"))
    app.add_handler(CallbackQueryHandler(answer,"^ans_"))
    app.add_handler(CallbackQueryHandler(myscore,"^myscore_cb$"))

    print("🤖 Bot Running...")
    app.run_polling()

if __name__=="__main__":
    main()
