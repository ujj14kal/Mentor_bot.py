"""
Message Handler — Processes incoming student messages.
Generates contextual replies with a human-like delay (3-10 minutes).
Handles score screenshots, mynotebook photos, planner requests,
subject changes, GT classifications, and general conversation.
"""

import logging
import asyncio
import random
from datetime import timedelta

from config import (
    YOUR_TELEGRAM_ID, OPS_GROUP_ID, STUDENTS,
    EYECONIC_SUPPORT_USERNAME, REPLY_DELAY_MIN, REPLY_DELAY_MAX,
)
from modules import ai_engine
from modules import student_tracker as tracker

log = logging.getLogger(__name__)


async def handle_student_message(event, client):
    """
    Process an incoming message from a student group chat.
    Called by the Telethon event handler.
    """
    msg = event.message
    chat_id = event.chat_id

    # Get student info from config
    student_info = STUDENTS.get(chat_id)
    if not student_info:
        return  # Not a registered student chat

    # Check sender — only respond to the actual student, not other group members
    sender = await event.get_sender()
    if not sender:
        return

    # Skip messages from yourself (Shraddha's own account)
    if sender.id == YOUR_TELEGRAM_ID:
        return

    # Skip messages from admins/leaders in the group — only respond to student
    # We identify the student by checking if the sender's name matches
    sender_name = getattr(sender, "first_name", "") or ""
    student_first = student_info["name"].split()[0].lower()
    sender_first = sender_name.lower().strip()

    # If the group has other members, we need to be careful
    # For now, we respond to any non-self message but log the sender
    text = msg.text or msg.message or ""
    caption = text  # caption for photos

    name = student_info["name"].split()[0]
    now = tracker.now_ist()
    day = tracker.weekday_name()

    # Update last message timestamp
    await tracker.update_student_last_message(chat_id)

    # Log incoming message
    await tracker.log_message(
        chat_id=chat_id,
        direction="in",
        content=text[:500] if text else "[photo/media]",
        sender_id=sender.id,
        has_photo=bool(msg.photo),
    )

    # Get daily submission status
    daily = await tracker.get_daily_submission(chat_id)

    # ── PHOTO HANDLING ──────────────────────────────────────
    if msg.photo:
        await _handle_photo(event, client, msg, chat_id, student_info, name,
                            daily, day, caption)
        return

    # Skip empty text messages
    if not text or not text.strip():
        return

    # ── CLASSIFY THE MESSAGE ─────────────────────────────────
    classification = await ai_engine.classify_message(text)
    msg_type = classification.get("type", "unknown")
    needs_reply = classification.get("needs_reply", True)
    is_planner = classification.get("is_planner", False)
    is_subject_change = classification.get("is_subject_change", False)

    log.info(f"Message from {name} classified as: {msg_type} (reply: {needs_reply})")

    # ── PLANNER REQUEST → flag to Shraddha ───────────────────
    if is_planner:
        await tracker.add_flag(
            flag_type="planner",
            chat_id=chat_id,
            student_name=student_info["name"],
            content=text,
        )

        # Immediate flag to Shraddha
        await client.send_message(
            YOUR_TELEGRAM_ID,
            f"[PLANNER FLAG] {student_info['name']}:\n\"{text}\"\n\n"
            f"Please handle this manually."
        )

        # Delayed reply to student
        reply = f"Noted, {name}. I will look into this and update your planner."
        await _schedule_delayed_reply(client, chat_id, text, reply)
        return

    # ── SUBJECT ORDER CHANGE → tag eyeconicsupport on OPS ────
    if is_subject_change:
        await tracker.add_flag(
            flag_type="subject_change",
            chat_id=chat_id,
            student_name=student_info["name"],
            content=text,
        )

        try:
            await client.send_message(
                OPS_GROUP_ID,
                f"@{EYECONIC_SUPPORT_USERNAME} — {student_info['name']} is requesting "
                f"a change: \"{text[:200]}\". Please review."
            )
        except Exception as e:
            log.error(f"Error tagging eyeconicsupport: {e}")

        await client.send_message(
            YOUR_TELEGRAM_ID,
            f"[SUBJECT CHANGE] {student_info['name']}:\n\"{text}\"\n\n"
            f"Tagged @{EYECONIC_SUPPORT_USERNAME} on OPS group."
        )

        reply = f"Noted, {name}. I have raised this with the team, they will update it."
        await _schedule_delayed_reply(client, chat_id, text, reply)
        return

    # ── GT CLASSIFICATION (Sunday long text) ─────────────────
    if day == "Sunday" and len(text) > 60:
        check = ai_engine.validate_gt_classification(text)
        if check["valid"]:
            await tracker.update_submission(
                chat_id, gt_classification=1
            )
            prompt = (
                f"Student {name} submitted their complete GT classification on Sunday. "
                f"Acknowledge briefly and motivate for the week ahead."
            )
            reply = await ai_engine.generate_message(prompt)
            await _schedule_delayed_reply(client, chat_id, text, reply)
            return
        elif any(kw in text.lower() for kw in ["positive", "negative", "error", "mistake"]):
            # Partial classification — ask for the rest
            missing_str = ", ".join(check["missing"])
            reply = (
                f"The classification is incomplete, {name}. "
                f"Missing: {missing_str}. Resend the complete one."
            )
            await _schedule_delayed_reply(client, chat_id, text, reply)
            return

    # ── IRRELEVANT / NO REPLY NEEDED ─────────────────────────
    if not needs_reply:
        log.info(f"No reply needed for message from {name}: {msg_type}")
        return

    # ── GENERATE CONTEXTUAL REPLY ────────────────────────────
    # Get recent conversation history for context
    recent = await tracker.get_recent_messages(chat_id, limit=6)
    history_str = ""
    if recent:
        history_parts = []
        for m in recent[-4:]:  # last 4 messages for context
            direction = "You" if m["direction"] == "out" else name
            history_parts.append(f"{direction}: {m['content'][:150]}")
        history_str = "\n".join(history_parts)

    cm_done = bool(daily.get("cm_submitted"))
    nb_done = bool(daily.get("mynb_submitted"))
    silent_days = await tracker.days_since_last_message(chat_id)

    prompt = f"""Student: {name} | Batch: {student_info.get('batch', '')} | Day: {day}
Their message: "{text}"
Days silent before this message: {max(0, silent_days - 1)}
CM submitted today: {cm_done} | Notebook submitted today: {nb_done}
{"Quiz day." if day == "Friday" else ""}{"GT day." if day == "Sunday" else ""}

Recent conversation:
{history_str}

Reply as their accountability partner. Be specific to what they said.
If it's a progress update: acknowledge specifically with positive reinforcement, and encourage the next step.
If it's a doubt about studies: answer clearly, practically, and supportively.
If they just returned after being silent: welcome them back warmly, acknowledge the gap briefly, and help them get back to the routine with a positive focus.
If CM or mynb still pending, encourage them to complete it soon so we can finish the day strong.
Keep it 1-3 lines. Natural, motivational, and positive. No emojis."""

    reply = await ai_engine.generate_message(prompt)
    if reply:
        await _schedule_delayed_reply(client, chat_id, text, reply)


async def _handle_photo(event, client, msg, chat_id, student_info, name,
                        daily, day, caption):
    """Handle photo messages — score screenshots or notebook photos."""
    try:
        # Download the photo
        photo_bytes = await client.download_media(msg, bytes)
        if not photo_bytes:
            log.warning(f"Could not download photo from {name}")
            return

        # Extract score using vision AI
        result = await ai_engine.extract_score_from_image(photo_bytes, caption)
        score_type = result.get("score_type", "unknown")
        value = result.get("value", "")
        pct = result.get("percentage", 0)
        pct_str = f"{pct}%" if pct else value

        log.info(f"Photo from {name}: type={score_type}, value={pct_str}")

        if score_type == "cm":
            await tracker.update_submission(
                chat_id, cm_submitted=1, cm_score=pct_str, attendance="P"
            )
            extra = " Make sure the notebook is sent too." if not daily.get("mynb_submitted") else ""
            prompt = (
                f"Student {name} just submitted their CM score of {pct_str}. "
                f"Acknowledge it briefly and push forward.{extra}"
            )
            reply = await ai_engine.generate_message(prompt)
            await _schedule_delayed_reply(client, chat_id, f"[CM Score: {pct_str}]", reply)

        elif score_type == "mynb":
            await tracker.update_submission(
                chat_id, mynb_submitted=1, attendance="P"
            )
            both_done = bool(daily.get("cm_submitted"))
            prompt = (
                f"Student {name} just sent their notebook. "
                f"{'Both CM and notebook are done for today.' if both_done else 'CM score is still pending for today.'} "
                f"Respond appropriately."
            )
            reply = await ai_engine.generate_message(prompt)
            await _schedule_delayed_reply(client, chat_id, "[Notebook submitted]", reply)

        elif score_type == "gt" and day == "Sunday":
            await tracker.update_submission(
                chat_id, gt_submitted=1, gt_score=pct_str, attendance="P"
            )
            if not daily.get("gt_classification"):
                reply = (
                    f"GT score noted, {name}. Send the complete classification now — "
                    f"3 positives, 3 negatives, number of classification errors, "
                    f"recall errors, silly mistakes, and misread questions."
                )
            else:
                prompt = (
                    f"Student {name} sent GT score {pct_str} and already submitted classification. "
                    f"Acknowledge and motivate for the week."
                )
                reply = await ai_engine.generate_message(prompt)
            await _schedule_delayed_reply(client, chat_id, f"[GT Score: {pct_str}]", reply)

        elif score_type == "quiz" and day == "Friday":
            await tracker.update_submission(
                chat_id, quiz_submitted=1, quiz_score=pct_str, attendance="P"
            )
            context = (
                "above 80%, solid" if pct >= 80
                else ("below 60%, needs attention" if pct < 60
                      else "decent, room to improve")
            )
            prompt = (
                f"Student {name} sent quiz score {pct_str} ({context}). "
                f"Respond as their accountability partner — be specific."
            )
            reply = await ai_engine.generate_message(prompt)
            await _schedule_delayed_reply(client, chat_id, f"[Quiz Score: {pct_str}]", reply)

        else:
            # Unknown photo — flag to Shraddha
            await client.send_message(
                YOUR_TELEGRAM_ID,
                f"[PHOTO] Unrecognised photo from {student_info['name']}. "
                f"Score type detected: {score_type}. Caption: \"{caption[:200]}\". "
                f"Please check manually.",
            )

    except Exception as e:
        log.error(f"Error handling photo from {name}: {e}")


async def _schedule_delayed_reply(client, chat_id: int, trigger: str, reply_text: str):
    """
    Schedule a reply to be sent after a random human-like delay (3-10 minutes).
    The reply is queued in the database and sent by the reply dispatcher.
    """
    if not reply_text:
        return

    delay_seconds = random.randint(REPLY_DELAY_MIN, REPLY_DELAY_MAX)
    send_at = tracker.now_ist() + timedelta(seconds=delay_seconds)

    await tracker.add_pending_reply(
        chat_id=chat_id,
        trigger_message=trigger[:200],
        reply_text=reply_text,
        scheduled_at=send_at.isoformat(),
    )

    log.info(
        f"Reply to {chat_id} scheduled in {delay_seconds}s "
        f"({delay_seconds // 60}m {delay_seconds % 60}s): {reply_text[:60]}..."
    )


async def dispatch_pending_replies(client):
    """
    Check for and send any pending replies that are due.
    This is called periodically (every 30 seconds) by the scheduler.
    """
    due = await tracker.get_due_replies()
    for reply in due:
        chat_id = reply["chat_id"]
        text = reply["reply_text"]
        try:
            await client.send_message(chat_id, text)

            # Log the outgoing message
            await tracker.log_message(
                chat_id=chat_id,
                direction="out",
                content=text[:500],
            )

            await tracker.mark_reply_sent(reply["id"])
            log.info(f"Delayed reply sent to {chat_id}: {text[:60]}...")

            # Small delay between sends
            await asyncio.sleep(1)

        except Exception as e:
            log.error(f"Failed to send delayed reply to {chat_id}: {e}")
            # Mark as sent anyway to avoid infinite retries
            await tracker.mark_reply_sent(reply["id"])
