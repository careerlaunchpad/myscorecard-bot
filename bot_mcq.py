import os
import sqlite3
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

TOKEN = os.getenv("BOT_TOKEN")

# ---------------- DATABASE ----------------
conn = sqlite3.connect("mcq.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS mcq (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam TEXT,
    topic TEXT,
    question TEXT,
    a TEXT,
    b TEXT,
    c TEXT,
    d TEXT,
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

# ---------------- START ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("📘 MPPSC", callback_data="exam_MPPSC")],
        [InlineKeyboardButton("📕 UGC NET", callback_data="exam_NET")]
    ]
    await update.message.reply_text(
        "👋 Welcome to MyScoreCard Bot 🎯\n\nSelect Exam 👇",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ---------------- EXAM ----------------
async def exam_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    context.user_data.clear()
    context.user_data["exam"] = q.data.split("_")[1]

    kb = [
        [InlineKeyboardButton("History", callback_data="topic_History")],
        [InlineKeyboardButton("Polity", callback_data="topic_Polity")]
    ]
    await q.edit_message_text(
        f"📘 Exam: {context.user_data['exam']}\n\nChoose Topic 👇",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ---------------- TOPIC ----------------
async def topic_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    context.user_data["topic"] = q.data.split("_")[1]
    context.user_data["score"] = 0
    context.user_data["q_no"] = 0
    context.user_data["limit"] = 10
    context.user_data["asked"] = []
    context.user_data["attempts"] = []
    context.user_data["wrong_questions"] = []

    await send_mcq(q, context)

# ---------------- SEND MCQ ----------------
async def send_mcq(q, context):
    asked = context.user_data["asked"]

    if asked:
        placeholders = ",".join("?" * len(asked))
        query = f"""
        SELECT * FROM mcq
        WHERE exam=? AND topic=?
        AND id NOT IN ({placeholders})
        ORDER BY RANDOM() LIMIT 1
        """
        params = [context.user_data["exam"], context.user_data["topic"]] + asked
    else:
        query = """
        SELECT * FROM mcq
        WHERE exam=? AND topic=?
        ORDER BY RANDOM() LIMIT 1
        """
        params = [context.user_data["exam"], context.user_data["topic"]]

    cur.execute(query, params)
    mcq = cur.fetchone()

    if not mcq:
        await show_result(q, context)
        return

    context.user_data["asked"].append(mcq[0])
    context.user_data["ans"] = mcq[8]

    context.user_data["last"] = {
        "question": mcq[3],
        "options": {"A": mcq[4], "B": mcq[5], "C": mcq[6], "D": mcq[7]},
        "correct": mcq[8],
        "explanation": mcq[9]
    }

    kb = [
        [InlineKeyboardButton("A", callback_data="ans_A"),
         InlineKeyboardButton("B", callback_data="ans_B")],
        [InlineKeyboardButton("C", callback_data="ans_C"),
         InlineKeyboardButton("D", callback_data="ans_D")]
    ]

    await q.edit_message_text(
        f"❓ Q{context.user_data['q_no']+1}\n{mcq[3]}\n\n"
        f"A. {mcq[4]}\nB. {mcq[5]}\nC. {mcq[6]}\nD. {mcq[7]}",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ---------------- ANSWER ----------------
async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    selected = q.data.split("_")[1]
    data = context.user_data["last"]

    context.user_data["attempts"].append({
        "question": data["question"],
        "options": data["options"],
        "selected": selected,
        "correct": data["correct"],
        "explanation": data["explanation"]
    })

    if selected == data["correct"]:
        context.user_data["score"] += 1
    else:
        context.user_data["wrong_questions"].append(data)

    context.user_data["q_no"] += 1

    if context.user_data["q_no"] >= context.user_data["limit"]:
        await show_result(q, context)
        return

    await send_mcq(q, context)

# ---------------- RESULT ----------------
async def show_result(q, context):
    score = context.user_data["score"]
    total = context.user_data["q_no"]

    cur.execute(
        "INSERT INTO scores VALUES (NULL,?,?,?,?,?)",
        (
            q.from_user.id,
            context.user_data["exam"],
            context.user_data["topic"],
            score,
            total,
            datetime.date.today().isoformat()
        )
    )
    conn.commit()

    await q.edit_message_text(
        f"🎯 Test Completed ✅\n\nScore: {score}/{total}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 Start New Test", callback_data="start_new")],
            [InlineKeyboardButton("📊 My Score", callback_data="go_myscore")],
            [InlineKeyboardButton("❌ Practice Wrong Only", callback_data="wrong_only")]
        ])
    )

# ---------------- WRONG ONLY ----------------
async def wrong_only_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    wrongs = context.user_data.get("wrong_questions", [])
    if not wrongs:
        await q.edit_message_text("🎉 No wrong questions!")
        return

    context.user_data["wrong_i"] = 0
    await show_wrong(q, context)

async def show_wrong(q, context):
    i = context.user_data["wrong_i"]
    wrongs = context.user_data["wrong_questions"]

    if i >= len(wrongs):
        await q.edit_message_text(
            "✅ Wrong-Only Practice Completed",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Start New Test", callback_data="start_new")]
            ])
        )
        return

    w = wrongs[i]
    await q.edit_message_text(
        f"❌ Wrong Question {i+1}\n\n{w['question']}\n\n"
        f"✅ Correct: {w['correct']}\n\n📘 {w['explanation']}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Next ▶", callback_data="wrong_next")]
        ])
    )

async def wrong_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["wrong_i"] += 1
    await show_wrong(q, context)

# ---------------- START NEW ----------------
async def start_new_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = [
        [InlineKeyboardButton("📘 MPPSC", callback_data="exam_MPPSC")],
        [InlineKeyboardButton("📕 UGC NET", callback_data="exam_NET")]
    ]
    await q.edit_message_text("🔁 Start New Test\n\nSelect Exam 👇", reply_markup=InlineKeyboardMarkup(kb))

# ---------------- MY SCORE ----------------
async def go_myscore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    cur.execute(
        "SELECT exam,topic,score,total,test_date FROM scores WHERE user_id=? ORDER BY id DESC LIMIT 5",
        (q.from_user.id,)
    )
    rows = cur.fetchall()

    if not rows:
        await q.edit_message_text("❌ No score history.")
        return

    msg = "📊 My Scores\n\n"
    for r in rows:
        msg += f"{r[0]} | {r[1]} → {r[2]}/{r[3]} ({r[4]})\n"

    await q.edit_message_text(msg)

# ---------------- MAIN ----------------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(start_new_test, "^start_new$"))
    app.add_handler(CallbackQueryHandler(go_myscore, "^go_myscore$"))
    app.add_handler(CallbackQueryHandler(wrong_only_start, "^wrong_only$"))
    app.add_handler(CallbackQueryHandler(wrong_next, "^wrong_next$"))
    app.add_handler(CallbackQueryHandler(exam_select, "^exam_"))
    app.add_handler(CallbackQueryHandler(topic_select, "^topic_"))
    app.add_handler(CallbackQueryHandler(answer, "^ans_"))

    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
