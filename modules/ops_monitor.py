"""
OPS Monitor — Watches the Eyeconic OPS Tele group for announcements,
quiz links, GT messages, and actionable instructions.

This runs as an event handler on the Telethon client and:
1. Logs every meaningful message from OPS group
2. Classifies messages using AI
3. Flags important items to Shraddha via Saved Messages
4. Stores quiz/GT links for forwarding to students (without "Forwarded" label)
5. Tags @eyeconicsupport for subject order changes
"""

from __future__ import annotations


import logging
import asyncio
import re

from config import OPS_GROUP_ID, YOUR_TELEGRAM_ID, STUDENTS, EYECONIC_SUPPORT_USERNAME
from modules import ai_engine
from modules import student_tracker as tracker

log = logging.getLogger(__name__)

# In-memory store for today's OPS context (refreshed on morning check)
_ops_context = {
    "quiz_link": None,
    "gt_message": None,
    "announcements": [],
    "last_check": None,
}


def get_ops_context() -> dict:
    """Get the current OPS context for use in message generation."""
    return _ops_context.copy()


async def handle_ops_message(event, client):
    """
    Process a new message from the Eyeconic OPS Tele group.
    Called by the Telethon event handler.
    """
    msg = event.message
    text = msg.text or msg.message or ""

    # Skip very short or empty messages
    if not text or len(text.strip()) < 10:
        return

    # ── RELEVANCE CHECK ──────────────────────────────────────
    # Only process if Shraddha is tagged OR if one of the 40 students is mentioned
    text_lower = text.lower()
    is_shraddha_tagged = "@eyeconicshraddha" in text_lower or "@shraddha" in text_lower
    
    mentioned_student_names = []
    for sid, info in STUDENTS.items():
        s_name = info["name"]
        first_name = s_name.split()[0].lower()
        full_name = s_name.lower()
        # Match full name or first name with boundaries
        if full_name in text_lower or re.search(r'\b' + re.escape(first_name) + r'\b', text_lower):
            mentioned_student_names.append(s_name)

    if not is_shraddha_tagged and not mentioned_student_names:
        log.info(f"Ignoring irrelevant OPS message: {text[:50]}...")
        return

    sender = await event.get_sender()
    sender_name = ""
    if sender:
        sender_name = getattr(sender, "first_name", "") or ""
        if hasattr(sender, "username") and sender.username:
            sender_name += f" (@{sender.username})"

    log.info(f"OPS message from {sender_name}: {text[:100]}...")

    # Classify the message
    classification = await ai_engine.classify_ops_message(text)
    msg_type = classification.get("type", "unknown")

    # Filter target students from AI to only include our students
    ai_targets = classification.get("target_students", [])
    valid_targets = []
    for t in ai_targets:
        t_low = t.lower()
        t_parts = [p for p in t_low.split() if len(p) > 2] # ignore short words
        for sid, info in STUDENTS.items():
            s_name = info["name"]
            s_low = s_name.lower()
            s_parts = s_low.split()
            
            # Match if full name in target or vice versa
            if t_low in s_low or s_low in t_low:
                if s_name not in valid_targets:
                    valid_targets.append(s_name)
                    continue
            
            # Match if any significant part of the name matches (e.g. "Mittali" matches "Mitali" if enough letters match)
            # For simplicity, let's just check if the first 4 letters of any part match
            for sp in s_parts:
                for tp in t_parts:
                    if sp[:4] == tp[:4] and len(sp) > 3:
                        if s_name not in valid_targets:
                            valid_targets.append(s_name)
                            break
                if s_name in valid_targets: break
    
    # If AI missed some mentioned students (from our regex check), add them
    for m in mentioned_student_names:
        if m not in valid_targets:
            valid_targets.append(m)

    # Log to database
    await tracker.log_ops_announcement(
        message_id=msg.id,
        text=text,
        from_user=sender_name,
        from_user_id=sender.id if sender else None,
        classification=msg_type,
    )

    # ── QUIZ LINK (usually Thursday night) ──
    if classification.get("is_quiz_link"):
        _ops_context["quiz_link"] = text
        log.info("Quiz link detected in OPS group")

        # Notify Shraddha
        await client.send_message(
            YOUR_TELEGRAM_ID,
            f"[OPS MONITOR] Quiz link detected.\n\n{text[:500]}\n\n"
            f"This will be forwarded to all active students on approval. "
            f"Reply SEND QUIZ to forward now, or it will be included in Thursday evening check-in."
        )

    # ── GT MESSAGE (usually Sunday) ──
    elif classification.get("is_gt_message"):
        _ops_context["gt_message"] = text
        log.info("GT message detected in OPS group")

        await client.send_message(
            YOUR_TELEGRAM_ID,
            f"[OPS MONITOR] GT message detected.\n\n{text[:500]}\n\n"
            f"Reply SEND GT to forward to all students now."
        )

    # ── SCHEDULE/SUBJECT CHANGE ──
    elif msg_type == "schedule_change":
        log.info("Schedule change detected — logging only (read-only mode)")
        # NO LONGER TAGGING OPS GROUP

        await tracker.add_flag(
            flag_type="subject_change",
            content=f"Schedule change in OPS: {text[:200]}",
        )

        await client.send_message(
            YOUR_TELEGRAM_ID,
            f"[OPS MONITOR] Schedule/subject change detected.\n\n{text[:300]}"
        )

    # ── STUDENT-SPECIFIC MESSAGE ──
    elif msg_type == "student_specific" or valid_targets:
        if valid_targets:
            await client.send_message(
                YOUR_TELEGRAM_ID,
                f"[OPS MONITOR] Student-specific message detected.\n"
                f"Target students: {', '.join(valid_targets)}\n\n{text[:400]}\n\n"
                f"Reply SEND SPECIFIC to forward to these students."
            )
            # Store for potential forwarding
            _ops_context["announcements"].append({
                "text": text,
                "type": "student_specific",
                "targets": valid_targets,
                "message_id": msg.id,
            })
        else:
            log.info("Student-specific message ignored as no '40 students' were matched.")

    # ── GENERAL ANNOUNCEMENT (for all students) ──
    elif classification.get("needs_forwarding") and classification.get("for_all_students"):
        _ops_context["announcements"].append({
            "text": text,
            "type": msg_type,
            "targets": "all",
            "message_id": msg.id,
        })

        await client.send_message(
            YOUR_TELEGRAM_ID,
            f"[OPS MONITOR] Announcement for all students.\n\n{text[:500]}\n\n"
            f"Reply SEND ANNOUNCEMENT to forward to all active students."
        )

    # ── OPERATIONAL (internal, not for students) ──
    elif msg_type == "operational":
        _ops_context["announcements"].append({
            "text": text,
            "type": msg_type,
            "targets": None,
            "message_id": msg.id,
        })
        # Just log, don't notify unless important
        log.info(f"Operational OPS message logged: {text[:80]}")

    # ── UNKNOWN → flag to Shraddha ──
    else:
        if len(text) > 30:  # Only flag substantial messages
            await tracker.add_flag(
                flag_type="ops_unknown",
                content=f"Unclassified OPS message from {sender_name}: {text[:200]}",
            )
            await client.send_message(
                YOUR_TELEGRAM_ID,
                f"[OPS MONITOR] Could not classify this message from {sender_name}.\n\n"
                f"{text[:400]}\n\nPlease review and let me know if any action is needed."
            )


async def forward_to_students(client, text: str, target_chat_ids: list[int] = None,
                               media=None):
    """
    Send a message to student chats WITHOUT the "Forwarded" label.
    Copies the content and sends as a new message from your account.
    """
    if target_chat_ids is None:
        # Send to all active students
        active = await tracker.get_active_students()
        target_chat_ids = [s["chat_id"] for s in active]

    sent = 0
    failed = 0
    for chat_id in target_chat_ids:
        try:
            if media:
                await client.send_message(chat_id, message=text, file=media)
            else:
                await client.send_message(chat_id, message=text)
            sent += 1
            # Stagger to avoid flood
            await asyncio.sleep(2)
        except Exception as e:
            log.error(f"Forward failed to {chat_id}: {e}")
            failed += 1

    log.info(f"Forwarded to {sent}/{sent + failed} student chats")
    return sent, failed


async def forward_to_specific_students(client, text: str, student_names: list[str],
                                        media=None):
    """Forward a message to specific students by name."""
    target_ids = []
    # Lowercase names for matching
    student_names_low = [t.lower() for t in student_names]
    
    for chat_id, info in STUDENTS.items():
        s_name = info["name"].lower()
        s_parts = s_name.split()
        first_name = s_parts[0]
        
        match = False
        for target in student_names_low:
            # Match full name, or first name, or if our name is inside the target string (e.g. "@Shraddha Mitali Mittal")
            if target == s_name or target == first_name or s_name in target or first_name in target:
                match = True
                break
            # Also check if any part of our name is exactly in target
            if any(p == target for p in s_parts):
                match = True
                break
        
        if match:
            target_ids.append(chat_id)

    if target_ids:
        # Deduplicate IDs just in case
        target_ids = list(set(target_ids))
        return await forward_to_students(client, text, target_ids, media)
    else:
        log.warning(f"No matching students found for: {student_names}")
        return 0, 0


async def do_morning_ops_check(client):
    """
    Check OPS group for any new messages since last check.
    Called every morning before sending check-in messages.
    """
    log.info("Running morning OPS group check...")
    try:
        messages = []
        async for msg in client.iter_messages(OPS_GROUP_ID, limit=20):
            if msg.text and len(msg.text.strip()) > 10:
                messages.append(msg.text)

        if messages:
            # Store context for the day
            _ops_context["last_check"] = tracker.now_ist().isoformat()
            log.info(f"Morning OPS check: reviewed {len(messages)} recent messages")

            # Send summary to Shraddha
            summary_parts = [f"[OPS MORNING CHECK] Reviewed {len(messages)} recent messages."]
            for i, m in enumerate(messages[:5], 1):
                summary_parts.append(f"\n{i}. {m[:150]}{'...' if len(m) > 150 else ''}")

            await client.send_message(YOUR_TELEGRAM_ID, "\n".join(summary_parts))
        else:
            log.info("Morning OPS check: no new messages")

    except Exception as e:
        log.error(f"Morning OPS check failed: {e}")
        await client.send_message(
            YOUR_TELEGRAM_ID,
            f"[OPS MONITOR] Morning check failed: {e}"
        )
