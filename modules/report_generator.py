"""
Report Generator — Creates end-of-day reports with student status,
submission tracking, flags, and AI-generated comments.
Saved to Desktop as report_YYYY-MM-DD.txt and sent to Saved Messages.
"""

import logging
from datetime import datetime

from config import YOUR_TELEGRAM_ID, STUDENTS, REPORTS_DIR, TIMEZONE
from modules import student_tracker as tracker
from modules import ai_engine

log = logging.getLogger(__name__)


async def generate_daily_report(client=None) -> str:
    """
    Generate the full daily report.
    Returns the report text and saves to Desktop.
    Optionally sends to Saved Messages if client is provided.
    """
    date = tracker.today_str()
    day = tracker.weekday_name()

    all_students = await tracker.get_all_students()
    active_students = [s for s in all_students if s.get("status") == "active"]
    inactive_students = [s for s in all_students if s.get("status") == "inactive"]

    # Get daily submissions
    submissions = await tracker.get_all_daily_submissions(date)
    sub_map = {s["chat_id"]: s for s in submissions}

    # Get flags
    flags = await tracker.get_today_flags()

    # Get OPS announcements
    ops = await tracker.get_today_ops_announcements()

    # ── Calculate stats ──
    total = len(all_students)
    total_active = len(active_students)
    cm_count = sum(1 for s in submissions if s.get("cm_submitted"))
    mynb_count = sum(1 for s in submissions if s.get("mynb_submitted"))
    gt_count = sum(1 for s in submissions if s.get("gt_submitted")) if day == "Sunday" else None
    quiz_count = sum(1 for s in submissions if s.get("quiz_submitted")) if day == "Friday" else None

    # ── Build report ──
    lines = []
    sep = "=" * 55

    lines.append(sep)
    lines.append(f" DAILY MENTOR REPORT — {date} ({day})")
    lines.append(sep)
    lines.append("")

    # Summary
    lines.append("SUMMARY")
    lines.append(f"  Active students: {total_active}/{total}")
    lines.append(f"  CM submitted: {cm_count}/{total_active}")
    lines.append(f"  MyNotebook submitted: {mynb_count}/{total_active}")
    if gt_count is not None:
        lines.append(f"  GT submitted (Sunday): {gt_count}/{total_active}")
    if quiz_count is not None:
        lines.append(f"  Quiz submitted (Friday): {quiz_count}/{total_active}")
    lines.append("")

    # Student-wise table
    lines.append("STUDENT-WISE STATUS")
    lines.append("-" * 55)

    header = f"{'Student':<22} {'CM':<6} {'MYNB':<6}"
    if day == "Sunday":
        header += f" {'GT':<6} {'Class':<6}"
    if day == "Friday":
        header += f" {'Quiz':<6}"
    header += f" {'Status':<8}"
    lines.append(header)
    lines.append("-" * 55)

    for student in all_students:
        cid = student["chat_id"]
        name = student["name"]
        sub = sub_map.get(cid, {})
        status = student.get("status", "active").capitalize()

        cm = sub.get("cm_score", "A") if sub.get("cm_submitted") else "A"
        mynb = "P" if sub.get("mynb_submitted") else "A"

        row = f"{name:<22} {cm:<6} {mynb:<6}"

        if day == "Sunday":
            gt = sub.get("gt_score", "A") if sub.get("gt_submitted") else "A"
            cl = "P" if sub.get("gt_classification") else "A"
            row += f" {gt:<6} {cl:<6}"

        if day == "Friday":
            quiz = sub.get("quiz_score", "A") if sub.get("quiz_submitted") else "A"
            row += f" {quiz:<6}"

        row += f" {status:<8}"
        lines.append(row)

    lines.append("-" * 55)
    lines.append("")

    # Flagged items
    if flags:
        lines.append("FLAGGED ITEMS")
        for f in flags:
            ftype = f.get("type", "unknown").upper()
            fname = f.get("student_name", "")
            fcontent = f.get("content", "")[:150]
            lines.append(f"  [{ftype}] {fname}: {fcontent}")
        lines.append("")

    # OPS announcements
    if ops:
        lines.append("OPS ANNOUNCEMENTS TODAY")
        for a in ops:
            atype = a.get("classification", "").upper()
            atext = a.get("message_text", "")[:120]
            afrom = a.get("from_user", "")
            lines.append(f"  [{atype}] from {afrom}: {atext}")
        lines.append("")

    # Inactive students
    if inactive_students:
        lines.append("INACTIVE STUDENTS (7+ days)")
        for s in inactive_students:
            name = s["name"]
            days = await tracker.days_since_last_message(s["chat_id"])
            last_ping = s.get("last_inactive_ping", "never")
            lines.append(f"  {name} — {days} days silent, last pinged: {last_ping}")
        lines.append("")

    # AI-generated comments
    comments = await _generate_comments(active_students, sub_map, day)
    if comments:
        lines.append("COMMENTS")
        for c in comments:
            lines.append(f"  {c}")
        lines.append("")

    lines.append(sep)

    report_text = "\n".join(lines)

    # ── Save to Desktop ──
    filename = f"report_{date}.txt"
    filepath = REPORTS_DIR / filename
    try:
        filepath.write_text(report_text, encoding="utf-8")
        log.info(f"Report saved to {filepath}")
    except Exception as e:
        log.error(f"Error saving report to {filepath}: {e}")

    # ── Send to Saved Messages ──
    if client:
        try:
            # Split if too long
            for i in range(0, len(report_text), 3800):
                await client.send_message(YOUR_TELEGRAM_ID, report_text[i:i + 3800])
            log.info("Report sent to Saved Messages")
        except Exception as e:
            log.error(f"Error sending report to Saved Messages: {e}")

    return report_text


async def _generate_comments(active_students: list, sub_map: dict, day: str) -> list[str]:
    """Generate AI-powered observations for the daily report."""
    # Build context for AI
    summary_parts = []
    for s in active_students:
        cid = s["chat_id"]
        name = s["name"].split()[0]
        sub = sub_map.get(cid, {})
        cm = sub.get("cm_score", "not submitted") if sub.get("cm_submitted") else "not submitted"
        mynb = "submitted" if sub.get("mynb_submitted") else "not submitted"
        summary_parts.append(f"- {name}: CM={cm}, MyNotebook={mynb}")

    if not summary_parts:
        return []

    prompt = f"""Today is {day}. Here is a summary of all student submissions today:
{chr(10).join(summary_parts)}

Write 2-4 brief observations/comments for the mentor's daily report.
Focus on:
- Students who consistently improved or declined
- Students who missed submissions (pattern if any)
- Any notable scores or concerns
- Participation rates

Each comment should be one sentence. Be factual and specific. No emojis.
Return just the comments, one per line, starting with a bullet point (-)."""

    try:
        result = await ai_engine.generate_message(prompt, max_tokens=300)
        if result:
            comments = [line.strip().lstrip("- ").lstrip("* ")
                       for line in result.split("\n")
                       if line.strip() and len(line.strip()) > 10]
            return comments[:4]
    except Exception as e:
        log.error(f"Error generating report comments: {e}")

    return []
