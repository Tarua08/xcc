"""RankerAgent: Scores and filters collected items by relevance.

Reads collected items from session state, scores them on relevance to
target topics, and shortlists the top 10. Uses gemini-2.0-flash since
this is a classification task.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from google.adk.agents import Agent

from ..shared.llm_client import FAST_MODEL
from ..shared.utils import sanitize_for_prompt

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "ranking.txt"


def _load_ranking_prompt() -> str:
    """Load the ranking prompt template from file."""
    if _PROMPT_PATH.exists():
        return _PROMPT_PATH.read_text()
    return ""


def score_items(items_json: str) -> dict:
    """Score a batch of items on relevance to target AI/ML topics.

    This tool is called by the RankerAgent with the collected items.
    The actual scoring is done by the LLM via the agent's instruction.

    Args:
        items_json: JSON string of items to score.

    Returns:
        dict: Status and the items passed for scoring.
    """
    try:
        raw = json.loads(items_json) if isinstance(items_json, str) else items_json
        if not isinstance(raw, list):
            raw = [raw] if isinstance(raw, dict) else []

        # Defensively parse: LLM may pass items as nested JSON strings
        items = []
        for item in raw:
            if isinstance(item, str):
                try:
                    item = json.loads(item)
                except (json.JSONDecodeError, TypeError):
                    continue
            if isinstance(item, dict):
                item["title"] = sanitize_for_prompt(item.get("title", ""))
                item["description"] = sanitize_for_prompt(
                    item.get("description", "")
                )[:500]
                items.append(item)

        return {
            "status": "success",
            "items": items,
            "count": len(items),
        }
    except (json.JSONDecodeError, TypeError, AttributeError) as e:
        logger.error("Failed to parse items for scoring: %s", e)
        return {"status": "error", "error_message": str(e)}


def shortlist_top_items(scored_items_json: str, max_items: int = 10) -> dict:
    """Filter scored items to keep only the top N by relevance score.

    Args:
        scored_items_json: JSON string of scored items with relevance_score field.
        max_items: Maximum number of items to keep (default 10).

    Returns:
        dict: Status and shortlisted items.
    """
    try:
        raw = json.loads(scored_items_json) if isinstance(scored_items_json, str) else scored_items_json
        if not isinstance(raw, list):
            raw = [raw] if isinstance(raw, dict) else []

        # Defensively parse: LLM may pass items as nested JSON strings
        items = []
        for item in raw:
            if isinstance(item, str):
                try:
                    item = json.loads(item)
                except (json.JSONDecodeError, TypeError):
                    continue
            if isinstance(item, dict):
                items.append(item)

        # Filter items with score >= 60 and sort descending
        qualified = [
            item for item in items
            if item.get("relevance_score", 0) >= 60
        ]
        qualified.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
        shortlisted = qualified[:max_items]
        return {
            "status": "success",
            "shortlisted": shortlisted,
            "count": len(shortlisted),
            "total_scored": len(items),
            "total_qualified": len(qualified),
        }
    except (json.JSONDecodeError, TypeError, AttributeError) as e:
        logger.error("Failed to shortlist items: %s", e)
        return {"status": "error", "error_message": str(e)}


def create_ranker_agent() -> Agent:
    """Create the RankerAgent with scoring and filtering tools.

    NOTE: Prompt template files (prompts/ranking.txt) contain {placeholders}
    which ADK would interpret as session state variables. Agent instructions
    must use plain text. Template files are kept as reference for tool-level
    prompt construction.
    """
    return Agent(
        name="ranker_agent",
        model=FAST_MODEL,
        description="Scores and shortlists collected items by relevance to AI/ML topics",
        instruction=(
            "You are a relevance scorer for AI/ML content.\n\n"
            "You will receive collected items in the session state under "
            "'collected_items'. Your job is to:\n\n"
            "1. Read the collected items from the previous agent's output\n"
            "2. Score each item on relevance (0-100) to these topics:\n"
            "   - AI agents and agentic systems\n"
            "   - RAG (Retrieval-Augmented Generation)\n"
            "   - Evaluation frameworks for LLMs\n"
            "   - Production deployments of AI/ML\n"
            "   - Database-aware agents\n\n"
            "3. Use the score_items tool with the items to prepare them\n"
            "4. For each item, assign a relevance_score (0-100) and list matched_topics\n"
            "5. Use shortlist_top_items to filter to the top 10\n"
            "6. Return the shortlisted items as a JSON array\n\n"
            "Scoring guidelines:\n"
            "- 80-100: Directly about a target topic with actionable content\n"
            "- 60-79: Related with useful signal\n"
            "- Below 60: Skip\n\n"
            "Be strict. Prefer quality over quantity."
        ),
        tools=[score_items, shortlist_top_items],
        output_key="shortlisted_items",
    )
