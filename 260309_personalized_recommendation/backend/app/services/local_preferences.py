"""
Load customer preferences from local JSON files (final_overall, final_short_term).
"""

import json
import re
from pathlib import Path
from typing import List, Optional

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
OVERALL_DIR = DATA_DIR / "final_overall_preferences_summaries"
SHORT_TERM_DIR = DATA_DIR / "final_short_term_preferences_summaries"


def _load_json(path: Path) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _extract_customer_id(filename: str) -> Optional[str]:
    """Extract customer_id from filename like customer_<hash>_overall_hierarchy_final_summary.json"""
    m = re.match(r"customer_([a-f0-9]+)_", filename)
    return m.group(1) if m else None


def list_preference_customers() -> List[str]:
    """
    Return union of customer_ids from final_overall and final_short_term.
    """
    seen = set()
    for d in (OVERALL_DIR, SHORT_TERM_DIR):
        if not d.exists():
            continue
        for f in d.iterdir():
            if f.suffix.lower() == ".json":
                cid = _extract_customer_id(f.name)
                if cid:
                    seen.add(cid)
    return sorted(seen)


def get_preferences(customer_id: str) -> Optional[dict]:
    """
    Load overall_summary and short_term_summary for a customer from local JSON.
    Returns dict with keys: customer_id, overall_summary, short_term_summary
    """
    overall_summary = ""
    short_term_summary = ""

    overall_file = OVERALL_DIR / f"customer_{customer_id}_overall_hierarchy_final_summary.json"
    if overall_file.exists():
        data = _load_json(overall_file)
        if data:
            overall_summary = data.get("final_summary", "") or ""

    short_term_file = SHORT_TERM_DIR / f"customer_{customer_id}_short_term_hierarchy_final_summary.json"
    if short_term_file.exists():
        data = _load_json(short_term_file)
        if data:
            short_term_summary = data.get("final_summary", "") or ""

    if not overall_summary and not short_term_summary:
        return None

    return {
        "customer_id": customer_id,
        "overall_summary": overall_summary,
        "short_term_summary": short_term_summary,
    }
