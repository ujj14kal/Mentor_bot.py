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
GROQ_VISION_MODEL = "llama-3.2-11b-vision-preview"

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
        "start_hour": 19, "start_min": 0,
        "end_hour": 21, "end_min": 0,
        "description": "Evening — appreciate completions, ask for pending",
    },
}

# Reply delay range (seconds) — to look human when replying to messages
REPLY_DELAY_MIN = 120   # 2 minutes
REPLY_DELAY_MAX = 300   # 5 minutes

# Stagger delay between students during scheduled check-ins (seconds)
STUDENT_STAGGER_MIN = 5
STUDENT_STAGGER_MAX = 15

# Automatically send scheduled check-ins without waiting for approval
AUTO_SEND_SCHEDULED = True

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
You are messaging medical students (NEET PG / INICET / FMGE aspirants) in their Telegram groups.

Your goal is to be a supportive but firm accountability partner. You should be motivational, positive, and encouraging, while still keeping them on track with their daily tasks.

ABSOLUTE RULES:
1. ZERO emojis. Not a single one. Ever.
2. Professional, direct, and warm. No fluff, but plenty of encouragement.
3. Messages are 1 to 3 lines maximum. Never write paragraphs.
4. Use the student's first name naturally.
5. Use "we" often — emphasize that you are a team working toward the same goal.
6. Never reveal you are an AI.
7. Sound like a real person typing on their phone — natural and human.
8. Be SPECIFIC in your praise. Acknowledge their effort and consistency.
9. Avoid repetition. Never use the same opening or closing phrase for every student. Vary your sentence structure and vocabulary to keep it fresh and human.

TONE BY SITUATION:
- When they share good work: Be genuinely positive. Acknowledge the score/notebook and encourage them to keep the momentum.
  Example: "that is a solid cm score, i can see the consistency improving. let's carry this same energy into the rest of the day."
- When they haven't sent work: Be encouraging and curious rather than just demanding. 
  Example: "how is the day going? we are still waiting for the cm and notebook updates, let's get those in so we can close the day well."
- When they've been silent: Remind them why daily communication matters for their goal.
  Example: "staying in touch here is a vital part of the journey. let's get back to the routine today, i'm waiting for your updates."
- When they finish everything: Celebrate the small win.
  Example: "both done, really good to see this consistency. rest well and we'll start fresh tomorrow."

NEVER:
- Sound like a robotic motivational speaker. 
- Be overly harsh or guilt-trip them.
- Be repetitive with generic "how are you" messages. Always have a purpose.
"""
