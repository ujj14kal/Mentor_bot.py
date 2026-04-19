"""
Google Sheets Manager — Handles centralized score sheet updates.

Sheet structure (single master spreadsheet, 3 tabs):
- "Quiz Score Sheet TG": A=Mail, B=Students, C=Batch, D=Quiz Count, E=Avg
  Then repeating per date: Quiz Subject, Total Score
- "CM Sheet": A=Mail, B=Students, C=Batch, D=CM Count, E=R2, F=MyNB
  Then repeating per date: Total Score, R2 Screenshot, Mynotebook (checkboxes)
- "GT SHEET": Similar structure

All students share one spreadsheet. Rows start at 4.
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
# SHEET IDs (centralized — not per-student)
# ─────────────────────────────────────────────────────────────
SCORE_SHEET_ID = "1J-AynOeTxSIoNgyAkwa0zWo41FjJC-SjBW1DGLqegRg"

CM_TAB = "CM Sheet"
QUIZ_TAB = "Quiz Score Sheet TG "  # trailing space in actual sheet name
GT_TAB = "GT SHEET"

# Column offsets in CM Sheet (per-date block: Total Score, R2 Screenshot, Mynotebook)
CM_BLOCK_SIZE = 3     # each date has 3 columns
CM_FIRST_DATE_COL = 7  # column G is where first date block starts (adjust after verification)

# Column offsets in Quiz Sheet (per-date block: Quiz Subject, Total Score)
QUIZ_BLOCK_SIZE = 2
QUIZ_FIRST_DATE_COL = 6  # column F is where first date block starts

# Column offsets in GT Sheet
GT_BLOCK_SIZE = 2
GT_FIRST_DATE_COL = 6

# ─────────────────────────────────────────────────────────────
# AUTH
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
        log.info("Google Sheets client authenticated")
    return _gc


def _get_worksheet(sheet_id: str, worksheet_name: str):
    """Open a specific worksheet in a spreadsheet."""
    try:
        gc = _get_client()
        spreadsheet = gc.open_by_key(sheet_id)
        return spreadsheet.worksheet(worksheet_name)
    except gspread.exceptions.SpreadsheetNotFound:
        log.error(f"Spreadsheet not found: {sheet_id}")
        return None
    except gspread.exceptions.WorksheetNotFound:
        log.error(f"Worksheet '{worksheet_name}' not found in {sheet_id}")
        return None
    except Exception as e:
        log.error(f"Error opening sheet {sheet_id}/{worksheet_name}: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
def _find_student_row(ws, student_name: str, name_col: int = 2) -> int | None:
    """Find a student's row number by name (column B). Case-insensitive."""
    try:
        col_vals = ws.col_values(name_col)
        for i, val in enumerate(col_vals):
            if val and val.strip().upper() == student_name.strip().upper():
                return i + 1  # 1-indexed
        # Try partial match (first name)
        first_name = student_name.strip().split()[0].upper()
        for i, val in enumerate(col_vals):
            if val and val.strip().upper().startswith(first_name):
                return i + 1
        log.warning(f"Student '{student_name}' not found in sheet")
        return None
    except Exception as e:
        log.error(f"Error finding student row: {e}")
        return None


def _find_date_column(ws, target_date: str, date_row: int = 1,
                       first_col: int = 6) -> int | None:
    """
    Find the column number for a specific date in the header row.
    Dates in the sheet are formatted like '6-Feb-26' or 'DD-Mon-YYYY'.
    """
    try:
        row_vals = ws.row_values(date_row)

        # Parse target date to compare
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")

        # Common date formats in Google Sheets
        date_formats = [
            "%d-%b-%Y",    # 6-Feb-2026
            "%d-%b-%y",     # 6-Feb-26
            "%d-%B-%Y",     # 6-February-2026
            "%d/%m/%Y",     # 06/02/2026
            "%Y-%m-%d",     # 2026-02-06
            "%d-%b",        # 6-Feb
        ]

        for col_idx, val in enumerate(row_vals):
            if not val or col_idx < first_col - 1:
                continue

            val = val.strip()
            for fmt in date_formats:
                try:
                    parsed = datetime.strptime(val, fmt)
                    # Handle 2-digit year or missing year
                    if parsed.year < 100:
                        parsed = parsed.replace(year=parsed.year + 2000)
                    if fmt == "%d-%b":
                        parsed = parsed.replace(year=target_dt.year)

                    if (parsed.day == target_dt.day and
                            parsed.month == target_dt.month and
                            parsed.year == target_dt.year):
                        return col_idx + 1  # 1-indexed
                except (ValueError, TypeError):
                    continue

        log.warning(f"Date '{target_date}' not found in sheet header row {date_row}")
        return None
    except Exception as e:
        log.error(f"Error finding date column: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# CM SHEET UPDATES
# ─────────────────────────────────────────────────────────────
def update_cm_score(student_name: str, cm_score: str, mynb: bool = False,
                    date: str = None):
    """
    Update a student's CM score and MyNotebook status on the CM Sheet.
    - Total Score column = cm_score
    - Mynotebook column = checkbox (TRUE/FALSE)
    """
    date = date or today_str()
    ws = _get_worksheet(SCORE_SHEET_ID, CM_TAB)
    if not ws:
        return False

    row = _find_student_row(ws, student_name)
    if not row:
        return False

    # Find the date column (row 1 has dates, row 2 has sub-headers)
    date_col = _find_date_column(ws, date, date_row=1, first_col=CM_FIRST_DATE_COL)
    if not date_col:
        log.warning(f"Date column not found for {date} on CM Sheet")
        return False

    try:
        updates = []

        # Total Score is the first column in the date block
        score_col = date_col
        updates.append({
            "range": gspread.utils.rowcol_to_a1(row, score_col),
            "values": [[cm_score]],
        })

        # Mynotebook is the 3rd column in the date block (Total Score, R2, MyNB)
        mynb_col = date_col + 2
        updates.append({
            "range": gspread.utils.rowcol_to_a1(row, mynb_col),
            "values": [[True if mynb else False]],
        })

        ws.batch_update(updates, value_input_option="USER_ENTERED")
        log.info(f"CM Sheet updated: {student_name}, date={date}, score={cm_score}, mynb={mynb}")
        return True

    except Exception as e:
        log.error(f"Error updating CM sheet for {student_name}: {e}")
        return False


def update_mynb_only(student_name: str, date: str = None):
    """Mark MyNotebook as submitted (checkbox = TRUE) without changing score."""
    date = date or today_str()
    ws = _get_worksheet(SCORE_SHEET_ID, CM_TAB)
    if not ws:
        return False

    row = _find_student_row(ws, student_name)
    if not row:
        return False

    date_col = _find_date_column(ws, date, date_row=1, first_col=CM_FIRST_DATE_COL)
    if not date_col:
        return False

    try:
        mynb_col = date_col + 2  # 3rd column in block
        ws.update_cell(row, mynb_col, True)
        log.info(f"MyNB marked for {student_name} on {date}")
        return True
    except Exception as e:
        log.error(f"Error marking mynb for {student_name}: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# QUIZ SHEET UPDATES
# ─────────────────────────────────────────────────────────────
def update_quiz_score(student_name: str, quiz_score: str, quiz_subject: str = "",
                      date: str = None):
    """Update a student's quiz score on the Quiz Score Sheet."""
    date = date or today_str()
    ws = _get_worksheet(SCORE_SHEET_ID, QUIZ_TAB)
    if not ws:
        return False

    row = _find_student_row(ws, student_name)
    if not row:
        return False

    date_col = _find_date_column(ws, date, date_row=2, first_col=QUIZ_FIRST_DATE_COL)
    if not date_col:
        log.warning(f"Date column not found for {date} on Quiz Sheet")
        return False

    try:
        updates = []

        # Quiz Subject is the first column in the date block
        if quiz_subject:
            updates.append({
                "range": gspread.utils.rowcol_to_a1(row, date_col),
                "values": [[quiz_subject]],
            })

        # Total Score is the second column in the date block
        score_col = date_col + 1
        updates.append({
            "range": gspread.utils.rowcol_to_a1(row, score_col),
            "values": [[quiz_score]],
        })

        ws.batch_update(updates, value_input_option="USER_ENTERED")
        log.info(f"Quiz Sheet updated: {student_name}, score={quiz_score}")
        return True

    except Exception as e:
        log.error(f"Error updating Quiz sheet for {student_name}: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# GT SHEET UPDATES
# ─────────────────────────────────────────────────────────────
def update_gt_score(student_name: str, gt_score: str, date: str = None):
    """Update a student's GT score on the GT Sheet."""
    date = date or today_str()
    ws = _get_worksheet(SCORE_SHEET_ID, GT_TAB)
    if not ws:
        return False

    row = _find_student_row(ws, student_name)
    if not row:
        return False

    date_col = _find_date_column(ws, date, date_row=1, first_col=GT_FIRST_DATE_COL)
    if not date_col:
        log.warning(f"Date column not found for {date} on GT Sheet")
        return False

    try:
        ws.update_cell(row, date_col, gt_score)
        log.info(f"GT Sheet updated: {student_name}, score={gt_score}")
        return True
    except Exception as e:
        log.error(f"Error updating GT sheet for {student_name}: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# BATCH UPDATE (called at 11 PM audit)
# ─────────────────────────────────────────────────────────────
def update_all_scores(student_name: str, date: str = None,
                       cm_score: str = "", mynb: bool = False,
                       quiz_score: str = "", gt_score: str = ""):
    """
    Update all sheets for a student at once (11 PM audit).
    Only writes non-empty values.
    """
    date = date or today_str()
    results = {}

    if cm_score or mynb:
        results["cm"] = update_cm_score(student_name, cm_score, mynb, date)
    elif mynb:
        results["mynb"] = update_mynb_only(student_name, date)

    if quiz_score:
        results["quiz"] = update_quiz_score(student_name, quiz_score, date=date)

    if gt_score:
        results["gt"] = update_gt_score(student_name, gt_score, date=date)

    return results
