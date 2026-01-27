📘 Telegram MCQ Exam Bot

A full-featured, production-ready Telegram MCQ Exam Platform with Student + Admin CMS, built using Python + python-telegram-bot + SQLite.
-----------------------------------------------------------------------------------------------------------------------------------------
**This bot is suitable for:**

🎓 Exam preparation channels

📚 Coaching institutes

🧪 Online test series

💰 Monetized EdTech projects
---------------------------------------------------------------------------------------------------------------------------------------------
**🚀 Features Overview**
🧑‍🎓 Student (User Side)
🎯 Exam Flow

Exam selection (Admin-enabled exams only)

Topic selection (exam-wise)

Disabled test auto-blocked with message

Random MCQ order

Question counter (Q x / Total)

Next / Previous navigation

Skip question support

Answer select & change allowed

Manual test finish option

Session expiry protection
--------------------------------------------------------------------------------------
**🧮 Result & Score**

Auto score calculation

Total marks display

Attempted answers stored

Duplicate score prevention (latest score only)
----------------------------------------------------------------------------------------------

**📋 Review System**

Review all questions

Review wrong-only questions

Correct answer shown as actual text

Explanation display

Pagination for long tests (Telegram-safe)

Review next / previous navigation

Back to result screen

Home navigation
------------------------------------------------------------------------------------
**📄 PDF Result**

PDF result generation

Hindi + English Unicode safe

Includes:

Question

Your Answer

Correct Answer

Explanation

User-wise secure PDF download
--------------------------------------------------------------------------------------------------
**👤 User Profile**

Username priority (@username)

Fallback → First + Last → User ID

Test history view

Latest score per exam/topic

Test date shown

Clean grouped records (no duplicates)
-------------------------------------------------------------------------
**🏆 Leaderboard**

Exam + Topic wise leaderboard

Best score per user

Top 10 users

Back → Result

Home → Exam select
-------------------------------------------------------------------------
**💖 Donate**

Professional donate page

UPI ID display

Copy UPI button

Back navigation
--------------------------------------------------------------------------------------------
**🧑‍💼 Admin Panel (CMS + Control)**
📊 Analytics Dashboard

Total users

Active users (today)

Active users (last 7 days)

Total tests given

Most popular test (exam + topic)

Test analytics:

Total MCQs

Questions per test

Weak tests (low MCQs)
-------------------------------------------------------------------------------
**👥 User Management (Read-Only)**

User list

Test count per user

Last active date

User test history view
----------------------------------------------------------------------
**📢 Broadcast**

Send message to all users

Success / failure count

Cancel support
---------------------------------------------------------------------------
**💾 Backup & Restore**

Database backup (.db)

Database restore (.db)

Safe overwrite protection

Restart required notice
----------------------------------------------------------------------------------
**📤 MCQ Data Management**

Excel Upload

Upload MCQs via Excel

Required column validation

Duplicate MCQ detection

Skip duplicates

Added / skipped count report

is_active auto set

Export

Export full MCQ database to Excel
-----------------------------------------------------------------------------------
**✍️ Manual MCQ Add (Without Excel)**

Step-by-step wizard (9 steps)

Exam → Topic → Question → A/B/C/D → Correct → Explanation

Preview before save

Cancel option

Duplicate detection

Force add duplicate using /force_add
----------------------------------------------------------------------------------
**🔍 Search / Edit MCQ**

Keyword search (question text)

MCQ shortlist

Individual MCQ edit menu

Edit:

Question

Option A

Option B

Option C

Option D

Correct answer

Correct answer selector (A/B/C/D)

Auto refresh after save

Safe state machine (no crash)
🚫 Enable / Disable Test
Exam + Topic wise toggle
Disabled tests hidden from users
Real-time effect
🗑 Delete Test (Dangerous)
Exam + Topic selection
Confirmation screen

**Deletes:**
All MCQs
All scores
Irreversible warning
-------------------------------------------------------------------------
**🔐 Security & Stability**
Admin ID based access control
User session safety
Telegram message length protection
No dead-end navigation
Back / Home available everywhere
SQLite with safe migrations
is_active auto-add migration
Production-ready architecture
---------------------------------------------------------------------
**🛠 Tech Stack**

Python 3.10+
python-telegram-bot v20+
SQLite
Pandas
ReportLab (PDF)
---------------------------------------------------------------------------
**📦 Installation**
pip install python-telegram-bot==20.7 pandas reportlab

**🔑 Configuration**

Set your bot token (recommended):
export BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN


Or edit directly in bot.py:
TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"


**Set Admin ID:**
ADMIN_IDS = [123456789]

▶️ Run Bot
python bot.py

**📁 Excel Upload Format**

Required columns:
exam | topic | question | a | b | c | d | correct | explanation

correct must be one of:
A / B / C / D

**🚀 Deployment Ready**

This bot can be deployed on:

1.VPS (Ubuntu)
2.Render
3.Railway
4.Docker
5.Local server

**📜 License**

This project is released for educational and commercial use.
You are free to customize, brand, and monetize.

**🙌 Support**
If you found this project useful:

1.⭐ Star the repository
2.💖 Donate via UPI    -----> 8085692143@ybl
3.🧑‍💻 Contribute improvements

**Contact:**
Mail Me : savankatara@gmail.com
call on: 8085692143
