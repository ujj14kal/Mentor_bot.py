"""
Eyeconic Mentor Bot — Full System
===================================
Architecture:
  - One bot monitors ALL individual student group chats (8 members each)
  - Also monitors EC OPS TEAM TELE for quiz/GT announcements
  - Claude acts as YOU (Shraddha) — professional, direct, no emojis
  - Google Sheets auto-updated for CM scores, mynb, GT, Quiz at 11pm daily

Modules:
  1. Scheduled check-ins (3 windows/day) to each student chat
  2. 11pm daily audit — mark sheet + flag missing submissions to you
  3. Auto-responder — reads student messages, replies as you
  4. Ops forwarder — detects quiz/GT messages in OPS group, asks your approval
  5. Score tracker — Claude Vision reads CM/GT/Quiz screenshots → Sheet
  6. GT classification validator — checks Sunday GT classification format
  7. Weekly inactive ping (7+ days silent)

FILL IN CONFIG BELOW BEFORE RUNNING.
"""

import re
import json
import base64
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# CONFIG — fill everything here before running
# ─────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
ANTHROPIC_API_KEY  = "YOUR_ANTHROPIC_API_KEY_HERE"
YOUR_TELEGRAM_ID   = 123456789          # your personal Telegram user ID (@userinfobot)
OPS_GROUP_ID       = -1000000000001     # EC OPS TEAM TELE chat ID
GOOGLE_SHEET_ID    = "YOUR_SHEET_ID_HERE"
GOOGLE_CREDS_FILE  = "google_creds.json"
TIMEZONE           = "Asia/Kolkata"

# ── Student roster ────────────────────────────────────────────
# Format: chat_id (int) → student info dict
# Get each group's chat ID by adding @getidsbot to the group temporarily
STUDENTS = {
    # -1001111111111: {
    #     "name": "Sahithi Gandham",
    #     "batch": "Foundation 4.14",
    #     "sheet_row": 2,        # their row number in Google Sheet
    # },
    # -1001111111112: {
    #     "name": "Pranjal Pareek",
    #     "batch": "Foundation 4.14",
    #     "sheet_row": 3,
    # },
    # Add all students here...
}

# ── Google Sheet columns (1-indexed, adjust to match your sheet) ──
COL = {
    "name":           1,   # A
    "cm_score":       2,   # B
    "mynb":           3,   # C  (P = present, A = absent)
    "gt_score":       4,   # D
    "quiz_score":     5,   # E
    "classification": 6,   # F  (GT Sunday classification status)
}

# ─────────────────────────────────────────────────────────────
# YOUR EXACT TONE — edit this to keep tuning
# ─────────────────────────────────────────────────────────────
SHRADDHA_PERSONA = """
You are Shraddha, an accountability mentor at Eyeconic by Dr Lalla.
You are messaging NEET PG / INICET / FMGE aspirant medical students one-on-one.

Follow this style EXACTLY:
- Professional and direct. Zero emojis. Zero exclamation marks unless truly needed.
- Messages are 1 to 3 lines maximum. Never write paragraphs.
- Use the student's first name naturally but not in every sentence.
- Use "we" often — you and the student are in this together.
- When they haven't replied or missed a submission, be firm but not harsh:
  Examples: "where are we?" / "why didn't we send the cm and mynb yesterday?" / "what's the update on today's tasks?"
- When they give a good update, acknowledge specifically and push forward:
  Example: "okay that's great, make sure we solve mixed bag cm everyday and share the images of the score."
- When silent for days, escalate slightly:
  Example: "a very crucial part of this journey is the communication between us and you, make sure none of us ruptures that."
- For study doubts: answer clearly and practically like a senior who knows the syllabus well.
- Never say "as an AI", never reveal you are a bot, never use generic praise like "great job" or "keep it up".
- Never use bullet points or lists. Always plain natural sentences.
- Never be generic. Be specific to what they said or didn't do.
"""

# ─────────────────────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────────────────────
STATE_FILE = Path("bot_state.json")

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {
        "last_message":       {},   # str(chat_id) → ISO timestamp
        "last_inactive_ping": {},   # str(chat_id) → ISO timestamp
        "daily":              {},   # str(chat_id) → {cm, mynb, gt, quiz, classification, date}
        "pending_forward":    {},   # str(message_id) → {text, chat_ids}
    }

def save_state(s: dict):
    STATE_FILE.write_text(json.dumps(s, indent=2, default=str))

state = load_state()

def today_str() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d")

def weekday() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("%A")

def get_daily(chat_id) -> dict:
    key = str(chat_id)
    td  = today_str()
    if state["daily"].get(key, {}).get("date") != td:
        state["daily"][key] = {
            "cm": False, "cm_value": "",
            "mynb": False,
            "gt": False, "gt_value": "",
            "quiz": False, "quiz_value": "",
            "classification": False,
            "date": td,
        }
    return state["daily"][key]

# ─────────────────────────────────────────────────────────────
# GOOGLE SHEETS
# ─────────────────────────────────────────────────────────────
def get_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(GOOGLE_CREDS_FILE, scopes=scopes)
    gc    = gspread.authorize(creds)
    return gc.open_by_key(GOOGLE_SHEET_ID).sheet1

def sheet_update(row: int, col: int, value):
    try:
        sheet = get_sheet()
        sheet.update_cell(row, col, value)
        log.info(f"Sheet updated: row {row}, col {col} = {value}")
    except Exception as e:
        log.error(f"Sheet error: {e}")

# ─────────────────────────────────────────────────────────────
# CLAUDE
# ─────────────────────────────────────────────────────────────
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

def claude_reply(prompt: str) -> str:
    resp = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        system=SHRADDHA_PERSONA,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()

def claude_vision_score(image_bytes: bytes, caption: str = "") -> dict:
    b64 = base64.standard_b64encode(image_bytes).decode()
    prompt = f"""
Look at this screenshot from a medical student preparing for NEET PG / INICET.
Caption they wrote: "{caption}"

Identify:
1. Type: "cm" (custom module), "gt" (grand test), "quiz" (weekly quiz), "mynb" (notebook photo), "unknown"
2. Score shown — exact text like "18/20" or "87%"
3. If correct/total format, calculate percentage = correct/total * 100, round to 1 decimal

Reply ONLY in this JSON, no other text:
{{"score_type": "cm|gt|quiz|mynb|unknown", "value": "raw score", "percentage": 0.0}}

For notebook photos: set value="present", percentage=100.
For unclear screenshots: score_type="unknown".
"""
    resp = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=100,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    try:
        raw = re.sub(r"```json|```", "", resp.content[0].text).strip()
        return json.loads(raw)
    except Exception as e:
        log.error(f"Vision parse error: {e} | raw: {resp.content[0].text}")
        return {"score_type": "unknown", "value": "", "percentage": 0}

def validate_gt_classification(text: str) -> dict:
    """Check that the GT classification contains all required elements."""
    tl = text.lower()
    checks = {
        "3 positives":             bool(re.search(r"positive", tl)),
        "3 negatives":             bool(re.search(r"negative", tl)),
        "classification errors":   bool(re.search(r"classification error", tl)),
        "recall errors":           bool(re.search(r"recall error", tl)),
        "silly mistakes":          bool(re.search(r"silly mistake", tl)),
        "misread questions":       bool(re.search(r"misread", tl)),
    }
    missing = [k for k, v in checks.items() if not v]
    return {"valid": len(missing) == 0, "missing": missing}

def days_since(chat_id) -> int:
    last = state["last_message"].get(str(chat_id))
    if not last:
        return 999
    last_dt = datetime.fromisoformat(last)
    now     = datetime.now(ZoneInfo(TIMEZONE))
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=ZoneInfo(TIMEZONE))
    return max(0, (now - last_dt).days)

# ─────────────────────────────────────────────────────────────
# SCHEDULED CHECK-INS
# ─────────────────────────────────────────────────────────────
async def send_checkins(bot: Bot, window: str):
    day = weekday()
    for chat_id, info in STUDENTS.items():
        name    = info["name"].split()[0]
        silent  = days_since(chat_id)
        daily   = get_daily(chat_id)
        cm_done = daily.get("cm", False)
        nb_done = daily.get("mynb", False)

        if window == "morning":
            prompt = f"""Student: {name} | Batch: {info['batch']} | Day: {day}
Days silent before today: {silent}
{"Today is Friday — quiz day." if day == "Friday" else ""}
{"Today is Sunday — GT day, classification required." if day == "Sunday" else ""}

Write a morning check-in. Ask {name} to share today's task plan.
If silent > 2 days, be firm about lack of communication first.
If Friday: remind about quiz. If Sunday: remind about GT and classification requirement."""

        elif window == "afternoon":
            prompt = f"""Student: {name} | Batch: {info['batch']} | Day: {day}
CM submitted today: {cm_done} | Notebook submitted: {nb_done}
Days silent: {silent}

Write a short afternoon check-in asking for a progress update on today's tasks.
If cm or mynb not yet submitted, specifically ask about those."""

        else:  # evening
            prompt = f"""Student: {name} | Batch: {info['batch']} | Day: {day}
CM submitted today: {cm_done} | Notebook submitted: {nb_done}
{"Quiz score expected today." if day == "Friday" else ""}
{"GT score and classification expected today." if day == "Sunday" else ""}
Days silent: {silent}

Write an evening check-in asking what was accomplished. If cm or mynb still missing, be firm.
If Friday/Sunday, ask specifically about those submissions if not done."""

        try:
            await bot.send_message(chat_id=chat_id, text=claude_reply(prompt))
            log.info(f"Check-in ({window}) → {name}")
            await asyncio.sleep(0.8)
        except Exception as e:
            log.error(f"Check-in failed for chat {chat_id}: {e}")

# ─────────────────────────────────────────────────────────────
# 11PM DAILY AUDIT
# ─────────────────────────────────────────────────────────────
async def daily_audit(bot: Bot):
    day     = weekday()
    missing = []

    for chat_id, info in STUDENTS.items():
        name  = info["name"]
        row   = info["sheet_row"]
        daily = get_daily(chat_id)

        # CM score
        if daily["cm"]:
            sheet_update(row, COL["cm_score"], daily["cm_value"] or "P")
        else:
            sheet_update(row, COL["cm_score"], "A")
            missing.append(f"{name} — CM score")

        # Notebook
        if daily["mynb"]:
            sheet_update(row, COL["mynb"], "P")
        else:
            sheet_update(row, COL["mynb"], "A")
            missing.append(f"{name} — notebook (mynb)")

        # Friday: quiz
        if day == "Friday":
            if daily["quiz"]:
                sheet_update(row, COL["quiz_score"], daily["quiz_value"] or "P")
            else:
                sheet_update(row, COL["quiz_score"], "A")
                missing.append(f"{name} — quiz score")

        # Sunday: GT + classification
        if day == "Sunday":
            if daily["gt"]:
                sheet_update(row, COL["gt_score"], daily["gt_value"] or "P")
            else:
                sheet_update(row, COL["gt_score"], "A")
                missing.append(f"{name} — GT score")
            if daily["classification"]:
                sheet_update(row, COL["classification"], "P")
            else:
                sheet_update(row, COL["classification"], "A")
                missing.append(f"{name} — GT classification")

    # Alert Shraddha
    if missing:
        header = f"11pm Audit — {today_str()} — {len(missing)} missing:\n\n"
        body   = "\n".join(f"- {m}" for m in missing)
        # Split into chunks if too long
        full = header + body
        for i in range(0, len(full), 3800):
            await bot.send_message(chat_id=YOUR_TELEGRAM_ID, text=full[i:i+3800])
    else:
        await bot.send_message(chat_id=YOUR_TELEGRAM_ID,
                               text=f"11pm Audit — {today_str()} — All students submitted CM and notebook.")
    save_state(state)

# ─────────────────────────────────────────────────────────────
# WEEKLY INACTIVE PING
# ─────────────────────────────────────────────────────────────
async def ping_inactive(bot: Bot):
    now = datetime.now(ZoneInfo(TIMEZONE))
    for chat_id, info in STUDENTS.items():
        name      = info["name"].split()[0]
        silent    = days_since(chat_id)
        last_ping = state["last_inactive_ping"].get(str(chat_id), "2000-01-01")
        last_ping_dt = datetime.fromisoformat(last_ping).replace(tzinfo=ZoneInfo(TIMEZONE))

        if silent >= 7 and (now - last_ping_dt).days >= 7:
            prompt = f"""Student: {name} | Batch: {info['batch']}
Days without any message: {silent}

Write a firm but motivating message to {name} about the importance of daily communication and consistency.
Address the silence directly — {silent} days is significant. Be direct but do not guilt trip excessively.
Reference that this communication is a crucial part of their preparation journey."""
            try:
                await bot.send_message(chat_id=chat_id, text=claude_reply(prompt))
                state["last_inactive_ping"][str(chat_id)] = now.isoformat()
                await asyncio.sleep(0.8)
            except Exception as e:
                log.error(f"Inactive ping failed for {chat_id}: {e}")
    save_state(state)

# ─────────────────────────────────────────────────────────────
# OPS GROUP HANDLER
# ─────────────────────────────────────────────────────────────
async def handle_ops_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg  = update.message
    text = msg.text or msg.caption or ""
    if not text or len(text) < 20:
        return

    fwd_id = str(msg.message_id)
    state["pending_forward"][fwd_id] = {"text": text, "chat_ids": [str(c) for c in STUDENTS]}
    save_state(state)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"Send to all {len(STUDENTS)} chats", callback_data=f"fwd_yes_{fwd_id}"),
        InlineKeyboardButton("Ignore", callback_data=f"fwd_no_{fwd_id}"),
    ]])
    preview = text[:400] + ("..." if len(text) > 400 else "")
    await context.bot.send_message(
        chat_id=YOUR_TELEGRAM_ID,
        text=f"New OPS message. Forward to all student chats?\n\n{preview}",
        reply_markup=keyboard,
    )

async def handle_forward_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data.startswith("fwd_yes_"):
        fwd_id  = data[8:]
        pending = state["pending_forward"].get(fwd_id)
        if not pending:
            await query.edit_message_text("Expired or not found.")
            return
        sent = 0
        for cid in pending["chat_ids"]:
            try:
                await context.bot.send_message(chat_id=int(cid), text=pending["text"])
                sent += 1
                await asyncio.sleep(0.5)
            except Exception as e:
                log.error(f"Forward failed to {cid}: {e}")
        del state["pending_forward"][fwd_id]
        save_state(state)
        await query.edit_message_text(f"Sent to {sent}/{len(pending['chat_ids'])} student chats.")

    elif data.startswith("fwd_no_"):
        fwd_id = data[7:]
        state["pending_forward"].pop(fwd_id, None)
        save_state(state)
        await query.edit_message_text("Not forwarded.")

# ─────────────────────────────────────────────────────────────
# STUDENT CHAT HANDLER
# ─────────────────────────────────────────────────────────────
async def handle_student_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    chat_id = msg.chat_id
    info    = STUDENTS.get(chat_id)
    if not info:
        return

    name  = info["name"].split()[0]
    text  = msg.text or msg.caption or ""
    now   = datetime.now(ZoneInfo(TIMEZONE)).isoformat()
    daily = get_daily(chat_id)
    day   = weekday()

    state["last_message"][str(chat_id)] = now
    save_state(state)

    # ── PHOTO ────────────────────────────────────────────────
    if msg.photo:
        photo_file = await context.bot.get_file(msg.photo[-1].file_id)
        img_bytes  = bytes(await photo_file.download_as_bytearray())
        result     = claude_vision_score(img_bytes, caption=text)
        stype      = result.get("score_type", "unknown")
        value      = result.get("value", "")
        pct        = result.get("percentage", 0)
        row        = info["sheet_row"]
        pct_str    = f"{pct}%" if pct else value

        if stype == "cm":
            daily["cm"]       = True
            daily["cm_value"] = pct_str
            save_state(state)
            sheet_update(row, COL["cm_score"], pct_str)
            extra = " Make sure the notebook is sent too." if not daily["mynb"] else ""
            prompt = f"Student {name} just submitted their CM score of {pct_str}. Acknowledge it briefly and push forward.{extra}"
            await msg.reply_text(claude_reply(prompt))

        elif stype == "mynb":
            daily["mynb"] = True
            save_state(state)
            sheet_update(row, COL["mynb"], "P")
            both_done = daily["cm"]
            prompt = f"Student {name} just sent their notebook. {'Both CM and notebook are done for today.' if both_done else 'CM score is still pending for today.'} Respond appropriately."
            await msg.reply_text(claude_reply(prompt))

        elif stype == "gt" and day == "Sunday":
            daily["gt"]       = True
            daily["gt_value"] = pct_str
            save_state(state)
            sheet_update(row, COL["gt_score"], pct_str)
            if not daily["classification"]:
                await msg.reply_text(
                    f"GT score noted, {name}. Send the complete classification now — 3 positives, 3 negatives, number of classification errors, recall errors, silly mistakes, and misread questions."
                )
            else:
                prompt = f"Student {name} sent GT score {pct_str} and already submitted classification. Acknowledge and motivate for the week."
                await msg.reply_text(claude_reply(prompt))

        elif stype == "quiz" and day == "Friday":
            daily["quiz"]       = True
            daily["quiz_value"] = pct_str
            save_state(state)
            sheet_update(row, COL["quiz_score"], pct_str)
            score_context = "above 80%" if pct >= 80 else ("below 60%, needs error analysis" if pct < 60 else "decent, room to improve")
            prompt = f"Student {name} sent quiz score {pct_str} ({score_context}). Respond as their accountability partner — be specific."
            await msg.reply_text(claude_reply(prompt))

        else:
            await context.bot.send_message(
                chat_id=YOUR_TELEGRAM_ID,
                text=f"Unrecognised photo from {info['name']}. Score type detected: {stype}. Please check manually.",
            )
        return

    if not text:
        return

    # ── GT CLASSIFICATION (Sunday long text) ─────────────────
    if day == "Sunday" and len(text) > 60:
        check = validate_gt_classification(text)
        if not check["valid"]:
            missing_str = ", ".join(check["missing"])
            await msg.reply_text(
                f"The classification is incomplete, {name}. Missing: {missing_str}. Resend the complete one."
            )
            return
        daily["classification"] = True
        save_state(state)
        sheet_update(info["sheet_row"], COL["classification"], "P")
        prompt = f"Student {name} submitted their complete GT classification on Sunday. Acknowledge briefly and motivate for the week ahead."
        await msg.reply_text(claude_reply(prompt))
        return

    # ── PLANNER REQUEST ──────────────────────────────────────
    if any(kw in text.lower() for kw in ["planner", "planner update", "reschedule", "change my plan", "update my plan"]):
        await context.bot.send_message(
            chat_id=YOUR_TELEGRAM_ID,
            text=f"PLANNER UPDATE — {info['name']}:\n\"{text}\"",
        )
        await msg.reply_text(
            f"Noted, {name}. I will look into this and update your planner."
        )
        return

    # ── GENERAL REPLY ────────────────────────────────────────
    silent  = days_since(chat_id)
    cm_done = daily.get("cm", False)
    nb_done = daily.get("mynb", False)

    prompt = f"""Student: {name} | Batch: {info['batch']} | Day: {day}
Their message: "{text}"
Days silent before this message: {max(0, silent - 1)}
CM submitted today: {cm_done} | Notebook submitted today: {nb_done}

Reply as their accountability partner. Be specific to what they said.
If it's a progress update: acknowledge specifically, push forward, ask a follow-up.
If it's a doubt about studies: answer clearly and practically.
If they just returned after being silent: address the gap directly, then help them move forward.
If CM or mynb still pending, remind them without being repetitive."""

    await msg.reply_text(claude_reply(prompt))

# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
async def main():
    app       = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    bot       = app.bot
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    # Check-ins: 3 windows
    scheduler.add_job(send_checkins, "cron", hour=7,  minute=30, args=[bot, "morning"])
    scheduler.add_job(send_checkins, "cron", hour=16, minute=30, args=[bot, "afternoon"])
    scheduler.add_job(send_checkins, "cron", hour=20, minute=0,  args=[bot, "evening"])

    # 11pm audit
    scheduler.add_job(daily_audit, "cron", hour=23, minute=0, args=[bot])

    # Weekly inactive ping every Monday 8am
    scheduler.add_job(ping_inactive, "cron", day_of_week="mon", hour=8, args=[bot])

    scheduler.start()

    student_ids = list(STUDENTS.keys())
    if student_ids:
        app.add_handler(MessageHandler(
            filters.Chat(student_ids) & (filters.TEXT | filters.PHOTO | filters.CAPTION),
            handle_student_message,
        ))

    app.add_handler(MessageHandler(
        filters.Chat(OPS_GROUP_ID) & (filters.TEXT | filters.CAPTION),
        handle_ops_message,
    ))

    app.add_handler(CallbackQueryHandler(handle_forward_callback, pattern=r"^fwd_"))

    log.info("Eyeconic Mentor Bot is live.")
    await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())