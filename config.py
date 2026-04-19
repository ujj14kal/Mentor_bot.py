"""
Eyeconic Mentor System — Configuration
========================================
All settings, student roster, and persona definition.
Fill in everything before first run.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────
# TELEGRAM (MTProto via Telethon — your personal account)
# Get these from https://my.telegram.org → API Development Tools
# ─────────────────────────────────────────────────────────────
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")

# Your personal Telegram user ID (send /start to @userinfobot)
YOUR_TELEGRAM_ID = int(os.getenv("YOUR_TELEGRAM_ID", "0"))

# Eyeconic OPS Tele group chat ID
OPS_GROUP_ID = int(os.getenv("OPS_GROUP_ID", "0"))

# Session file name (stores your login — guard with your life)
SESSION_NAME = "shraddha_session"

# ─────────────────────────────────────────────────────────────
# GROQ AI (free tier — https://console.groq.com)
# ─────────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_TEXT_MODEL = "llama-3.3-70b-versatile"
GROQ_VISION_MODEL = "meta-llama/llama-4-maverick-17b-128e-instruct"

# ─────────────────────────────────────────────────────────────
# GOOGLE SHEETS
# ─────────────────────────────────────────────────────────────
GOOGLE_CREDS_FILE = os.getenv("GOOGLE_CREDS_FILE", "google_creds.json")

# Attendance sheet (on ops9 account)
ATTENDANCE_SHEET_ID = os.getenv("ATTENDANCE_SHEET_ID", "")
ATTENDANCE_WORKSHEET_NAME = "Daily Attendance"

# ─────────────────────────────────────────────────────────────
# TIMEZONE
# ─────────────────────────────────────────────────────────────
TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")

# ─────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "mentor.db"
REPORTS_DIR = Path.home() / "Desktop"  # reports saved to Desktop

# Ensure data directory exists
DATA_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────
# SCHEDULE WINDOWS (IST)
# ─────────────────────────────────────────────────────────────
SCHEDULE = {
    "morning": {
        "start_hour": 7, "start_min": 0,
        "end_hour": 8, "end_min": 30,
        "description": "Morning check-in — ask for work plan",
    },
    "afternoon": {
        "start_hour": 16, "start_min": 0,
        "end_hour": 16, "end_min": 45,
        "description": "Afternoon — task update check",
    },
    "evening": {
        "start_hour": 20, "start_min": 0,
        "end_hour": 20, "end_min": 45,
        "description": "Evening — appreciate completions, ask for pending",
    },
}

# Reply delay range (seconds) — to look human when replying to messages
REPLY_DELAY_MIN = 180   # 3 minutes
REPLY_DELAY_MAX = 600   # 10 minutes

# Stagger delay between students during scheduled check-ins (seconds)
STUDENT_STAGGER_MIN = 30
STUDENT_STAGGER_MAX = 120

# Inactive threshold (days)
INACTIVE_DAYS_THRESHOLD = 7
INACTIVE_ESCALATION_DAYS = 14

# ─────────────────────────────────────────────────────────────
# STUDENT ROSTER
# ─────────────────────────────────────────────────────────────
# Format: chat_id (int) → student info dict
# Get each group's chat ID from the group's description or
# by forwarding a message from the group to @userinfobot
#
# google_sheet_id: the spreadsheet ID from the sheet URL
#   e.g. from https://docs.google.com/spreadsheets/d/XXXXX/edit
#   the ID is XXXXX
#
# sheet_worksheet: which tab/worksheet name in that spreadsheet
# sheet_row: the row number for this student in their sheet
STUDENTS = {
    # ── Dominator 2.04 ──
    -1003849522671: {
        "name": "Noel Mondal",
        "batch": "Dominator 2.04",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003790233735: {
        "name": "Mahesh Vind",
        "batch": "Dominator 2.04",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003789034375: {
        "name": "Abhinav Kumar",
        "batch": "Dominator 2.04",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003689238292: {
        "name": "Abhishek Soni",
        "batch": "Dominator 2.04",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003559440129: {
        "name": "Tareen G Khan",
        "batch": "Dominator 2.04 - Working",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003647667037: {
        "name": "Aditya Butle",
        "batch": "Dominator (Performance)",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },

    # ── Dominator 2.12 ──
    -1003711984350: {
        "name": "Sundaram Chaudhary",
        "batch": "Dominator 2.12",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003666263124: {
        "name": "Tuba Ansari",
        "batch": "Dominator 2.12",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003712663652: {
        "name": "Kush Vyas",
        "batch": "Dominator 2.12",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },

    # ── Dominator 2.03 ──
    -1003836665528: {
        "name": "Aayushi Verma",
        "batch": "Dominator 2.03",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },

    # ── Foundation 4.14 ──
    -1003813734296: {
        "name": "Dibyayan",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003872145496: {
        "name": "Chandrima Adhikary",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003412473585: {
        "name": "Aarzoo Rawat",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003600618320: {
        "name": "Shreya Kashish",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003768381719: {
        "name": "Shivangi Bariar",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003620505081: {
        "name": "Bhavin",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003219193016: {
        "name": "Aditya Mittal",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003677846454: {
        "name": "Piyush Arora",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003594903083: {
        "name": "Pagidala Manognya",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003615551447: {
        "name": "Nishchith",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003519276357: {
        "name": "Vikas Detwani",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003419333003: {
        "name": "Pranjal Pareek",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -5049605162: {
        "name": "Pooja",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003512246451: {
        "name": "Vishal Bandi",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003784844657: {
        "name": "Kshitij",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003556933471: {
        "name": "Siman Sangeeta",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003593246081: {
        "name": "Rajnish Pandey",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003546727552: {
        "name": "Divyansh Thakur",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003601540612: {
        "name": "Pruthviraj Parmar",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003612061129: {
        "name": "Namrata Bag",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003500991190: {
        "name": "Payal Rani",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003660277419: {
        "name": "Rakesh Swain",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003546174452: {
        "name": "Sravya G",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003572470717: {
        "name": "Mitali Mittal",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003537881238: {
        "name": "Elakkiya",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -1003827430242: {
        "name": "Dhvani Parmar",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },

    # ── Foundation 4.14 (Non-Working) ──
    -1003518727437: {
        "name": "Sreeja Vattikoti",
        "batch": "Foundation 4.14 (Non-Working)",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -5134902752: {
        "name": "Sahithi Gandham",
        "batch": "Foundation 4.14 (Non-Working)",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
    -5217494778: {
        "name": "ISHU",
        "batch": "Foundation 4.14",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },

    # ── FMGE ──
    -1003536309726: {
        "name": "Rohit N Nikhade",
        "batch": "FMGE - Dec",
        "google_sheet_id": "",
        "sheet_worksheet": "Sheet1",
    },
}

# ─────────────────────────────────────────────────────────────
# GOOGLE SHEET COLUMN MAPPING (1-indexed, adjust to your sheets)
# ─────────────────────────────────────────────────────────────
SHEET_COLUMNS = {
    "date": 1,        # A — date
    "cm_score": 2,    # B — custom module score
    "mynb": 3,        # C — mynotebook (P/A)
    "gt_score": 4,    # D — grand test score (Sundays)
    "quiz_score": 5,  # E — quiz score (Fridays)
    "classification": 6,  # F — GT classification (Sundays)
}

# Attendance sheet column mapping
ATTENDANCE_COLUMNS = {
    "name": 1,        # A — student name
    "date_start": 2,  # B onwards — dates as column headers
}

# ─────────────────────────────────────────────────────────────
# EYECONIC SUPPORT HANDLE
# ─────────────────────────────────────────────────────────────
EYECONIC_SUPPORT_USERNAME = "eyeconicsupport"  # without @

# ─────────────────────────────────────────────────────────────
# PERSONA — This defines how AI writes messages as you
# ─────────────────────────────────────────────────────────────
SHRADDHA_PERSONA = """
You are Shraddha, an accountability mentor at Eyeconic by Dr Lalla.
You are messaging NEET PG / INICET / FMGE aspirant medical students one-on-one
inside their dedicated Telegram group chats.

ABSOLUTE RULES — violating any of these is a failure:
1. ZERO emojis. Not a single one. Ever.
2. Professional and direct. No fluff, no filler.
3. Messages are 1 to 3 lines maximum. Never write paragraphs.
4. Use the student's first name naturally but not in every single message.
5. Use "we" often — you and the student are a team in this.
6. Never say "as an AI", never reveal you are automated, never break character.
7. Never use bullet points, numbered lists, or any formatting. Plain natural sentences only.
8. Never use generic praise like "great job" or "keep it up" or "proud of you".
   Be SPECIFIC to what they did or did not do.
9. Never mention "NEET PG" or the exam name directly in every message.
   Reference it occasionally mid-week as "the bigger goal" or "what we are working towards".
10. Never use exclamation marks unless absolutely warranted.
11. Sound like a real person typing quickly on their phone. Short, natural, human.

TONE BY SITUATION:
- When they share good work: acknowledge the specific thing, then push forward.
  Example: "okay that cm score is looking better than last week, make sure we do the mixed bag cm today as well and share it."
- When they haven't sent work: be firm but not harsh.
  Example: "where are we? cm and notebook are still pending for today."
- When they've been silent for days: escalate slightly.
  Example: "a very crucial part of this journey is the communication between us, make sure none of us ruptures that."
- When they ask study doubts: answer clearly and practically like a senior who knows the syllabus.
- When both cm and notebook are done: appreciate specifically and close the day.
  Example: "both are done, that is how it should be everyday. rest well and we start fresh tomorrow."

NEVER:
- Start messages with "Hey" or "Hi" unless it is very natural.
- Use words like "awesome", "amazing", "fantastic", "brilliant".
- Sound motivational-speaker-ish. Sound like a mentor who has been through this.
- Send generic "how are you" messages. Always have a purpose.
"""
