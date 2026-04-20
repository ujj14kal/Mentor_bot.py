"""
AI Engine — Groq API wrapper for text generation and vision/OCR.
Uses the free tier of Groq with Llama models.

Rate limit strategy:
- Groq free tier: ~30 RPM but only ~6000 tokens/min for Llama 3.3 70B
- Token cost per call: classify ~350 tokens, generate ~950 tokens
- Full reply (classify + generate) = ~1300 tokens
- 6000 tokens/min ÷ 1300 = 4.6 students/min → 13s minimum interval
- _MIN_INTERVAL set to 15s for safety buffer
- 40 students × 15s = ~10 minutes max queue drain (well within 1 hour SLA)
"""

import re
import json
import base64
import logging
import asyncio
import time
from typing import Optional
from groq import AsyncGroq

from config import GROQ_API_KEY, GROQ_TEXT_MODEL, GROQ_VISION_MODEL, SHRADDHA_PERSONA

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# CLIENT INIT
# ─────────────────────────────────────────────────────────────
_client = AsyncGroq(api_key=GROQ_API_KEY)

# ─────────────────────────────────────────────────────────────
# GLOBAL THROTTLE
# 15s between calls = 4/min = safe under 6000 tokens/min limit
# All 40 students processed in ~10 minutes, well within 1 hour SLA
# ─────────────────────────────────────────────────────────────
_throttle_lock: Optional[asyncio.Lock] = None
_last_call_time: float = 0.0
_MIN_INTERVAL: float = 15.0  # seconds between API calls


async def _throttled_call(func, max_retries: int = 5):
    """
    Serialize ALL Groq calls through a single lock with a minimum gap,
    then retry with exponential backoff on rate limit errors.
    Prevents burst firing during scheduled check-ins with 40 students.
    """
    global _last_call_time, _throttle_lock

    if _throttle_lock is None:
        _throttle_lock = asyncio.Lock()

    async with _throttle_lock:
        # Enforce minimum gap between calls
        now = time.monotonic()
        gap = _MIN_INTERVAL - (now - _last_call_time)
        if gap > 0:
            await asyncio.sleep(gap)

        for attempt in range(max_retries):
            try:
                result = await func()
                _last_call_time = time.monotonic()
                return result
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate_limit" in error_str.lower():
                    # Exponential backoff: 15s, 30s, 60s, 120s, 240s
                    wait = _MIN_INTERVAL * (2 ** attempt)
                    log.warning(
                        f"Groq rate limit hit, waiting {wait:.0f}s "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(wait)
                    _last_call_time = time.monotonic()
                else:
                    log.error(f"Groq API error (non-rate-limit): {e}")
                    raise

        log.error("Groq API: max retries exhausted")
        return None


# ─────────────────────────────────────────────────────────────
# TEXT GENERATION (message composition)
# ─────────────────────────────────────────────────────────────
async def generate_message(prompt: str, max_tokens: int = 250) -> str:
    """
    Generate a message as Shraddha using the persona prompt.
    Returns the generated text or a fallback empty string on failure.
    """
    async def _call():
        resp = await _client.chat.completions.create(
            model=GROQ_TEXT_MODEL,
            max_tokens=max_tokens,
            temperature=0.7,
            messages=[
                {"role": "system", "content": SHRADDHA_PERSONA},
                {"role": "user", "content": prompt},
            ],
        )
        return resp.choices[0].message.content.strip()

    result = await _throttled_call(_call)
    if result is None:
        log.error("generate_message: failed after retries")
        return ""

    result = _strip_emojis(result)
    return result


# ─────────────────────────────────────────────────────────────
# MESSAGE CLASSIFICATION
# ─────────────────────────────────────────────────────────────
async def classify_message(text: str) -> dict:
    """
    Classify a student message to determine its type and whether it needs a reply.
    Returns: {"type": str, "needs_reply": bool, "is_planner": bool,
              "is_subject_change": bool, "summary": str}
    """
    prompt = f'''Analyze this message from a medical student in a Telegram group chat.
The student is preparing for NEET PG and sends updates about their study work.

Message: "{text}"

Classify it and respond ONLY in this exact JSON format, no other text:
{{"type": "work_update|doubt|planner_request|subject_change|greeting|acknowledgment|personal|irrelevant|question",
 "needs_reply": true or false,
 "is_planner": true or false,
 "is_subject_change": true or false,
 "summary": "one line summary of what the student said"}}

Rules:
- "work_update": they shared progress, scores, or completion status. Also includes them telling you their "plan for today" (e.g., "I will do 50 MCQs today"). This is NOT a planner_request.
- "doubt": they asked a study-related question
- "planner_request": specifically requests a structural change to their long-term study schedule, changing subject dates, or modifying their overall roadmap.
- "subject_change": specifically requesting to swap subjects or skip a subject in the roadmap.
- "greeting": just hi/hello/good morning type messages — needs_reply=true but keep reply brief
- "acknowledgment": ok/noted/sure/done type — needs_reply=false
- "personal": personal issues, health, leave — needs_reply=true
- "irrelevant": random/off-topic — needs_reply=false
- "question": general questions directed at the mentor

"is_planner" Rule:
Only set "is_planner": true if the student is asking the mentor to CHANGE their official schedule/dates.
If they are just sharing their plan for the day, set "is_planner": false.
'''

    async def _call():
        resp = await _client.chat.completions.create(
            model=GROQ_TEXT_MODEL,
            max_tokens=150,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"```json|```", "", raw).strip()
        return json.loads(raw)

    try:
        result = await _throttled_call(_call)
        if result is None:
            return {"type": "unknown", "needs_reply": True, "is_planner": False,
                    "is_subject_change": False, "summary": text[:100]}
        return result
    except (json.JSONDecodeError, Exception) as e:
        log.error(f"classify_message parse error: {e}")
        return {"type": "unknown", "needs_reply": True, "is_planner": False,
                "is_subject_change": False, "summary": text[:100]}


# ─────────────────────────────────────────────────────────────
# OPS MESSAGE CLASSIFICATION
# ─────────────────────────────────────────────────────────────
async def classify_ops_message(text: str) -> dict:
    """
    Classify a message from the Eyeconic OPS Tele group.
    Returns: {"type": str, "for_all_students": bool,
              "target_students": list, "is_quiz_link": bool,
              "is_gt_message": bool, "summary": str}
    """
    prompt = f'''Analyze this message from the Eyeconic OPS Tele group (admin/support group).
This group is used by admins to send announcements, quiz links, GT links, and operational updates.

Message: "{text}"

Classify it and respond ONLY in this exact JSON format, no other text:
{{"type": "quiz_link|gt_message|announcement|schedule_change|student_specific|operational|irrelevant",
 "for_all_students": true or false,
 "target_students": [],
 "is_quiz_link": true or false,
 "is_gt_message": true or false,
 "needs_forwarding": true or false,
 "summary": "one line summary"}}

Rules:
- "quiz_link": contains a quiz link or quiz-related announcement (usually Thursday night)
- "gt_message": grand test related message (usually Sunday)
- "announcement": general announcement for all students
- "schedule_change": changes to dates, subjects, order
- "student_specific": mentions specific student names
- "operational": internal ops discussion, not for students
- "irrelevant": casual chat, not actionable
- for_all_students: true if this should be shared with every student
- target_students: list of student names if message is for specific students only
- needs_forwarding: true if this message content should be sent to student chats
'''

    async def _call():
        resp = await _client.chat.completions.create(
            model=GROQ_TEXT_MODEL,
            max_tokens=200,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"```json|```", "", raw).strip()
        return json.loads(raw)

    try:
        result = await _throttled_call(_call)
        if result is None:
            return {"type": "unknown", "for_all_students": False,
                    "target_students": [], "is_quiz_link": False,
                    "is_gt_message": False, "needs_forwarding": False,
                    "summary": text[:100]}
        return result
    except (json.JSONDecodeError, Exception) as e:
        log.error(f"classify_ops_message parse error: {e}")
        return {"type": "unknown", "for_all_students": False,
                "target_students": [], "is_quiz_link": False,
                "is_gt_message": False, "needs_forwarding": False,
                "summary": text[:100]}


# ─────────────────────────────────────────────────────────────
# VISION / OCR (score extraction from screenshots)
# ─────────────────────────────────────────────────────────────
async def extract_score_from_image(image_bytes: bytes, caption: str = "") -> dict:
    """
    Use Groq Vision to analyze a screenshot and extract score information.
    Returns: {"score_type": str, "value": str, "percentage": float}
    """
    b64 = base64.standard_b64encode(image_bytes).decode()

    prompt = f'''Look at this screenshot from a medical student preparing for NEET PG.
Caption they wrote: "{caption}"

Identify:
1. Type: "cm" (custom module score), "gt" (grand test score), "quiz" (weekly quiz score), "mynb" (notebook/handwritten notes photo), "unknown"
2. Score shown — exact text like "18/20" or "87%"
3. If correct/total format, calculate percentage = correct/total * 100, round to 1 decimal

Reply ONLY in this JSON, no other text:
{{"score_type": "cm|gt|quiz|mynb|unknown", "value": "raw score text", "percentage": 0.0}}

For notebook photos (handwritten notes, revision material): set value="present", percentage=100.
For unclear or unrelated screenshots: score_type="unknown".
'''

    async def _call():
        resp = await _client.chat.completions.create(
            model=GROQ_VISION_MODEL,
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        raw = re.sub(r"```json|```", "", resp.choices[0].message.content).strip()
        return json.loads(raw)

    try:
        result = await _throttled_call(_call)
        if result is None:
            return {"score_type": "unknown", "value": "", "percentage": 0.0}
        return result
    except (json.JSONDecodeError, Exception) as e:
        log.error(f"extract_score_from_image parse error: {e}")
        return {"score_type": "unknown", "value": "", "percentage": 0.0}


# ─────────────────────────────────────────────────────────────
# GT CLASSIFICATION VALIDATOR
# ─────────────────────────────────────────────────────────────
def validate_gt_classification(text: str) -> dict:
    """Check that GT classification text contains all required elements."""
    tl = text.lower()
    checks = {
        "3 positives":           bool(re.search(r"positive", tl)),
        "3 negatives":           bool(re.search(r"negative", tl)),
        "classification errors": bool(re.search(r"classification\s*error", tl)),
        "recall errors":         bool(re.search(r"recall\s*error", tl)),
        "silly mistakes":        bool(re.search(r"silly\s*mistake", tl)),
        "misread questions":     bool(re.search(r"misread", tl)),
    }
    missing = [k for k, v in checks.items() if not v]
    return {"valid": len(missing) == 0, "missing": missing}


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
def _strip_emojis(text: str) -> str:
    """Remove any emoji characters from text as a safety net."""
    emoji_pattern = re.compile(
        "["
        "\\U0001F600-\\U0001F64F"
        "\\U0001F300-\\U0001F5FF"
        "\\U0001F680-\\U0001F6FF"
        "\\U0001F1E0-\\U0001F1FF"
        "\\U00002702-\\U000027B0"
        "\\U000024C2-\\U0001F251"
        "\\U0001f926-\\U0001f937"
        "\\U00010000-\\U0010ffff"
        "\\u2640-\\u2642"
        "\\u2600-\\u2B55"
        "\\u200d"
        "\\u23cf"
        "\\u23e9"
        "\\u231a"
        "\\ufe0f"
        "\\u3030"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text).strip()
