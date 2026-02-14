"""LLM client configuration for the X Content Agent system.

Centralizes model selection and configuration. Uses gemini-2.0-flash for
cheap classification tasks and gemini-2.5-flash for quality generation.
"""

from __future__ import annotations

# Model identifiers -- single source of truth
# Using gemini-2.0-flash for all agents to stay within Vertex AI free-tier
# rate limits. Upgrade QUALITY_MODEL to gemini-2.5-flash once you have
# higher quota or a billing-enabled project with paid tier.
FAST_MODEL = "gemini-2.0-flash"      # Cheap: collection, ranking, quality checks
QUALITY_MODEL = "gemini-2.0-flash"   # Draft generation (upgrade to 2.5-flash with higher quota)


def get_generation_config(
    max_output_tokens: int = 300,
    temperature: float = 0.7,
) -> dict:
    """Return a generation config dict compatible with ADK's generate_content_config.

    Args:
        max_output_tokens: Cap on response length. 300 tokens ~ 280 chars
            which fits a single X post.
        temperature: Controls creativity. 0.7 balances variety with coherence.
    """
    return {
        "max_output_tokens": max_output_tokens,
        "temperature": temperature,
    }


# Pre-built configs for common use cases
RANKING_CONFIG = get_generation_config(max_output_tokens=500, temperature=0.2)
DRAFTING_CONFIG = get_generation_config(max_output_tokens=350, temperature=0.8)
QUALITY_CONFIG = get_generation_config(max_output_tokens=400, temperature=0.1)
