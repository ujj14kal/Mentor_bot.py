"""
Eyeconic Mentor System — Main Entry Point
==========================================
A Telethon userbot that sends messages through your personal Telegram account.
Messages look exactly like you're typing them — nobody knows it's automated.

Usage:
    python mentor_system.py

First run: will prompt for phone number and OTP to create a session.
Subsequent runs: uses the saved session file automatically.
"""

import logging
import asyncio
import sys
from pathlib import Path

from telethon import TelegramClient, events
from telethon.tl.types import PeerUser

from config import (
    TELEGRAM_API_ID, TELEGRAM_API_HASH, SESSION_NAME,
    YOUR_TELEGRAM_ID, OPS_GROUP_ID, STUDENTS, TIMEZONE, DATA_DIR,
)
from modules import student_tracker as tracker
from modules import message_handler
from modules import ops_monitor
from modules import confirmation
from modules.scheduler import create_scheduler, setup_jobs

# ─────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)-7s | %(name)-20s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(DATA_DIR / "mentor.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("mentor_system")

# Suppress noisy loggers
logging.getLogger("telethon").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)


# ─────────────────────────────────────────────────────────────
# VALIDATION
# ─────────────────────────────────────────────────────────────
def validate_config():
    """Check that essential config values are filled in."""
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
        log.warning("No students configured in config.py — system will run but won't message anyone")

    if errors:
        for e in errors:
            log.error(f"Config error: {e}")
        log.error("Fix the above errors in .env and config.py before running")
        sys.exit(1)


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
async def main():
    validate_config()

    # Initialize database
    await tracker.init_db()

    # Populate students table from config
    for chat_id, info in STUDENTS.items():
        await tracker.upsert_student(
            chat_id=chat_id,
            name=info["name"],
            batch=info.get("batch", ""),
            google_sheet_id=info.get("google_sheet_id", ""),
        )

    # Create Telethon client (your personal account)
    session_path = str(DATA_DIR / SESSION_NAME)
    client = TelegramClient(session_path, TELEGRAM_API_ID, TELEGRAM_API_HASH)

    await client.start()

    me = await client.get_me()
    log.info(f"Logged in as: {me.first_name} (@{me.username}), ID: {me.id}")

    if me.id != YOUR_TELEGRAM_ID:
        log.warning(
            f"YOUR_TELEGRAM_ID in config ({YOUR_TELEGRAM_ID}) doesn't match "
            f"logged-in account ({me.id}). Updating to match."
        )

    # ── EVENT HANDLERS ──────────────────────────────────────

    # 1. Student chat messages
    student_chat_ids = list(STUDENTS.keys())
    if student_chat_ids:
        @client.on(events.NewMessage(chats=student_chat_ids))
        async def on_student_message(event):
            """Handle incoming messages from student group chats."""
            try:
                await message_handler.handle_student_message(event, client)
            except Exception as e:
                log.error(f"Error handling student message: {e}", exc_info=True)

    # 2. OPS group messages
    if OPS_GROUP_ID and OPS_GROUP_ID != 0:
        @client.on(events.NewMessage(chats=[OPS_GROUP_ID]))
        async def on_ops_message(event):
            """Handle incoming messages from Eyeconic OPS Tele group."""
            try:
                await ops_monitor.handle_ops_message(event, client)
            except Exception as e:
                log.error(f"Error handling OPS message: {e}", exc_info=True)

    # 3. Saved Messages (your confirmations and commands)
    @client.on(events.NewMessage(outgoing=True))
    async def on_self_message(event):
        """
        Handle messages you send to Saved Messages (commands/confirmations).
        Only processes messages in your private chat (Saved Messages).
        """
        try:
            # Only process messages sent to Saved Messages (chat with yourself)
            if not event.is_private:
                return

            chat = await event.get_chat()
            if not chat or getattr(chat, "id", None) != YOUR_TELEGRAM_ID:
                return

            text = (event.message.text or "").strip()
            if not text:
                return

            log.info(f"Saved Messages command received: {text}")
            handled = await confirmation.handle_confirmation_reply(event, client)
            if not handled:
                pass  # Not a command, ignore
        except Exception as e:
            log.error(f"Error handling self message: {e}", exc_info=True)

    # ── SCHEDULER ───────────────────────────────────────────
    scheduler = create_scheduler()
    setup_jobs(scheduler, client)
    scheduler.start()

    # ── STARTUP MESSAGE ─────────────────────────────────────
    student_count = len(STUDENTS)
    active = await tracker.get_active_students()

    startup_msg = (
        f"Mentor System Online\n\n"
        f"Logged in as: {me.first_name} (@{me.username})\n"
        f"Students configured: {student_count}\n"
        f"Active students: {len(active)}\n"
        f"OPS group: {'Connected' if OPS_GROUP_ID else 'Not configured'}\n\n"
        f"Commands (type in Saved Messages):\n"
        f"  YES / SEND — approve pending check-ins\n"
        f"  SKIP — skip current check-in window\n"
        f"  SEND QUIZ — forward quiz link to all students\n"
        f"  SEND GT — forward GT message to all students\n"
        f"  SEND ANNOUNCEMENT — forward latest announcement\n"
        f"  SEND SPECIFIC — forward to targeted students\n"
        f"  STATUS — view system status"
    )

    await client.send_message(YOUR_TELEGRAM_ID, startup_msg)
    log.info("Mentor System is live and running")

    # Keep running
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
