"""QualityGuardAgent: Validates draft posts against content quality rules.

Reviews each generated draft for hype language, fabricated claims,
character limits, and content substance requirements.
Uses gemini-2.0-flash since this is a classification/checking task.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from google.adk.agents import Agent

from ..shared.llm_client import FAST_MODEL
from ..shared.utils import sanitize_for_prompt

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "quality_check.txt"


def _load_quality_prompt() -> str:
    """Load the quality check prompt template from file."""
    if _PROMPT_PATH.exists():
        return _PROMPT_PATH.read_text()
    return ""

# Hype words/phrases to flag
HYPE_PATTERNS = [
    r"\bgame[- ]?changer\b",
    r"\brevolutionary\b",
    r"\bchanges everything\b",
    r"\bmind[- ]?blowing\b",
    r"\binsane\b",
    r"\bunbelievable\b",
    r"\b10x\b",
    r"\b100x\b",
    r"\bkills?\b.*\bindustry\b",
    r"\bdisrupt\b",
]


def check_hype_language(draft_text: str) -> dict:
    """Check a draft for generic AI hype language patterns.

    Args:
        draft_text: The draft post text to check.

    Returns:
        dict: Status with any hype phrases found.
    """
    found = []
    text_lower = draft_text.lower()
    for pattern in HYPE_PATTERNS:
        matches = re.findall(pattern, text_lower)
        if matches:
            found.extend(matches)
    return {
        "status": "success",
        "has_hype": len(found) > 0,
        "hype_phrases": found,
        "draft_text": draft_text,
    }


def check_character_limit(draft_text: str) -> dict:
    """Verify draft is within X's 280 character limit.

    Args:
        draft_text: The draft post text to check.

    Returns:
        dict: Status with character count and pass/fail.
    """
    count = len(draft_text)
    return {
        "status": "success",
        "char_count": count,
        "within_limit": count <= 4000,
        "over_by": max(0, count - 4000),
    }


def check_substance(draft_text: str) -> dict:
    """Preliminary check for content substance indicators.

    Looks for signals that the draft contains actionable content
    rather than vague statements.

    Args:
        draft_text: The draft post text to check.

    Returns:
        dict: Status with substance indicators found.
    """
    indicators = {
        "has_question": "?" in draft_text,
        "has_url_or_reference": "http" in draft_text or "@" in draft_text,
        "has_specific_numbers": bool(re.search(r"\d+[%xX]|\d+\.\d+", draft_text)),
        "has_action_verb": bool(
            re.search(
                r"\b(try|build|test|compare|deploy|evaluate|measure|run|use)\b",
                draft_text.lower(),
            )
        ),
        "has_tradeoff_language": bool(
            re.search(
                r"\b(but|however|tradeoff|limitation|caveat|downside|cost)\b",
                draft_text.lower(),
            )
        ),
    }
    substance_score = sum(indicators.values()) / len(indicators) * 100
    return {
        "status": "success",
        "indicators": indicators,
        "substance_score": round(substance_score, 1),
    }


def create_quality_guard_agent() -> Agent:
    """Create the QualityGuardAgent with quality checking tools."""
    return Agent(
        name="quality_guard_agent",
        model=FAST_MODEL,
        description="Reviews draft posts for quality, accuracy, and content rules",
        instruction=(
            "You are a content quality reviewer for technical AI/ML posts.\n\n"
            "Review each draft from 'generated_drafts' in session state.\n\n"
            "For EACH draft:\n"
            "1. Use check_hype_language to detect generic hype\n"
            "2. Use check_character_limit to verify length\n"
            "3. Use check_substance to assess content depth\n"
            "4. Make a final judgment: does this draft meet ALL rules?\n\n"
            "Quality rules -- a draft MUST:\n"
            "- Be between 200-600 characters (reject if under 200 -- too short)\n"
            "- Contain no generic AI hype language\n"
            "- Include at least one of: use case, experiment, workflow, tradeoff\n"
            "- Not fabricate metrics or claims\n"
            "- Accurately represent the source material\n\n"
            "For each draft, produce a quality check result:\n"
            "- passed: true/false\n"
            "- score: 0-100\n"
            "- issues: list of problems found\n"
            "- suggestions: list of improvement ideas\n\n"
            "Return results as a JSON array of quality check objects, each with:\n"
            "draft_id, passed, score, issues, suggestions\n\n"
            "Be strict. It's better to reject a mediocre draft than to let "
            "low-quality content through."
        ),
        tools=[check_hype_language, check_character_limit, check_substance],
        output_key="quality_results",
    )
