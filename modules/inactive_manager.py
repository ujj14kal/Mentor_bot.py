"""
Inactive Manager — Tracks students who haven't responded in 7+ days
and sends weekly motivational re-engagement messages.
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import (
    STUDENTS, YOUR_TELEGRAM_ID, TIMEZONE,
    INACTIVE_DAYS_THRESHOLD, INACTIVE_ESCALATION_DAYS,
)
from modules import student_tracker as tracker
from modules import ai_engine

log = logging.getLogger(__name__)


async def check_and_update_inactive(client):
    """
    Check all students for inactivity and update their status.
    Students silent for 7+ days are marked inactive.
    Called daily (e.g., at 10 PM before the audit).
    """
    all_students = await tracker.get_all_students()
    newly_inactive = []

    for student in all_students:
        chat_id = student["chat_id"]
        name = student["name"]
        days = await tracker.days_since_last_message(chat_id)
        
        # Skip students added in the last 24 hours to give them a chance to send their first message
        created_at = student.get("created_at")
        if created_at:
            try:
                # Handle potential space instead of T in created_at from SQLite
                if " " in created_at and "T" not in created_at:
                    created_at = created_at.replace(" ", "T")
                created_dt = datetime.fromisoformat(created_at)
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=ZoneInfo(TIMEZONE))
                if (tracker.now_ist() - created_dt).total_seconds() < 86400: # 24 hours
                    continue
            except (ValueError, TypeError):
                pass

        if days >= INACTIVE_DAYS_THRESHOLD and student.get("status") == "active":
            await tracker.mark_student_inactive(chat_id)
            newly_inactive.append(f"{name} ({days} days)")
            log.info(f"Marked {name} as inactive ({days} days silent)")

    if newly_inactive:
        await client.send_message(
            YOUR_TELEGRAM_ID,
            f"[INACTIVE ALERT] Newly inactive students:\n"
            + "\n".join(f"- {n}" for n in newly_inactive)
        )


async def ping_inactive_students(client):
    """
    Send weekly motivational messages to inactive students.
    Called once a week (Monday morning).
    """
    inactive = await tracker.get_inactive_students()
    now = tracker.now_ist()
    pinged = 0

    for student in inactive:
        chat_id = student["chat_id"]
        name = student["name"].split()[0]
        days = await tracker.days_since_last_message(chat_id)

        # Check if we've pinged them in the last 7 days
        last_ping = student.get("last_inactive_ping")
        if last_ping:
            try:
                last_ping_dt = datetime.fromisoformat(last_ping)
                if last_ping_dt.tzinfo is None:
                    last_ping_dt = last_ping_dt.replace(tzinfo=ZoneInfo(TIMEZONE))
                if (now - last_ping_dt).days < 7:
                    continue  # Already pinged this week
            except (ValueError, TypeError):
                pass

        # Check if needs escalation (14+ days)
        if days >= INACTIVE_ESCALATION_DAYS:
            await tracker.add_flag(
                flag_type="inactive_escalation",
                chat_id=chat_id,
                student_name=student["name"],
                content=f"Silent for {days} days — needs manual intervention",
            )
            await client.send_message(
                YOUR_TELEGRAM_ID,
                f"[ESCALATION] {student['name']} has been silent for {days} days. "
                f"This needs your personal attention."
            )

        # Generate motivational message
        batch = STUDENTS.get(chat_id, {}).get("batch", "")
        prompt = f"""Student: {name} | Batch: {batch}
Days without any message: {days}

Write a firm but motivating message to {name} about the importance of daily communication
and consistency. Address the silence directly — {days} days is significant.
Be direct but do not guilt trip excessively.
Reference that this communication is a crucial part of their preparation journey.
Make it personal and warm but firm. 1-3 lines. No emojis."""

        reply = await ai_engine.generate_message(prompt)
        if reply:
            try:
                await client.send_message(chat_id, reply)

                # Update last ping time
                import aiosqlite
                from config import DB_PATH
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "UPDATE students SET last_inactive_ping = ? WHERE chat_id = ?",
                        (now.isoformat(), chat_id),
                    )
                    await db.commit()

                # Log outgoing
                await tracker.log_message(
                    chat_id=chat_id,
                    direction="out",
                    content=reply[:500],
                )

                pinged += 1
                log.info(f"Inactive ping sent to {name} ({days} days silent)")

                import asyncio
                await asyncio.sleep(3)  # Stagger

            except Exception as e:
                log.error(f"Failed to ping inactive student {name}: {e}")

    if pinged > 0:
        await client.send_message(
            YOUR_TELEGRAM_ID,
            f"[INACTIVE PING] Sent re-engagement messages to {pinged} inactive students."
        )

    return pinged
