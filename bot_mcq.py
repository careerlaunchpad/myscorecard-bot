import os, sqlite3, datetime, csv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Document
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    CallbackQueryHandler, ContextTypes, MessageHandler, filters
)

TOKEN = os.getenv("BOT_TOKEN")

# 🔐 ADMIN IDS (ADD YOUR ID)
#ADMIN_IDS = [123456789]

# 💰 PRICE CONFIG
PLAN_PRICE = 199  # per month ₹

# ---------- DATABASE ----------
conn = sqlite3.connect("mcq.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    is_paid INTEGER DEFAULT 0,
    expiry TEXT
)
""")

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

# ---------- HELPERS ----------
def add_user(uid):
    cur.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (uid,))
    conn.commit()

def is_paid(uid):
    cur.execute("SELECT is_paid, expiry FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    if not r or r[0] == 0:
        return False
    return datetime.datetime.strptime(r[1], "%Y-%m-%d") >= datetime.datetime.now()

# ---------- START ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_user(update.effective_user.id)

    await update.message.reply_text(
        "👋 Welcome to MyScoreCard Bot\n\n"
        "🎯 Practice MCQs\n"
        "💰 Paid users get full access\n\n"
        "Commands:\n"
        "/pay – Upgrade Plan\n"
        "/myscore – Your history"
    )

# ---------- PAYMENT ----------
async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 Paid Plan – ₹199 / month\n\n"
        "UPI: yourupi@bank\n\n"
        "Payment करने के बाद admin को msg करें:\n"
        "Format:\n"
        "Paid – <your user id>"
    )

# ---------- ADMIN PANEL ----------
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    kb = [
        [InlineKeyboardButton("👥 Users", callback_data="admin_users")],
        [InlineKeyboardButton("💰 Revenue", callback_data="admin_revenue")],
        [InlineKeyboardButton("📥 Upload MCQ CSV", callback_data="admin_upload")]
    ]

    await update.message.reply_text(
        "📱 Admin Dashboard",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ---------- ADMIN USERS ----------
async def admin_users(update: Update, context):
    q = update.callback_query
    await q.answer()

    cur.execute("SELECT COUNT(*) FROM users")
    total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM users WHERE is_paid=1")
    paid = cur.fetchone()[0]

    await q.edit_message_text(
        f"👥 Users Stats\n\n"
        f"Total Users: {total}\n"
        f"Paid Users: {paid}"
    )

# ---------- REVENUE ----------
async def admin_revenue(update: Update, context):
    q = update.callback_query
    await q.answer()

    cur.execute("SELECT COUNT(*) FROM users WHERE is_paid=1")
    paid = cur.fetchone()[0]

    revenue = paid * PLAN_PRICE

    await q.edit_message_text(
        f"💰 Revenue Analytics\n\n"
        f"Active Paid Users: {paid}\n"
        f"Estimated Revenue: ₹{revenue}"
    )

# ---------- APPROVE USER ----------
async def approve(update: Update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return

    uid = int(context.args[0])
    days = int(context.args[1])

    expiry = (datetime.datetime.now() + datetime.timedelta(days=days)).strftime("%Y-%m-%d")

    cur.execute(
        "UPDATE users SET is_paid=1, expiry=? WHERE user_id=?",
        (expiry, uid)
    )
    conn.commit()

    await update.message.reply_text(f"✅ User {uid} approved till {expiry}")

# ---------- REMOVE USER ----------
async def remove(update: Update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return

    uid = int(context.args[0])
    cur.execute("UPDATE users SET is_paid=0 WHERE user_id=?", (uid,))
    conn.commit()

    await update.message.reply_text(f"❌ User {uid} removed from paid")

# ---------- CSV UPLOAD ----------
async def admin_upload(update: Update, context):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "📥 Upload MCQ CSV file now"
    )
    context.user_data["await_csv"] = True

async def handle_csv(update: Update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return

    if not context.user_data.get("await_csv"):
        return

    doc: Document = update.message.document
    file = await doc.get_file()
    path = "mcq_upload.csv"
    await file.download_to_drive(path)

    count = 0
    with open(path, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            cur.execute("""
            INSERT INTO mcq (exam,topic,question,a,b,c,d,correct,explanation)
            VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                r["exam"], r["topic"], r["question"],
                r["a"], r["b"], r["c"], r["d"],
                r["correct"], r["explanation"]
            ))
            count += 1

    conn.commit()
    context.user_data["await_csv"] = False

    await update.message.reply_text(f"✅ {count} MCQs uploaded successfully")
#-----------------myid-----------
async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Your ID is: {update.effective_user.id}"
    )

# ---------- MAIN ----------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("remove", remove))

    app.add_handler(CallbackQueryHandler(admin_users, "^admin_users$"))
    app.add_handler(CallbackQueryHandler(admin_revenue, "^admin_revenue$"))
    app.add_handler(CallbackQueryHandler(admin_upload, "^admin_upload$"))

    app.add_handler(MessageHandler(filters.Document.ALL, handle_csv))
    app.add_handler(CommandHandler("myid", myid))


    print("🤖 Bot Running with Paid + Upload + Revenue")
    app.run_polling()

if __name__ == "__main__":
    main()
