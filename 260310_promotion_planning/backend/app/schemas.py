"""Pydantic schemas for promotion API."""

import math


def _is_na(v):
    try:
        return v is None or (isinstance(v, float) and math.isnan(v))
    except (TypeError, ValueError):
        return False


def promotion_row_to_dict(row) -> dict:
    """Convert promotion row to API response dict."""
    d = {}
    for col in row.index:
        v = row[col]
        if _is_na(v):
            d[col] = None
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            try:
                if float(v) == int(v):
                    d[col] = int(v)
                else:
                    d[col] = float(v)
            except (ValueError, TypeError):
                d[col] = str(v) if v is not None else None
        else:
            d[col] = v
    return d
