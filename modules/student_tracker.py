"""
Student Tracker — SQLite database for all student state management.
Tracks daily submissions, message history, OPS announcements, and flags.
"""

from __future__ import annotations


import logging
import aiosqlite
from datetime import datetime
from zoneinfo import ZoneInfo

from config import DB_PATH, TIMEZONE, INACTIVE_DAYS_THRESHOLD

log = logging.getLogger(__name__)


async def init_db():
    """Create all tables if they don't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS students (
                chat_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                batch TEXT,
                google_sheet_id TEXT,
                status TEXT DEFAULT 'active',
                last_message_at TEXT,
                last_reply_at TEXT,
                inactive_since TEXT,
                last_inactive_ping TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS daily_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                cm_submitted INTEGER DEFAULT 0,
                cm_score TEXT DEFAULT '',
                mynb_submitted INTEGER DEFAULT 0,
                gt_submitted INTEGER DEFAULT 0,
                gt_score TEXT DEFAULT '',
                gt_classification INTEGER DEFAULT 0,
                quiz_submitted INTEGER DEFAULT 0,
                quiz_score TEXT DEFAULT '',
                attendance TEXT DEFAULT 'A',
                UNIQUE(chat_id, date)
            );

            CREATE TABLE IF NOT EXISTS message_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                direction TEXT NOT NULL,
                sender_id INTEGER,
                content TEXT,
                has_photo INTEGER DEFAULT 0,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS ops_announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                message_text TEXT,
                from_user TEXT,
                from_user_id INTEGER,
                classification TEXT DEFAULT 'unknown',
                forwarded_to_students INTEGER DEFAULT 0,
                flagged_to_mentor INTEGER DEFAULT 0,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS flags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                chat_id INTEGER,
                student_name TEXT,
                content TEXT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                resolved INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS pending_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                trigger_message TEXT,
                reply_text TEXT,
                scheduled_at TEXT,
                sent INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS pending_checkins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                window TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                message_text TEXT NOT NULL,
                approved INTEGER DEFAULT 0,
                sent INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(window, chat_id, created_at)
            );
        """)
        await db.commit()
    log.info("Database initialized")


def now_ist() -> datetime:
    """Current time in IST."""
    return datetime.now(ZoneInfo(TIMEZONE))


def today_str() -> str:
    """Today's date as YYYY-MM-DD string in IST."""
    return now_ist().strftime("%Y-%m-%d")


def weekday_name() -> str:
    """Current day of week name in IST."""
    return now_ist().strftime("%A")


# ─────────────────────────────────────────────────────────────
# STUDENT OPERATIONS
# ─────────────────────────────────────────────────────────────
async def upsert_student(chat_id: int, name: str, batch: str = "",
                         google_sheet_id: str = "", status: str = "active"):
    """Insert or update a student record."""
    # Check if student exists to preserve status unless explicitly provided
    existing = await get_student(chat_id)
    
    async with aiosqlite.connect(DB_PATH) as db:
        if not existing:
            # New student: set initial status and current time as last_message_at
            # so they don't get marked inactive immediately
            await db.execute("""
                INSERT INTO students (chat_id, name, batch, google_sheet_id, status, last_message_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (chat_id, name, batch, google_sheet_id, status, now_ist().isoformat()))
        else:
            # Existing student: update info and status
            await db.execute("""
                UPDATE students SET
                    name = ?,
                    batch = ?,
                    google_sheet_id = ?,
                    status = ?
                WHERE chat_id = ?
            """, (name, batch, google_sheet_id, status, chat_id))
        await db.commit()


async def get_student(chat_id: int) -> dict | None:
    """Get a student's record."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM students WHERE chat_id = ?", (chat_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_student_last_message(chat_id: int):
    """Update the last message timestamp for a student."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE students SET last_message_at = ?, status = 'active', inactive_since = NULL WHERE chat_id = ?",
            (now_ist().isoformat(), chat_id),
        )
        await db.commit()


async def get_all_students() -> list[dict]:
    """Get all student records."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM students")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_active_students() -> list[dict]:
    """Get all active student records."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM students WHERE status = 'active'")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_inactive_students() -> list[dict]:
    """Get all inactive student records."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM students WHERE status = 'inactive'")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def mark_student_inactive(chat_id: int):
    """Mark a student as inactive."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE students SET status = 'inactive', inactive_since = ? WHERE chat_id = ?",
            (now_ist().isoformat(), chat_id),
        )
        await db.commit()


async def days_since_last_message(chat_id: int) -> int:
    """Calculate days since the student last sent a message."""
    student = await get_student(chat_id)
    if not student:
        return 999

    # Fallback to created_at if last_message_at is missing
    last_ts = student.get("last_message_at") or student.get("created_at")
    if not last_ts:
        return 0

    try:
        # Standardize format (replace space with T if needed)
        if " " in last_ts and "T" not in last_ts:
            last_ts = last_ts.replace(" ", "T")
            
        last = datetime.fromisoformat(last_ts)
        if last.tzinfo is None:
            last = last.replace(tzinfo=ZoneInfo(TIMEZONE))
        return max(0, (now_ist() - last).days)
    except (ValueError, TypeError):
        return 999


# ─────────────────────────────────────────────────────────────
# DAILY SUBMISSIONS
# ─────────────────────────────────────────────────────────────
async def get_daily_submission(chat_id: int, date: str = None) -> dict:
    """Get or create today's submission record."""
    date = date or today_str()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Try to get existing
        cursor = await db.execute(
            "SELECT * FROM daily_submissions WHERE chat_id = ? AND date = ?",
            (chat_id, date),
        )
        row = await cursor.fetchone()

        if row:
            return dict(row)

        # Create new
        await db.execute(
            "INSERT INTO daily_submissions (chat_id, date) VALUES (?, ?)",
            (chat_id, date),
        )
        await db.commit()

        cursor = await db.execute(
            "SELECT * FROM daily_submissions WHERE chat_id = ? AND date = ?",
            (chat_id, date),
        )
        row = await cursor.fetchone()
        return dict(row)


async def update_submission(chat_id: int, date: str = None, **kwargs):
    """Update a submission field. Pass field=value pairs."""
    date = date or today_str()
    # Ensure record exists
    await get_daily_submission(chat_id, date)

    allowed = {"cm_submitted", "cm_score", "mynb_submitted", "gt_submitted",
               "gt_score", "gt_classification", "quiz_submitted", "quiz_score",
               "attendance"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [chat_id, date]

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE daily_submissions SET {set_clause} WHERE chat_id = ? AND date = ?",
            values,
        )
        await db.commit()


async def get_all_daily_submissions(date: str = None) -> list[dict]:
    """Get all submission records for a specific date."""
    date = date or today_str()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM daily_submissions WHERE date = ?", (date,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────
# MESSAGE HISTORY
# ─────────────────────────────────────────────────────────────
async def log_message(chat_id: int, direction: str, content: str,
                      sender_id: int = None, has_photo: bool = False):
    """Log a message (incoming or outgoing)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO message_history
               (chat_id, direction, sender_id, content, has_photo, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (chat_id, direction, sender_id, content, int(has_photo),
             now_ist().isoformat()),
        )
        await db.commit()


async def get_recent_messages(chat_id: int, limit: int = 10) -> list[dict]:
    """Get recent messages for a student chat for context."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM message_history
               WHERE chat_id = ? ORDER BY timestamp DESC LIMIT ?""",
            (chat_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in reversed(rows)]


# ─────────────────────────────────────────────────────────────
# OPS ANNOUNCEMENTS
# ─────────────────────────────────────────────────────────────
async def log_ops_announcement(message_id: int, text: str, from_user: str,
                                from_user_id: int = None, classification: str = "unknown"):
    """Log an OPS group announcement."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO ops_announcements
               (message_id, message_text, from_user, from_user_id, classification, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (message_id, text, from_user, from_user_id, classification,
             now_ist().isoformat()),
        )
        await db.commit()


async def get_today_ops_announcements() -> list[dict]:
    """Get all OPS announcements from today."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM ops_announcements WHERE date(timestamp) = ?",
            (today_str(),),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────
# FLAGS
# ─────────────────────────────────────────────────────────────
async def add_flag(flag_type: str, chat_id: int = None, student_name: str = "",
                   content: str = ""):
    """Add a flag for mentor review."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO flags (type, chat_id, student_name, content, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (flag_type, chat_id, student_name, content, now_ist().isoformat()),
        )
        await db.commit()
    log.info(f"Flag added: [{flag_type}] {student_name}: {content[:80]}")


async def get_today_flags() -> list[dict]:
    """Get all flags from today."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM flags WHERE date(timestamp) = ?", (today_str(),)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────
# PENDING REPLIES (delayed replies to look human)
# ─────────────────────────────────────────────────────────────
async def add_pending_reply(chat_id: int, trigger_message: str,
                            reply_text: str, scheduled_at: str):
    """Queue a reply to be sent after a delay."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO pending_replies
               (chat_id, trigger_message, reply_text, scheduled_at)
               VALUES (?, ?, ?, ?)""",
            (chat_id, trigger_message, reply_text, scheduled_at),
        )
        await db.commit()


async def get_due_replies() -> list[dict]:
    """Get all pending replies that are due to be sent."""
    now = now_ist().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM pending_replies WHERE sent = 0 AND scheduled_at <= ?",
            (now,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def mark_reply_sent(reply_id: int):
    """Mark a pending reply as sent."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE pending_replies SET sent = 1 WHERE id = ?", (reply_id,)
        )
        await db.commit()


# ─────────────────────────────────────────────────────────────
# PENDING CHECK-INS (confirmation workflow)
# ─────────────────────────────────────────────────────────────
async def add_pending_checkin(window: str, chat_id: int, message_text: str):
    """Queue a check-in message waiting for approval."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO pending_checkins (window, chat_id, message_text, created_at)
               VALUES (?, ?, ?, ?)""",
            (window, chat_id, message_text, now_ist().isoformat()),
        )
        await db.commit()


async def get_pending_checkins(window: str = None) -> list[dict]:
    """Get all pending (unapproved) check-in messages."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if window:
            cursor = await db.execute(
                "SELECT * FROM pending_checkins WHERE approved = 0 AND sent = 0 AND window = ?",
                (window,),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM pending_checkins WHERE approved = 0 AND sent = 0"
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def approve_checkins(window: str):
    """Mark all pending check-ins for a window as approved."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE pending_checkins SET approved = 1 WHERE window = ? AND sent = 0",
            (window,),
        )
        await db.commit()


async def get_approved_unsent_checkins(window: str = None) -> list[dict]:
    """Get check-ins that are approved but not yet sent."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if window:
            cursor = await db.execute(
                "SELECT * FROM pending_checkins WHERE approved = 1 AND sent = 0 AND window = ?",
                (window,),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM pending_checkins WHERE approved = 1 AND sent = 0"
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def mark_checkin_sent(checkin_id: int):
    """Mark a check-in as sent."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE pending_checkins SET sent = 1 WHERE id = ?", (checkin_id,)
        )
        await db.commit()
