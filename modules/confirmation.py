"""
Confirmation System — Sends batch previews to Shraddha's Saved Messages
and waits indefinitely for approval before sending.
"""

from __future__ import annotations


import logging
import asyncio

from config import YOUR_TELEGRAM_ID, STUDENTS
from modules import student_tracker as tracker

log = logging.getLogger(__name__)

# Track which window is currently awaiting confirmation
_pending_window = None
_confirmation_event = asyncio.Event()


def get_pending_window() -> str | None:
    """Get the window currently awaiting confirmation."""
    return _pending_window


async def request_confirmation(client, window: str, messages: list[dict]):
    """
    Send a batch preview to Saved Messages and wait for YES.
    messages: list of {"chat_id": int, "name": str, "text": str}
    Returns True if approved, False if skipped.
    """
    global _pending_window
    _pending_window = window
    _confirmation_event.clear()

    # Build preview
    window_label = {
        "morning": "Morning Check-in (6-9 AM)",
        "afternoon": "Afternoon Update (3:30-5 PM)",
        "evening": "Evening Follow-up (7:30-9 PM)",
    }.get(window, window)

    # Get inactive student count for morning
    inactive_summary = ""
    if window == "morning":
        inactive = await tracker.get_inactive_students()
        if inactive:
            inactive_summary = f"\n⚠️ {len(inactive)} INACTIVE STUDENTS (7+ days silent):\n"
            inactive_summary += "\n".join([f"- {s['name']} ({await tracker.days_since_last_message(s['chat_id'])} days)" for s in inactive[:10]])
            if len(inactive) > 10:
                inactive_summary += f"\n...and {len(inactive)-10} more."
            inactive_summary += "\n"

    preview_lines = [
        f"Ready to send {window_label} to {len(messages)} students.\n",
        inactive_summary
    ]
    for i, m in enumerate(messages, 1):
        short_text = m["text"][:120] + ("..." if len(m["text"]) > 120 else "")
        preview_lines.append(f"{i}. {m['name']}: \"{short_text}\"")

    preview_lines.append(
        f"\nReply YES to send all, SKIP to skip this window."
    )

    preview = "\n".join(preview_lines)

    # Split if too long (Telegram limit ~4096 chars)
    for i in range(0, len(preview), 3800):
        await client.send_message(YOUR_TELEGRAM_ID, preview[i:i + 3800])

    log.info(f"Confirmation requested for {window} window ({len(messages)} messages)")

    # Wait indefinitely for confirmation
    # The event is set by handle_confirmation_reply when user responds
    await _confirmation_event.wait()

    result = _confirmation_event.is_set()
    _pending_window = None
    return result


async def handle_confirmation_reply(event, client):
    """
    Handle a reply from Shraddha in Saved Messages.
    Processes YES/SKIP/SEND commands.
    """
    global _pending_window

    msg = event.message
    text = (msg.text or msg.message or "").strip().lower()

    if not text:
        return

    # ── SCHEDULED CHECK-IN CONFIRMATION ──
    if _pending_window and text in ("yes", "send", "y"):
        window = _pending_window
        await tracker.approve_checkins(window)
        _confirmation_event.set()
        await client.send_message(
            YOUR_TELEGRAM_ID,
            f"Approved. Sending {window} check-ins now."
        )
        log.info(f"Check-ins approved for {window}")
        return True

    if _pending_window and text in ("skip", "no", "n"):
        _confirmation_event.set()
        await client.send_message(
            YOUR_TELEGRAM_ID,
            f"Skipped {_pending_window} check-ins."
        )
        log.info(f"Check-ins skipped for {_pending_window}")
        _pending_window = None
        return True

    # ── OPS FORWARD COMMANDS ──
    if text == "send quiz":
        from modules.ops_monitor import get_ops_context, forward_to_students
        ctx = get_ops_context()
        if ctx.get("quiz_link"):
            sent, failed = await forward_to_students(client, ctx["quiz_link"])
            await client.send_message(
                YOUR_TELEGRAM_ID,
                f"Quiz link sent to {sent} students ({failed} failed)."
            )
        else:
            await client.send_message(
                YOUR_TELEGRAM_ID,
                "No quiz link found in recent OPS messages."
            )
        return True

    if text == "send gt":
        from modules.ops_monitor import get_ops_context, forward_to_students
        ctx = get_ops_context()
        if ctx.get("gt_message"):
            sent, failed = await forward_to_students(client, ctx["gt_message"])
            await client.send_message(
                YOUR_TELEGRAM_ID,
                f"GT message sent to {sent} students ({failed} failed)."
            )
        else:
            await client.send_message(
                YOUR_TELEGRAM_ID,
                "No GT message found in recent OPS messages."
            )
        return True

    if text == "send announcement":
        from modules.ops_monitor import get_ops_context, forward_to_students
        ctx = get_ops_context()
        announcements = [a for a in ctx.get("announcements", []) if a.get("targets") == "all"]
        if announcements:
            latest = announcements[-1]
            sent, failed = await forward_to_students(client, latest["text"])
            await client.send_message(
                YOUR_TELEGRAM_ID,
                f"Announcement sent to {sent} students ({failed} failed)."
            )
        else:
            await client.send_message(
                YOUR_TELEGRAM_ID,
                "No pending announcements to send."
            )
        return True

    if text.startswith("send specific"):
        from modules.ops_monitor import get_ops_context, forward_to_specific_students
        ctx = get_ops_context()
        specific = [a for a in ctx.get("announcements", [])
                     if a.get("type") == "student_specific" and a.get("targets")]
        if specific:
            latest = specific[-1]
            sent, failed = await forward_to_specific_students(
                client, latest["text"], latest["targets"]
            )
            await client.send_message(
                YOUR_TELEGRAM_ID,
                f"Sent to {sent} targeted students ({failed} failed)."
            )
        else:
            await client.send_message(
                YOUR_TELEGRAM_ID,
                "No pending student-specific messages to send."
            )
        return True

    # ── STATUS COMMAND ──
    if text == "status":
        students = await tracker.get_all_students()
        active = [s for s in students if s.get("status") == "active"]
        inactive = [s for s in students if s.get("status") == "inactive"]
        flags = await tracker.get_today_flags()

        status_msg = (
            f"System Status\n"
            f"Active students: {len(active)}\n"
            f"Inactive students: {len(inactive)}\n"
            f"Today's flags: {len(flags)}\n"
            f"Pending window: {_pending_window or 'None'}\n"
        )
        if inactive:
            status_msg += "\nRecently Inactive:\n"
            status_msg += "\n".join([f"- {s['name']} ({await tracker.days_since_last_message(s['chat_id'])} days)" for s in inactive[:5]])

        await client.send_message(YOUR_TELEGRAM_ID, status_msg)
        return True

    return False
