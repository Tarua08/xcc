"""X (Twitter) API v2 posting service.

Posts approved drafts directly to X using OAuth 1.0a (User Context).
Requires four env vars:
  X_API_KEY, X_API_KEY_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
"""

from __future__ import annotations

import logging
import os

import tweepy

logger = logging.getLogger(__name__)


class XPoster:
    """Thin wrapper around tweepy.Client for posting tweets."""

    def __init__(self) -> None:
        self.api_key = os.getenv("X_API_KEY", "")
        self.api_key_secret = os.getenv("X_API_KEY_SECRET", "")
        self.access_token = os.getenv("X_ACCESS_TOKEN", "")
        self.access_token_secret = os.getenv("X_ACCESS_TOKEN_SECRET", "")
        self._client: tweepy.Client | None = None

    @property
    def is_configured(self) -> bool:
        """Check if all 4 credentials are present."""
        return all([
            self.api_key,
            self.api_key_secret,
            self.access_token,
            self.access_token_secret,
        ])

    def _get_client(self) -> tweepy.Client:
        if self._client is None:
            if not self.is_configured:
                raise RuntimeError(
                    "X API credentials not configured. "
                    "Set X_API_KEY, X_API_KEY_SECRET, X_ACCESS_TOKEN, "
                    "X_ACCESS_TOKEN_SECRET in .env"
                )
            self._client = tweepy.Client(
                consumer_key=self.api_key,
                consumer_secret=self.api_key_secret,
                access_token=self.access_token,
                access_token_secret=self.access_token_secret,
            )
        return self._client

    def post_tweet(self, text: str) -> dict:
        """Post a tweet and return the result.

        Args:
            text: Tweet text (must be <= 280 chars).

        Returns:
            dict with 'success', 'tweet_id', and 'tweet_url' on success,
            or 'success' False and 'error' on failure.
        """
        if len(text) > 4000:
            return {
                "success": False,
                "error": f"Tweet exceeds 4000 chars ({len(text)})",
            }

        try:
            client = self._get_client()
            response = client.create_tweet(text=text)
            tweet_id = response.data["id"]
            logger.info("Tweet posted successfully: %s", tweet_id)
            return {
                "success": True,
                "tweet_id": tweet_id,
                "tweet_url": f"https://x.com/i/status/{tweet_id}",
            }
        except tweepy.TweepyException as e:
            logger.error("Failed to post tweet: %s", e)
            return {"success": False, "error": str(e)}


# Module-level singleton
_poster: XPoster | None = None


def get_poster() -> XPoster:
    global _poster
    if _poster is None:
        _poster = XPoster()
    return _poster
