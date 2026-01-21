# =========================================================
# STEP 2 — MCQ ENGINE + REVIEW / WRONG ANALYSIS (STABLE)
# =========================================================

import os, sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes
)
from telegram.error import BadRequest

TOKEN = os.getenv("BOT_TOKEN")

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
conn.commit()

# ================= SAFE EDIT =================
async def safe_edit(q, text, kb=None):
    try:
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    except BadRequest:
        await q.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

# ================= KEYBOARDS =================
def exam_kb():
    cur.execute("SELECT DISTINCT exam FROM mcq")
    exams = [r[0] for r in cur.fetchall()]
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(e, callback_data=f"exam_{e}")] for e in exams]
    )

def topic_kb(exam):
    cur.execute("SELECT DISTINCT topic FROM mcq WHERE exam=?", (exam,))
    topics = [r[0] for r in cur.fetchall()]
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t, callback_data=f"topic_{t}")] for t in topics] +
        [[InlineKeyboardButton("🏠 Home", callback_data="start")]]
    )

def answer_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("A", callback_data="ans_A"),
            InlineKeyboardButton("B", callback_data="ans_B")
        ],
        [
            InlineKeyboardButton("C", callback_data="ans_C"),
            InlineKeyboardButton("D", callback_data="ans_D")
        ]
    ])

# ================= START =================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "👋 *Select Exam*",
        parse_mode="Markdown",
        reply_markup=exam_kb()
    )

# ================= EXAM =================
async def exam_select(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data.clear()
    ctx.user_data["exam"] = q.data.replace("exam_", "")
    await safe_edit(q, "*Select Topic*", topic_kb(ctx.user_data["exam"]))

# ================= TOPIC =================
async def topic_select(update, ctx):
    q = update.callback_query; await q.answer()

    exam = ctx.user_data["exam"]
    topic = q.data.replace("topic_", "")

    cur.execute("SELECT COUNT(*) FROM mcq WHERE exam=? AND topic=?", (exam, topic))
    total = cur.fetchone()[0]

    ctx.user_data.update({
        "topic": topic,
        "asked": [],
        "score": 0,
        "q_no": 0,
        "total": total,
        "attempts": [],
        "wrong": []
    })

    await send_mcq(q, ctx)

# ================= SEND MCQ =================
async def send_mcq(q, ctx):
    exam, topic = ctx.user_data["exam"], ctx.user_data["topic"]
    asked = ctx.user_data["asked"]

    if asked:
        ph = ",".join("?" * len(asked))
        cur.execute(
            f"""
            SELECT * FROM mcq
            WHERE exam=? AND topic=? AND id NOT IN ({ph})
            ORDER BY RANDOM() LIMIT 1
            """,
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

    text = (
        f"❓ *Q{ctx.user_data['q_no']+1}/{ctx.user_data['total']}*\n\n"
        f"{m[3]}\n\n"
        f"A. {m[4]}\nB. {m[5]}\nC. {m[6]}\nD. {m[7]}"
    )

    await safe_edit(q, text, answer_kb())

# ================= ANSWER =================
async def answer(update, ctx):
    q = update.callback_query; await q.answer()

    if "current" not in ctx.user_data:
        await safe_edit(q, "⚠️ Session expired", InlineKeyboardMarkup(
            [[InlineKeyboardButton("🏠 Home", callback_data="start")]]
        ))
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
        ctx.user_data["wrong"].append(ctx.user_data["attempts"][-1])

    ctx.user_data["q_no"] += 1
    await send_mcq(q, ctx)

# ================= RESULT =================
async def show_result(q, ctx):
    await safe_edit(
        q,
        f"🎯 *Test Completed*\n\nScore: *{ctx.user_data['score']}/{ctx.user_data['q_no']}*",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Review All", callback_data="review_all")],
            [InlineKeyboardButton("❌ Wrong Only", callback_data="wrong_only")],
            [InlineKeyboardButton("🏠 Home", callback_data="start")]
        ])
    )

# ================= REVIEW ALL =================
async def review_all(update, ctx):
    q = update.callback_query; await q.answer()
    text = "📋 *Review All Questions*\n\n"
    for i,a in enumerate(ctx.user_data["attempts"],1):
        text += (
            f"*Q{i}.* {a['question']}\n"
            f"Your: {a['chosen']}\n"
            f"Correct: {a['correct']}\n"
            f"📘 {a['explanation']}\n\n"
        )
    await safe_edit(q, text, InlineKeyboardMarkup(
        [[InlineKeyboardButton("🏠 Home", callback_data="start")]]
    ))

# ================= WRONG ONLY =================
async def wrong_only(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data["wrong_index"] = 0
    await show_wrong(q, ctx)

async def show_wrong(q, ctx):
    idx = ctx.user_data["wrong_index"]
    wrong = ctx.user_data["wrong"]

    if not wrong:
        await safe_edit(q, "🎉 No wrong questions", InlineKeyboardMarkup(
            [[InlineKeyboardButton("🏠 Home", callback_data="start")]]
        ))
        return

    a = wrong[idx]
    text = (
        f"❌ *Wrong {idx+1}/{len(wrong)}*\n\n"
        f"{a['question']}\n\n"
        f"✅ Correct: {a['correct']}\n"
        f"📘 {a['explanation']}"
    )

    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="w_prev"))
    if idx < len(wrong)-1:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="w_next"))

    kb = []
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("🏠 Home", callback_data="start")])

    await safe_edit(q, text, InlineKeyboardMarkup(kb))

async def w_next(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data["wrong_index"] += 1
    await show_wrong(q, ctx)

async def w_prev(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data["wrong_index"] -= 1
    await show_wrong(q, ctx)

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(start, "^start$"))
    app.add_handler(CallbackQueryHandler(exam_select, "^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select, "^topic_"))
    app.add_handler(CallbackQueryHandler(answer, "^ans_"))

    app.add_handler(CallbackQueryHandler(review_all, "^review_all$"))
    app.add_handler(CallbackQueryHandler(wrong_only, "^wrong_only$"))
    app.add_handler(CallbackQueryHandler(w_next, "^w_next$"))
    app.add_handler(CallbackQueryHandler(w_prev, "^w_prev$"))

    print("🤖 STEP 2 BOT RUNNING")
    app.run_polling()

if __name__ == "__main__":
    main()
