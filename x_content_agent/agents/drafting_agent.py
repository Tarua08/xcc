"""DraftingAgent: Generates 2 draft X posts per shortlisted item.

Reads shortlisted items from session state, generates two draft variants
for each, and stores them. Uses gemini-2.5-flash for higher quality output.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from google.adk.agents import Agent

from ..shared.llm_client import QUALITY_MODEL
from ..shared.utils import sanitize_for_prompt

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "drafting.txt"


def _load_drafting_prompt() -> str:
    """Load the drafting prompt template from file."""
    if _PROMPT_PATH.exists():
        return _PROMPT_PATH.read_text()
    return ""


def prepare_drafting_context(item_json: str) -> dict:
    """Prepare a single item's context for draft generation.

    Sanitizes all text fields and formats them for the drafting prompt.

    Args:
        item_json: JSON string of a single shortlisted item.

    Returns:
        dict: Sanitized item context ready for drafting.
    """
    try:
        item = json.loads(item_json) if isinstance(item_json, str) else item_json
        return {
            "status": "success",
            "context": {
                "item_id": item.get("item_id", ""),
                "title": sanitize_for_prompt(item.get("title", "")),
                "url": item.get("url", ""),
                "description": sanitize_for_prompt(
                    item.get("description", "")
                )[:500],
                "source": item.get("source", ""),
                "matched_topics": item.get("matched_topics", []),
            },
        }
    except (json.JSONDecodeError, TypeError) as e:
        logger.error("Failed to prepare drafting context: %s", e)
        return {"status": "error", "error_message": str(e)}


def validate_draft_length(draft_text: str) -> dict:
    """Check that a draft fits within X's character limit.

    Args:
        draft_text: The draft post text to validate.

    Returns:
        dict: Status with character count and whether it fits.
    """
    char_count = len(draft_text)
    fits = char_count <= 4000
    return {
        "status": "success",
        "char_count": char_count,
        "fits_limit": fits,
        "max_allowed": 4000,
    }


def create_drafting_agent() -> Agent:
    """Create the DraftingAgent with drafting tools."""
    return Agent(
        name="drafting_agent",
        model=QUALITY_MODEL,
        description="Generates 2 draft X post variants per shortlisted item",
        instruction=(
            "You are an AI engineer who shares insights on X (Twitter). "
            "You write like a thoughtful builder, not a content marketer.\n\n"
            "You will receive shortlisted items from the ranker. For EACH item, "
            "generate exactly 2 draft variants.\n\n"
            "CRITICAL RULES:\n\n"
            "1. DO NOT include URLs or links in the post. The URL will be "
            "attached separately when posting. Your job is the TEXT only.\n\n"
            "2. DO NOT just describe what the link is. Instead, write YOUR "
            "take on it -- an insight, a question, a practical angle.\n\n"
            "3. LENGTH REQUIREMENTS:\n"
            "   - MINIMUM 200 characters. Posts under 200 chars are TOO SHORT.\n"
            "   - MAXIMUM 600 characters. Sweet spot for engagement.\n"
            "   - AIM for 400-550 characters. Use the space to add real depth.\n\n"
            "4. STRUCTURE each post with 2-3 parts:\n"
            "   - Lead with your opinion, insight, or observation\n"
            "   - Add a supporting detail, example, or tradeoff\n"
            "   - End with a takeaway, question, or practical suggestion\n\n"
            "5. MUST include at least one of:\n"
            "   - A concrete real-world use case or scenario\n"
            "   - An experiment or thing readers can try themselves\n"
            "   - A practical builder workflow or integration idea\n"
            "   - A specific tradeoff, limitation, or nuanced opinion\n\n"
            "6. Write in first person or direct address. Sound like a real "
            "human sharing something interesting, not a press release.\n\n"
            "7. NO generic hype ('game-changer', 'revolutionary', 'excited to share')\n"
            "8. NO fabricated metrics or claims not in the source\n"
            "9. If uncertain about a detail, use hedged language\n\n"
            "GOOD examples (notice they are 400-550 chars with real depth):\n"
            "- 'One thing most agent builders skip: input validation on tool "
            "calls. If your LLM can call APIs, untrusted prompts can exploit "
            "that. I spent a week adding a middleware layer that sanitizes "
            "every tool input before execution. Caught 3 prompt injection "
            "attempts in the first day. The pattern is simple -- validate "
            "inputs against a schema, reject anything with system-level "
            "commands, and log everything. Small effort, massive security "
            "win for production agents.' (450 chars)\n"
            "- 'Been testing multi-agent RAG with LangGraph for two weeks. "
            "The tradeoff is real: complex queries get much better recall "
            "because each agent specializes in a different retrieval "
            "strategy. But latency goes up about 3x. My takeaway: use "
            "multi-agent for research-style queries where accuracy matters, "
            "stick with a single retriever for simple lookups. Know your "
            "query patterns before over-engineering the pipeline.' (440 chars)\n\n"
            "BAD examples (do NOT write like this):\n"
            "- 'Security for LLM tool calls! GuardLLM hardens agents.' "
            "(TOO SHORT, only 55 chars, no substance)\n"
            "- 'Check out this amazing new repo! https://github.com/...' "
            "(no URL allowed, no substance)\n"
            "- 'Exciting developments in AI agents!' (empty hype, too short)\n\n"
            "For each item:\n"
            "1. Use prepare_drafting_context to get the sanitized context\n"
            "2. Write 2 variants that approach the topic from DIFFERENT angles\n"
            "   (e.g., one practical, one opinion-based)\n"
            "3. Use validate_draft_length to verify EACH draft is between "
            "200-600 chars. If under 200, expand it. If over 600, trim it.\n"
            "4. Return all drafts as a JSON array of objects with fields:\n"
            "   item_id, variant (1 or 2), content\n\n"
            "Process items from the 'shortlisted_items' session state."
        ),
        tools=[prepare_drafting_context, validate_draft_length],
        output_key="generated_drafts",
    )
