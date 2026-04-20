"""
Eyeconic Mentor System — Main Entry Point
==========================================
A Telethon userbot that sends messages through your personal Telegram account.

Key fixes vs previous version:
- Single instance lock (no duplicate processes / DB lock errors)
- Catch-up tracks last replied message ID per student — no duplicate replies
- Sequential catch-up with proper throttling
- Python 3.9 compatible throughout
"""

from __future__ import annotations

import logging
import asyncio
import sys
import os
import fcntl
import aiosqlite
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from telethon import TelegramClient, events
from zoneinfo import ZoneInfo

from config import (
    TELEGRAM_API_ID, TELEGRAM_API_HASH, SESSION_NAME,
    YOUR_TELEGRAM_ID, OPS_GROUP_ID, STUDENTS, TIMEZONE, DATA_DIR,
    INACTIVE_DAYS_THRESHOLD, DB_PATH
)
from modules import student_tracker as tracker
from modules import message_handler
from modules import ops_monitor
from modules import confirmation
from modules.scheduler import create_scheduler, setup_jobs

# ─────────────────────────────────────────────────────────────
# SINGLE INSTANCE LOCK
# ─────────────────────────────────────────────────────────────
_LOCK_FILE = DATA_DIR / "mentor.lock"
_lock_fh = None
_STARTUP_CATCHUP_DELAY_SECONDS = 90
_startup_catchup_queue: Optional[asyncio.Queue] = None


@dataclass
class StartupCatchupItem:
    student_name: str
    chat_id: int
    msg_id: int
    event: object


def acquire_single_instance_lock():
    global _lock_fh
    try:
        _lock_fh = open(_LOCK_FILE, "w")
        fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fh.write(str(os.getpid()))
        _lock_fh.flush()
    except IOError:
        print(
            "ERROR: Another instance is already running.\n"
            "Kill it first, or delete data/mentor.lock if it's stale."
        )
        sys.exit(1)


def release_single_instance_lock():
    global _lock_fh
    if _lock_fh:
        try:
            fcntl.flock(_lock_fh, fcntl.LOCK_UN)
            _lock_fh.close()
            _LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)-7s | %(name)-20s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(DATA_DIR / "mentor.log", encoding="utf-8"),
    ],
    force=True,
)
log = logging.getLogger("mentor_system")

logging.getLogger("telethon").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)


# ─────────────────────────────────────────────────────────────
# REPLY TRACKING — prevents duplicate catch-up replies
# ─────────────────────────────────────────────────────────────
async def _ensure_reply_tracking_table():
    """Add last_replied_msg_id column to students table if missing."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Add column only if it doesn't exist (safe to call repeatedly)
        try:
            await db.execute(
                "ALTER TABLE students ADD COLUMN last_replied_msg_id INTEGER DEFAULT 0"
            )
            await db.commit()
        except Exception:
            pass  # Column already exists


async def _get_last_replied_msg_id(chat_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT last_replied_msg_id FROM students WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row and row[0] else 0


async def _set_last_replied_msg_id(chat_id: int, msg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE students SET last_replied_msg_id = ? WHERE chat_id = ?",
            (msg_id, chat_id)
        )
        await db.commit()


def _get_startup_catchup_queue() -> asyncio.Queue:
    """Get or create the in-memory startup catch-up queue."""
    global _startup_catchup_queue
    if _startup_catchup_queue is None:
        _startup_catchup_queue = asyncio.Queue()
    return _startup_catchup_queue


async def _process_startup_catchup_queue(client):
    """
    Drain startup catch-up slowly in the background so the bot can come online
    without blasting Groq with a large restart backlog.
    """
    queue = _get_startup_catchup_queue()

    while True:
        item: StartupCatchupItem = await queue.get()
        try:
            last_replied_id = await _get_last_replied_msg_id(item.chat_id)
            if last_replied_id and last_replied_id >= item.msg_id:
                log.info(
                    f"Startup catch-up: skipping {item.student_name} "
                    f"(msg_id={item.msg_id}) because a newer reply is already recorded."
                )
                continue

            await message_handler.handle_student_message(item.event, client)
            await _set_last_replied_msg_id(item.chat_id, item.msg_id)
            log.info(f"Startup catch-up: replied to {item.student_name} (msg_id={item.msg_id})")
        except Exception as e:
            log.warning(f"Startup catch-up reply failed for {item.student_name}: {e}")
        finally:
            queue.task_done()

        # Add extra spacing between offline catch-up items so live messages
        # can be prioritized and Groq does not get hammered right after restart.
        await asyncio.sleep(_STARTUP_CATCHUP_DELAY_SECONDS)


# ─────────────────────────────────────────────────────────────
# VALIDATION
# ─────────────────────────────────────────────────────────────
def validate_config():
    errors = []
    if not TELEGRAM_API_ID or TELEGRAM_API_ID == 0:
        errors.append("TELEGRAM_API_ID is not set in .env")
    if not TELEGRAM_API_HASH:
        errors.append("TELEGRAM_API_HASH is not set in .env")
    if not YOUR_TELEGRAM_ID or YOUR_TELEGRAM_ID == 0:
        errors.append("YOUR_TELEGRAM_ID is not set in .env")

    from config import GROQ_API_KEY
    if not GROQ_API_KEY:
        errors.append("GROQ_API_KEY is not set in .env")

    if not STUDENTS:
        log.warning("No students configured — system will run but won't message anyone")

    if errors:
        for e in errors:
            log.error(f"Config error: {e}")
        sys.exit(1)


# ─────────────────────────────────────────────────────────────
# STARTUP CATCH-UP
# ─────────────────────────────────────────────────────────────
async def run_startup_catchup(client, me):
    """
    Check for messages sent while offline.
    - Only processes messages from the last 12 hours
    - Skips students whose last message was already replied to (tracks by message ID)
    - Runs one student at a time — no burst firing
    """
    log.info("Running startup activity check for all students...")
    all_db_students = await tracker.get_all_students()
    now_ist = tracker.now_ist()

    class MockEvent:
        def __init__(self, message, chat_id):
            self.message = message
            self.chat_id = chat_id

        async def get_sender(self):
            return await self.message.get_sender()

    catchup_queue = _get_startup_catchup_queue()

    for student in all_db_students:
        cid = student["chat_id"]
        try:
            last_replied_id = await _get_last_replied_msg_id(cid)

            async for message in client.iter_messages(cid, limit=1):
                # Skip if the last message is from us
                if message.sender_id == me.id:
                    break

                # Skip if we already replied to this exact message
                if message.id == last_replied_id:
                    log.debug(f"Startup catch-up: {student['name']} already replied to msg {message.id}, skipping.")
                    break

                msg_ts = message.date.astimezone(ZoneInfo(TIMEZONE))
                days_since = (now_ist - msg_ts).days
                new_status = "active" if days_since < INACTIVE_DAYS_THRESHOLD else "inactive"

                # Update activity timestamp and status
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "UPDATE students SET last_message_at = ?, status = ? WHERE chat_id = ?",
                        (msg_ts.isoformat(), new_status, cid)
                    )
                    await db.commit()

                log.info(
                    f"Startup catch-up: Updated {student['name']} to {new_status} "
                    f"(Last: {msg_ts.strftime('%Y-%m-%d %H:%M')})"
                )

                # Only queue a reply if the message is recent (< 12 hours)
                age_hours = (now_ist - msg_ts).total_seconds() / 3600
                if age_hours < 12:
                    log.info(f"Startup catch-up: queuing reply for {student['name']} (msg_id={message.id})")
                    catchup_queue.put_nowait(
                        StartupCatchupItem(
                            student_name=student["name"],
                            chat_id=cid,
                            msg_id=message.id,
                            event=MockEvent(message, cid),
                        )
                    )
                break

        except Exception as e:
            log.warning(f"Could not check activity for {student['name']}: {e}")

    queued_count = catchup_queue.qsize()
    if queued_count == 0:
        log.info("Startup catch-up: no missed messages to reply to.")
        return

    log.info(
        f"Startup catch-up: {queued_count} students need replies. "
        f"Queued for background processing every {_STARTUP_CATCHUP_DELAY_SECONDS}s."
    )


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
async def main():
    validate_config()

    await tracker.init_db()
    await _ensure_reply_tracking_table()

    for chat_id, info in STUDENTS.items():
        await tracker.upsert_student(
            chat_id=chat_id,
            name=info["name"],
            batch=info.get("batch", ""),
            google_sheet_id=info.get("google_sheet_id", ""),
            status=info.get("status", "active"),
        )

    session_path = str(DATA_DIR / SESSION_NAME)
    client = TelegramClient(session_path, TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.start()

    me = await client.get_me()
    log.info(f"Logged in as: {me.first_name} (@{me.username}), ID: {me.id}")

    # Start the catch-up worker before collecting backlog items so restart
    # messages drain safely in the background instead of blocking startup.
    asyncio.create_task(_process_startup_catchup_queue(client))

    # Run catch-up before registering event handlers to avoid double-processing
    await run_startup_catchup(client, me)

    # ── EVENT HANDLERS ───────────────────────────────────────

    student_chat_ids = list(STUDENTS.keys())
    if student_chat_ids:
        @client.on(events.NewMessage(chats=student_chat_ids))
        async def on_student_message(event):
            try:
                await message_handler.handle_student_message(event, client)
                await _set_last_replied_msg_id(event.chat_id, event.message.id)
            except Exception as e:
                log.error(f"Error handling student message: {e}", exc_info=True)

    if OPS_GROUP_ID and OPS_GROUP_ID != 0:
        @client.on(events.NewMessage(chats=[OPS_GROUP_ID]))
        async def on_ops_message(event):
            try:
                await ops_monitor.handle_ops_message(event, client)
            except Exception as e:
                log.error(f"Error handling OPS message: {e}", exc_info=True)

    @client.on(events.NewMessage(outgoing=True))
    async def on_self_message(event):
        try:
            if not event.is_private:
                return
            chat = await event.get_chat()
            if not chat or getattr(chat, "id", None) != YOUR_TELEGRAM_ID:
                return
            text = (event.message.text or "").strip()
            if not text:
                return
            log.info(f"Saved Messages command received: {text}")
            await confirmation.handle_confirmation_reply(event, client)
        except Exception as e:
            log.error(f"Error handling self message: {e}", exc_info=True)

    # ── SCHEDULER ────────────────────────────────────────────
    scheduler = create_scheduler()
    setup_jobs(scheduler, client)
    scheduler.start()

    # ── STARTUP MESSAGE ──────────────────────────────────────
    active = await tracker.get_active_students()
    await client.send_message(
        YOUR_TELEGRAM_ID,
        f"Mentor System Online\n"
        f"Students: {len(STUDENTS)} configured, {len(active)} active\n"
        f"OPS group: {'Connected' if OPS_GROUP_ID else 'Not configured'}\n\n"
        f"Commands: YES | SKIP | SEND QUIZ | SEND GT | SEND ANNOUNCEMENT | SEND SPECIFIC | STATUS"
    )
    log.info("Mentor System is live and running")

    try:
        await client.run_until_disconnected()
    finally:
        release_single_instance_lock()


if __name__ == "__main__":
    acquire_single_instance_lock()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Stopped by user.")
    finally:
        release_single_instance_lock()
