"""
Scheduler — APScheduler setup for all timed operations.
Manages the 3 daily check-in windows, 11 PM audit, reply dispatch,
inactive checks, and daily reports.
"""

import logging
import random
import asyncio
from datetime import timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import (
    STUDENTS, SCHEDULE, TIMEZONE,
    STUDENT_STAGGER_MIN, STUDENT_STAGGER_MAX,
)
from modules import ai_engine
from modules import student_tracker as tracker
from modules import ops_monitor
from modules import confirmation
from modules import sheets_manager
from modules import attendance as attendance_mgr
from modules import report_generator
from modules import inactive_manager
from modules import message_handler

log = logging.getLogger(__name__)


def create_scheduler() -> AsyncIOScheduler:
    """Create and configure the APScheduler instance."""
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    return scheduler


def setup_jobs(scheduler: AsyncIOScheduler, client):
    """Register all scheduled jobs."""

    # ── Morning check-in (trigger at start of window) ──
    morning = SCHEDULE["morning"]
    scheduler.add_job(
        _run_checkin_window,
        "cron",
        hour=morning["start_hour"],
        minute=morning["start_min"],
        args=[client, "morning"],
        id="checkin_morning",
        name="Morning Check-in",
    )

    # ── Afternoon check-in ──
    afternoon = SCHEDULE["afternoon"]
    scheduler.add_job(
        _run_checkin_window,
        "cron",
        hour=afternoon["start_hour"],
        minute=afternoon["start_min"],
        args=[client, "afternoon"],
        id="checkin_afternoon",
        name="Afternoon Check-in",
    )

    # ── Evening check-in ──
    evening = SCHEDULE["evening"]
    scheduler.add_job(
        _run_checkin_window,
        "cron",
        hour=evening["start_hour"],
        minute=evening["start_min"],
        args=[client, "evening"],
        id="checkin_evening",
        name="Evening Check-in",
    )

    # ── Pending reply dispatcher (every 30 seconds) ──
    scheduler.add_job(
        message_handler.dispatch_pending_replies,
        "interval",
        seconds=30,
        args=[client],
        id="reply_dispatch",
        name="Reply Dispatcher",
    )

    # ── 11 PM daily audit (sheets + attendance) ──
    scheduler.add_job(
        _run_daily_audit,
        "cron",
        hour=23,
        minute=0,
        args=[client],
        id="daily_audit",
        name="11 PM Daily Audit",
    )

    # ── 6:50 AM Inactive check (Moved from 10 PM) ──
    scheduler.add_job(
        inactive_manager.check_and_update_inactive,
        "cron",
        hour=6,
        minute=50,
        args=[client],
        id="inactive_check",
        name="Inactive Student Check",
    )

    # ── 11:15 PM daily report ──
    scheduler.add_job(
        report_generator.generate_daily_report,
        "cron",
        hour=23,
        minute=15,
        args=[client],
        id="daily_report",
        name="Daily Report",
    )

    # ── Weekly inactive ping (Monday 8 AM) ──
    scheduler.add_job(
        inactive_manager.ping_inactive_students,
        "cron",
        day_of_week="mon",
        hour=8,
        minute=0,
        args=[client],
        id="inactive_ping",
        name="Weekly Inactive Ping",
    )

    log.info("All scheduled jobs registered")

    # ── Run startup catch-up check ──
    asyncio.create_task(check_for_missed_windows(client))


# ─────────────────────────────────────────────────────────────
# CHECK-IN WINDOW LOGIC
# ─────────────────────────────────────────────────────────────
async def _run_checkin_window(client, window: str):
    """
    Execute a check-in window:
    1. Check OPS group first
    2. Generate messages for all active students (incorporating recent history)
    3. Send preview to Saved Messages for confirmation
    4. Wait indefinitely for YES
    5. Send messages with staggered delays
    """
    day = tracker.weekday_name()
    log.info(f"Starting {window} check-in window ({day})")

    # Step 1: Check OPS group every morning
    if window == "morning":
        await ops_monitor.do_morning_ops_check(client)
        # Also ensure inactive check is fresh if we just started
        await inactive_manager.check_and_update_inactive(client)

    # Step 2: Generate messages for each active student
    active_students = await tracker.get_active_students()
    if not active_students:
        log.info("No active students — skipping check-in")
        return

    messages = []
    for student in active_students:
        chat_id = student["chat_id"]
        name = student["name"].split()[0]
        info = STUDENTS.get(chat_id, {})
        batch = info.get("batch", student.get("batch", ""))
        daily = await tracker.get_daily_submission(chat_id)
        silent_days = await tracker.days_since_last_message(chat_id)
        cm_done = bool(daily.get("cm_submitted"))
        nb_done = bool(daily.get("mynb_submitted"))

        # Get recent history context (last 20 messages to cover 48 hours)
        recent_history = await tracker.get_recent_messages(chat_id, limit=20)
        history_str = "\n".join([f"{'You' if m['direction']=='out' else name}: {m['content']}" for m in recent_history])

        # Get OPS context for relevant info
        ops_ctx = ops_monitor.get_ops_context()

        prompt = _build_checkin_prompt(
            window=window,
            name=name,
            batch=batch,
            day=day,
            silent_days=silent_days,
            cm_done=cm_done,
            nb_done=nb_done,
            ops_ctx=ops_ctx,
            daily=daily,
            history_ctx=history_str
        )

        msg_text = await ai_engine.generate_message(prompt)
        if msg_text:
            messages.append({
                "chat_id": chat_id,
                "name": student["name"],
                "text": msg_text,
            })

            # Store in pending check-ins
            await tracker.add_pending_checkin(window, chat_id, msg_text)

    if not messages:
        log.warning(f"No messages generated for {window} window")
        return

    # Step 3: Send preview and wait for confirmation
    approved = await confirmation.request_confirmation(client, window, messages)

    if not approved:
        log.info(f"{window} check-ins skipped by user")
        return

    # Step 4: Send approved messages with staggered delays
    approved_checkins = await tracker.get_approved_unsent_checkins(window)
    sent_count = 0

    for checkin in approved_checkins:
        try:
            await client.send_message(checkin["chat_id"], checkin["message_text"])

            # Log outgoing
            await tracker.log_message(
                chat_id=checkin["chat_id"],
                direction="out",
                content=checkin["message_text"][:500],
            )

            await tracker.mark_checkin_sent(checkin["id"])
            sent_count += 1

            # Staggered delay between students
            delay = random.randint(STUDENT_STAGGER_MIN, STUDENT_STAGGER_MAX)
            await asyncio.sleep(delay)

        except Exception as e:
            log.error(f"Failed to send check-in to {checkin['chat_id']}: {e}")

    # Confirm to Shraddha
    await client.send_message(
        YOUR_TELEGRAM_ID if client else None,
        f"{window.capitalize()} check-ins sent to {sent_count}/{len(approved_checkins)} students."
    )
    log.info(f"{window} check-ins complete: {sent_count}/{len(approved_checkins)}")


def _build_checkin_prompt(window: str, name: str, batch: str, day: str,
                           silent_days: int, cm_done: bool, nb_done: bool,
                           ops_ctx: dict, daily: dict, history_ctx: str = "") -> str:
    """Build the AI prompt for a check-in message."""

    # Day-specific context
    is_friday = day == "Friday"
    is_sunday = day == "Sunday"
    is_thursday = day == "Thursday"
    is_midweek = day in ("Wednesday", "Thursday")

    context_header = f"Student: {name} | Batch: {batch} | Day: {day}\nDays silent: {silent_days}\n"
    if history_ctx:
        context_header += f"\nRecent History (Last 48 Hours):\n{history_ctx}\n"
        context_header += "\nIMPORTANT: If the student mentioned being on leave, sick, or taking an off in the last 48 hours, acknowledge it and do not ask for a work plan. If they just sent a score/update, acknowledge it specifically.\n"

    if window == "morning":
        base = f"""Student: {name} | Batch: {batch} | Day: {day}
Days silent before today: {silent_days}
"""
        if silent_days > 2:
            base += f"\n{name} has been silent for {silent_days} days. Address this first, then ask for today's plan."
        else:
            base += f"\nWrite a morning check-in. Ask {name} to share today's task plan."

        if is_friday:
            base += "\nToday is Friday — quiz day. Remind about the quiz."
        elif is_sunday:
            base += "\nToday is Sunday — GT day. Remind about GT attempt and classification requirement."
        elif is_thursday:
            base += "\nTomorrow is quiz day. Brief reminder."

        if is_midweek:
            base += ("\nOptionally include a brief line about staying focused on "
                    "what we are working towards. Don't name the exam directly.")

        if ops_ctx.get("quiz_link") and is_friday:
            base += "\nQuiz link has been shared — remind them to attempt it today."
        if ops_ctx.get("gt_message") and is_sunday:
            base += "\nGT link has been shared — remind them to attempt it today."

        base += "\nKeep it 1-3 lines. Natural. No emojis."
        return base

    elif window == "afternoon":
        return f"""Student: {name} | Batch: {batch} | Day: {day}
CM submitted today: {cm_done} | Notebook submitted: {nb_done}
Days silent: {silent_days}

Write a short afternoon check-in asking for a progress update on today's tasks.
If cm or mynb not yet submitted, specifically ask about those.
{'Quiz reminder if not done yet.' if is_friday and not daily.get('quiz_submitted') else ''}
{'GT reminder if not done yet.' if is_sunday and not daily.get('gt_submitted') else ''}
Keep it 1-2 lines. Natural. No emojis."""

    else:  # evening
        return f"""Student: {name} | Batch: {batch} | Day: {day}
CM submitted today: {cm_done} | Notebook submitted: {nb_done}
{'Quiz score expected today.' if is_friday else ''}
{'GT score and classification expected today.' if is_sunday else ''}
Days silent: {silent_days}

Write an evening check-in.
{'Both CM and notebook are done — appreciate specifically and close the day.' if cm_done and nb_done else ''}
{'CM and notebook still missing — be firm.' if not cm_done and not nb_done else ''}
{'CM is done but notebook is still missing.' if cm_done and not nb_done else ''}
{'Notebook is done but CM score is still pending.' if not cm_done and nb_done else ''}
{'Ask about quiz submission.' if is_friday and not daily.get('quiz_submitted') else ''}
{'Ask about GT and classification.' if is_sunday and not daily.get('gt_submitted') else ''}
Keep it 1-3 lines. Be firm about missing submissions. No emojis."""


# ─────────────────────────────────────────────────────────────
# 11 PM DAILY AUDIT
# ─────────────────────────────────────────────────────────────
async def _run_daily_audit(client):
    """
    11 PM audit: update centralized Google Sheets and mark attendance.
    Uses the single master score sheet with CM/Quiz/GT tabs.
    """
    from config import YOUR_TELEGRAM_ID

    date = tracker.today_str()
    day = tracker.weekday_name()
    log.info(f"Running 11 PM daily audit for {date} ({day})")

    missing = []
    attendance_statuses = {}

    for chat_id, info in STUDENTS.items():
        name = info["name"]
        daily = await tracker.get_daily_submission(chat_id)

        # Determine attendance
        has_activity = bool(daily.get("cm_submitted") or daily.get("mynb_submitted"))
        att_status = "P" if has_activity else "A"
        attendance_statuses[name] = att_status

        # Update centralized Google Sheet
        cm_score = daily.get("cm_score", "") if daily.get("cm_submitted") else ""
        mynb = bool(daily.get("mynb_submitted"))
        gt_score = daily.get("gt_score", "") if daily.get("gt_submitted") else ""
        quiz_score = daily.get("quiz_score", "") if daily.get("quiz_submitted") else ""

        try:
            sheets_manager.update_all_scores(
                student_name=name,
                date=date,
                cm_score=cm_score,
                mynb=mynb,
                quiz_score=quiz_score,
                gt_score=gt_score,
            )
        except Exception as e:
            log.error(f"Sheet update failed for {name}: {e}")
            missing.append(f"{name} — sheet update error: {str(e)[:80]}")

        # Track missing submissions
        if not daily.get("cm_submitted"):
            missing.append(f"{name} — CM score")
        if not daily.get("mynb_submitted"):
            missing.append(f"{name} — notebook (mynb)")
        if day == "Friday" and not daily.get("quiz_submitted"):
            missing.append(f"{name} — quiz score")
        if day == "Sunday" and not daily.get("gt_submitted"):
            missing.append(f"{name} — GT score")
        if day == "Sunday" and not daily.get("gt_classification"):
            missing.append(f"{name} — GT classification")

    # Attendance marking disabled — user handles manually
    # try:
    #     attendance_mgr.mark_all_attendance(attendance_statuses, date)
    # except Exception as e:
    #     log.error(f"Attendance update failed: {e}")

    # Notify Shraddha
    if missing:
        header = f"11 PM Audit — {date} — {len(missing)} items missing:\n\n"
        body = "\n".join(f"- {m}" for m in missing)
        full = header + body
        for i in range(0, len(full), 3800):
            await client.send_message(YOUR_TELEGRAM_ID, full[i:i + 3800])
    else:
        await client.send_message(
            YOUR_TELEGRAM_ID,
            f"11 PM Audit — {date} — All students submitted CM and notebook."
        )

    log.info(f"Daily audit complete: {len(missing)} missing items")


async def check_for_missed_windows(client):
    """
    Safety check on startup: if Mac is turned on within 1 hour of a window's
    start time, and no check-in exists for today, trigger it immediately.
    """
    log.info("Running startup catch-up check...")
    now = tracker.now_ist()
    today = tracker.today_str()

    # ── Check-in Windows Catch-up ──
    for window_name, times in SCHEDULE.items():
        # Check if we are within the window (from start_hour to end_hour)
        start = now.replace(hour=times["start_hour"], minute=times["start_min"], second=0, microsecond=0)
        end = now.replace(hour=times["end_hour"], minute=times["end_min"], second=0, microsecond=0)

        if start <= now <= end:
            # Check if we already have pending checkins for this window today
            pending = await tracker.get_pending_checkins(window_name)
            today_pending = [p for p in pending if p["created_at"].startswith(today)]

            if not today_pending:
                log.info(f"Startup catch-up: Active {window_name} window detected. Triggering now.")
                asyncio.create_task(_run_checkin_window(client, window_name))
                return  # Only catch up one window at a time

    # ── 11 PM Audit Catch-up (if started between 11 PM and Midnight) ──
    audit_start = now.replace(hour=23, minute=0, second=0, microsecond=0)
    audit_end = audit_start + timedelta(hours=1)

    if audit_start <= now <= audit_end:
        log.info("Startup catch-up: 11 PM Audit window active. Running now.")
        asyncio.create_task(_run_daily_audit(client))
        # Also run the 11:15 PM report if we are past that time
        report_start = now.replace(hour=23, minute=15, second=0, microsecond=0)
        if now >= report_start:
            asyncio.create_task(report_generator.generate_daily_report(client))
