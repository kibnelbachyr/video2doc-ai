"""
timestamps.py
-------------
Shared helper for formatting second offsets as MM:SS, used to keep the
transcript and the visual frame context aligned on a common timeline.
"""


def format_timestamp(seconds: float) -> str:
    """Format a second offset as MM:SS (e.g. 125.4 -> '02:05')."""
    total = max(0, int(round(seconds)))
    return f"{total // 60:02d}:{total % 60:02d}"
