"""Utility functions for the X Content Agent system."""

from __future__ import annotations

import hashlib
import html
import logging
import re
import uuid
from datetime import datetime, timezone


logger = logging.getLogger(__name__)


def url_to_id(url: str) -> str:
    """Generate a deterministic 16-char hex ID from a URL.

    Used as the primary key for items to ensure idempotent collection.
    """
    return hashlib.sha256(url.strip().encode()).hexdigest()[:16]


def generate_run_id() -> str:
    """Generate a unique pipeline run ID."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    return f"run_{ts}_{short_uuid}"


def now_utc() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(timezone.utc)


def today_str() -> str:
    """Return today's date as YYYY-MM-DD string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def sanitize_for_prompt(text: str) -> str:
    """Sanitize external text before inserting into LLM prompts.

    Defends against prompt injection by:
    1. HTML-decoding entities
    2. Stripping control characters
    3. Truncating to reasonable length
    4. Wrapping will be done at the prompt template level with delimiters
    """
    if not text:
        return ""
    # Decode HTML entities
    text = html.unescape(text)
    # Remove control characters except newlines
    text = re.sub(r"[\x00-\x09\x0b-\x0c\x0e-\x1f\x7f]", "", text)
    # Truncate to 2000 chars to keep prompt sizes bounded
    if len(text) > 2000:
        text = text[:2000] + "..."
    return text.strip()


def truncate_for_post(text: str, max_chars: int = 280) -> str:
    """Truncate text to fit X post character limit."""
    if len(text) <= max_chars:
        return text
    # Try to break at a word boundary
    truncated = text[:max_chars - 3]
    last_space = truncated.rfind(" ")
    if last_space > max_chars // 2:
        truncated = truncated[:last_space]
    return truncated + "..."


def setup_logging(level: str = "INFO") -> None:
    """Configure structured logging for the application."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=(
            '{"timestamp":"%(asctime)s",'
            '"level":"%(levelname)s",'
            '"logger":"%(name)s",'
            '"message":"%(message)s"}'
        ),
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
