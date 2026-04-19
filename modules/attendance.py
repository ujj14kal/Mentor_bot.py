"""
Attendance Manager — Updates daily attendance on the UJJWAL tab
of the DAILY ATTENDANCE SHEET-2026.

Sheet structure:
- Tab: "UJJWAL" (Shraddha's students)
- Row 1: Dates (merged cells like "6-Sep-2025")
- Row 2: Time slots (9:00 AM, 5:00 PM, 9:00 PM) per date
- Row 3: "Mail" / "STUDENTS" / "BATCH" headers
- Rows 4+: Students with checkboxes for each time slot

Attendance is marked with checkboxes (TRUE/FALSE).
The system marks the 9:00 PM slot for students who submitted work that day.
"""

from __future__ import annotations


import logging
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

from config import GOOGLE_CREDS_FILE, TIMEZONE
from modules.student_tracker import today_str

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# ATTENDANCE SHEET CONFIG
# ─────────────────────────────────────────────────────────────
ATTENDANCE_SHEET_ID = "1k_-YTSHEl9YgvvVRgvQVUg_47Kq98IU1xBgA6_hKJQA"
ATTENDANCE_TAB = "UJJWAL"  # Shraddha/Ujjwal's tab

# Time slots per date (3 columns per date)
SLOTS_PER_DATE = 3   # 9:00 AM, 5:00 PM, 9:00 PM
FIRST_DATE_COL = 5   # Column E is where first date block starts (adjust after verification)
STUDENT_NAME_COL = 2  # Column B has student names
HEADER_DATE_ROW = 1   # Row 1 has dates
HEADER_SLOT_ROW = 3   # Row 3 has time slots (9:00 AM, 5:00 PM, 9:00 PM)
DATA_START_ROW = 4     # Student data starts at row 4


# ─────────────────────────────────────────────────────────────
# AUTH (shared with sheets_manager)
# ─────────────────────────────────────────────────────────────
_gc = None


def _get_client() -> gspread.Client:
    """Get or create authenticated gspread client."""
    global _gc
    if _gc is None:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(GOOGLE_CREDS_FILE, scopes=scopes)
        _gc = gspread.authorize(creds)
        log.info("Attendance sheets client authenticated")
    return _gc


def _get_worksheet():
    """Open the UJJWAL attendance worksheet."""
    try:
        gc = _get_client()
        spreadsheet = gc.open_by_key(ATTENDANCE_SHEET_ID)
        return spreadsheet.worksheet(ATTENDANCE_TAB)
    except Exception as e:
        log.error(f"Error opening attendance sheet: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
def _find_student_row(ws, student_name: str) -> int | None:
    """Find a student's row by name in column B."""
    try:
        col_vals = ws.col_values(STUDENT_NAME_COL)
        for i, val in enumerate(col_vals):
            if val and val.strip().upper() == student_name.strip().upper():
                return i + 1
        # Partial match
        first_name = student_name.strip().split()[0].upper()
        for i, val in enumerate(col_vals):
            if val and val.strip().upper().startswith(first_name):
                return i + 1
        return None
    except Exception as e:
        log.error(f"Error finding student in attendance: {e}")
        return None


def _find_date_columns(ws, target_date: str) -> dict | None:
    """
    Find the 3 column numbers for a date (9:00 AM, 5:00 PM, 9:00 PM).
    Returns dict with 'morning', 'afternoon', 'evening' column numbers.
    """
    try:
        row1_vals = ws.row_values(HEADER_DATE_ROW)
        row3_vals = ws.row_values(HEADER_SLOT_ROW)

        target_dt = datetime.strptime(target_date, "%Y-%m-%d")

        date_formats = [
            "%d-%b-%Y", "%d-%b-%y", "%d-%B-%Y",
            "%d/%m/%Y", "%Y-%m-%d",
        ]

        # Find the starting column for this date
        date_start_col = None
        for col_idx, val in enumerate(row1_vals):
            if not val or col_idx < FIRST_DATE_COL - 1:
                continue

            val = val.strip()
            for fmt in date_formats:
                try:
                    parsed = datetime.strptime(val, fmt)
                    if parsed.year < 100:
                        parsed = parsed.replace(year=parsed.year + 2000)

                    if (parsed.day == target_dt.day and
                            parsed.month == target_dt.month and
                            parsed.year == target_dt.year):
                        date_start_col = col_idx + 1  # 1-indexed
                        break
                except (ValueError, TypeError):
                    continue
            if date_start_col:
                break

        if not date_start_col:
            log.warning(f"Date '{target_date}' not found in attendance header")
            return None

        # Map time slots from row 3
        slots = {}
        for offset in range(SLOTS_PER_DATE):
            col = date_start_col + offset
            if col - 1 < len(row3_vals):
                slot_label = row3_vals[col - 1].strip().upper()
                if "9:00 AM" in slot_label or "9" in slot_label and "AM" in slot_label:
                    slots["morning"] = col
                elif "5:00 PM" in slot_label or "5" in slot_label and "PM" in slot_label:
                    slots["afternoon"] = col
                elif "9:00 PM" in slot_label or "9" in slot_label and "PM" in slot_label:
                    slots["evening"] = col
                else:
                    # Fallback: assume order is morning, afternoon, evening
                    if offset == 0:
                        slots["morning"] = col
                    elif offset == 1:
                        slots["afternoon"] = col
                    else:
                        slots["evening"] = col

        return slots if slots else None

    except Exception as e:
        log.error(f"Error finding date columns in attendance: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# ATTENDANCE MARKING
# ─────────────────────────────────────────────────────────────
def mark_attendance(student_name: str, present: bool = True,
                    slot: str = "evening", date: str = None):
    """
    Mark a single student's attendance for a specific slot.
    slot: 'morning', 'afternoon', or 'evening'
    """
    date = date or today_str()
    ws = _get_worksheet()
    if not ws:
        return False

    row = _find_student_row(ws, student_name)
    if not row:
        log.warning(f"Student '{student_name}' not found in attendance sheet")
        return False

    date_cols = _find_date_columns(ws, date)
    if not date_cols:
        return False

    col = date_cols.get(slot)
    if not col:
        log.warning(f"Slot '{slot}' not found for date {date}")
        return False

    try:
        ws.update_cell(row, col, True if present else False)
        log.info(f"Attendance: {student_name} = {'P' if present else 'A'} ({slot}, {date})")
        return True
    except Exception as e:
        log.error(f"Error marking attendance for {student_name}: {e}")
        return False


def mark_all_attendance(student_statuses: dict, date: str = None):
    """
    Mark attendance for all students at once (11 PM audit).
    student_statuses: dict of {student_name: "P" or "A"}
    Marks the 9:00 PM (evening) slot for each student.
    """
    date = date or today_str()
    ws = _get_worksheet()
    if not ws:
        return

    date_cols = _find_date_columns(ws, date)
    if not date_cols:
        log.error(f"Could not find date columns for {date} in attendance sheet")
        return

    evening_col = date_cols.get("evening")
    if not evening_col:
        log.error("Evening slot column not found")
        return

    updates = []
    for name, status in student_statuses.items():
        row = _find_student_row(ws, name)
        if row:
            cell = gspread.utils.rowcol_to_a1(row, evening_col)
            updates.append({
                "range": cell,
                "values": [[True if status == "P" else False]],
            })

    if updates:
        try:
            ws.batch_update(updates, value_input_option="USER_ENTERED")
            log.info(f"Attendance batch updated: {len(updates)} students for {date}")
        except Exception as e:
            log.error(f"Batch attendance update failed: {e}")
