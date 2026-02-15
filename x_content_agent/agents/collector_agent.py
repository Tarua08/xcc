"""CollectorAgent: Fetches signals from GitHub, HN, arXiv, RSS, Reddit, Product Hunt.

This agent uses function tools to fetch from each source independently.
It deduplicates items by URL hash before storing them in Firestore.
Uses gemini-2.0-flash since this is a simple orchestration task.
"""

from __future__ import annotations

import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Optional

import httpx
from google.adk.agents import Agent

from ..shared.llm_client import FAST_MODEL
from ..shared.models import SignalItem, SignalSource
from ..shared.utils import sanitize_for_prompt

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 30.0
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds


def _request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    **kwargs,
) -> httpx.Response:
    """Make an HTTP request with exponential backoff on transient failures."""
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.request(method, url, **kwargs)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", RETRY_BACKOFF_BASE ** (attempt + 1)))
                logger.warning("Rate limited by %s, retrying in %ds", url, retry_after)
                time.sleep(retry_after)
                continue
            resp.raise_for_status()
            return resp
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last_exc = e
            wait = RETRY_BACKOFF_BASE ** (attempt + 1)
            logger.warning("Request to %s failed (attempt %d/%d): %s, retrying in %ds", url, attempt + 1, MAX_RETRIES, e, wait)
            time.sleep(wait)
        except httpx.HTTPStatusError as e:
            if e.response.status_code >= 500:
                last_exc = e
                wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                logger.warning("Server error from %s (attempt %d/%d): %s, retrying in %ds", url, attempt + 1, MAX_RETRIES, e, wait)
                time.sleep(wait)
            else:
                raise
    raise last_exc or httpx.HTTPError(f"Failed after {MAX_RETRIES} retries: {url}")


# ---------------------------------------------------------------------------
# Tool functions -- ADK auto-wraps these as FunctionTools
# ---------------------------------------------------------------------------


def fetch_github_trending() -> dict:
    """Fetch trending repositories from GitHub related to AI/ML.

    Returns:
        dict: A dict with 'status' key and 'items' list of signal items.
    """
    try:
        url = "https://api.github.com/search/repositories"
        params = {
            "q": "AI agents OR RAG OR LLM OR evaluation framework",
            "sort": "stars",
            "order": "desc",
            "per_page": 20,
        }
        headers = {"Accept": "application/vnd.github.v3+json"}
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            resp = _request_with_retry(client, "GET", url, params=params, headers=headers)
            data = resp.json()

        items = []
        for repo in data.get("items", [])[:20]:
            items.append({
                "url": repo.get("html_url", ""),
                "title": repo.get("full_name", ""),
                "source": SignalSource.GITHUB.value,
                "description": sanitize_for_prompt(
                    repo.get("description", "") or ""
                ),
                "metadata": {
                    "stars": repo.get("stargazers_count", 0),
                    "language": repo.get("language", ""),
                    "updated_at": repo.get("updated_at", ""),
                },
            })
        return {"status": "success", "items": items, "count": len(items)}
    except Exception as e:
        logger.error("GitHub fetch failed: %s", e)
        return {"status": "error", "error_message": str(e), "items": []}


def fetch_hackernews_top() -> dict:
    """Fetch top stories from Hacker News related to AI/ML topics.

    Returns:
        dict: A dict with 'status' key and 'items' list of signal items.
    """
    try:
        base_url = "https://hacker-news.firebaseio.com/v0"
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            resp = _request_with_retry(client, "GET", f"{base_url}/topstories.json")
            story_ids = resp.json()[:30]

            items = []
            for sid in story_ids:
                try:
                    story_resp = _request_with_retry(client, "GET", f"{base_url}/item/{sid}.json")
                except Exception:
                    continue
                story = story_resp.json()
                if not story or story.get("type") != "story":
                    continue

                title = story.get("title", "").lower()
                ai_keywords = [
                    "ai", "llm", "gpt", "agent", "rag", "embedding",
                    "transformer", "ml", "machine learning", "neural",
                    "openai", "anthropic", "gemini", "claude", "model",
                    "evaluation", "benchmark", "vector", "retrieval",
                ]
                if not any(kw in title for kw in ai_keywords):
                    continue

                url = story.get("url", f"https://news.ycombinator.com/item?id={sid}")
                items.append({
                    "url": url,
                    "title": story.get("title", ""),
                    "source": SignalSource.HACKERNEWS.value,
                    "description": sanitize_for_prompt(
                        story.get("title", "")
                    ),
                    "metadata": {
                        "hn_id": sid,
                        "score": story.get("score", 0),
                        "comments": story.get("descendants", 0),
                    },
                })
                if len(items) >= 15:
                    break

        return {"status": "success", "items": items, "count": len(items)}
    except Exception as e:
        logger.error("HackerNews fetch failed: %s", e)
        return {"status": "error", "error_message": str(e), "items": []}


def fetch_arxiv_papers() -> dict:
    """Fetch recent arXiv papers on AI agents, RAG, and evaluation.

    Returns:
        dict: A dict with 'status' key and 'items' list of signal items.
    """
    try:
        search_query = (
            "cat:cs.AI AND "
            "(abs:agent OR abs:RAG OR abs:retrieval augmented "
            "OR abs:evaluation framework OR abs:LLM deployment)"
        )
        url = "https://export.arxiv.org/api/query"
        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": 15,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            resp = _request_with_retry(client, "GET", url, params=params)

        items = []
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(resp.text)
        for entry in root.findall("atom:entry", ns):
            id_el = entry.find("atom:id", ns)
            title_el = entry.find("atom:title", ns)
            summary_el = entry.find("atom:summary", ns)
            if id_el is not None and title_el is not None:
                paper_url = (id_el.text or "").strip()
                items.append({
                    "url": paper_url,
                    "title": sanitize_for_prompt(
                        " ".join((title_el.text or "").strip().split())
                    ),
                    "source": SignalSource.ARXIV.value,
                    "description": sanitize_for_prompt(
                        " ".join((summary_el.text or "").strip().split()) if summary_el is not None else ""
                    )[:500],
                    "metadata": {"arxiv_id": paper_url.split("/")[-1]},
                })

        return {"status": "success", "items": items, "count": len(items)}
    except Exception as e:
        logger.error("arXiv fetch failed: %s", e)
        return {"status": "error", "error_message": str(e), "items": []}


def fetch_rss_feeds() -> dict:
    """Fetch recent posts from curated AI/ML RSS/Atom feeds.

    Sources include top AI researchers, company blogs, and newsletters.

    Returns:
        dict: A dict with 'status' key and 'items' list of signal items.
    """
    feeds = [
        # Individual researchers / practitioners
        "https://lilianweng.github.io/index.xml",
        "https://simonwillison.net/atom/everything/",
        "https://www.latent.space/feed",
        "https://cameronrwolfe.substack.com/feed",
        # Company / product blogs
        "https://blog.langchain.dev/rss/",
        "https://openai.com/blog/rss.xml",
        "https://huggingface.co/blog/feed.xml",
        # Newsletters / aggregators
        "https://thesequence.substack.com/feed",
    ]
    items = []
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            for feed_url in feeds:
                try:
                    resp = _request_with_retry(client, "GET", feed_url)

                    text = resp.text
                    entries = re.findall(r"<entry>(.*?)</entry>", text, re.DOTALL)
                    if not entries:
                        entries = re.findall(r"<item>(.*?)</item>", text, re.DOTALL)

                    for entry in entries[:5]:
                        link = re.search(r'<link[^>]*href="([^"]+)"', entry)
                        if not link:
                            link = re.search(r"<link>(.*?)</link>", entry)
                        if not link:
                            continue
                        entry_url = link.group(1).strip()

                        title = re.search(r"<title[^>]*>(.*?)</title>", entry, re.DOTALL)
                        desc = re.search(
                            r"<(?:summary|description)[^>]*>(.*?)</(?:summary|description)>",
                            entry,
                            re.DOTALL,
                        )
                        items.append({
                            "url": entry_url,
                            "title": sanitize_for_prompt(
                                title.group(1).strip() if title else "Untitled"
                            ),
                            "source": SignalSource.RSS.value,
                            "description": sanitize_for_prompt(
                                (desc.group(1).strip() if desc else "")[:500]
                            ),
                            "metadata": {"feed": feed_url},
                        })
                except Exception as e:
                    logger.warning("Failed to fetch RSS feed %s: %s", feed_url, e)
                    continue

        return {"status": "success", "items": items, "count": len(items)}
    except Exception as e:
        logger.error("RSS fetch failed: %s", e)
        return {"status": "error", "error_message": str(e), "items": []}


def fetch_reddit_ai() -> dict:
    """Fetch top posts from AI-related subreddits.

    Pulls from r/MachineLearning, r/LocalLLaMA, and r/LangChain.
    Uses Reddit's public JSON API (no auth required).

    Returns:
        dict: A dict with 'status' key and 'items' list of signal items.
    """
    subreddits = [
        "MachineLearning",
        "LocalLLaMA",
        "LangChain",
    ]
    items = []
    try:
        headers = {"User-Agent": "XContentAgent/1.0"}
        with httpx.Client(timeout=HTTP_TIMEOUT, headers=headers, follow_redirects=True) as client:
            for sub in subreddits:
                try:
                    resp = _request_with_retry(
                        client, "GET",
                        f"https://www.reddit.com/r/{sub}/hot.json",
                        params={"limit": 10},
                    )

                    data = resp.json()
                    posts = data.get("data", {}).get("children", [])
                    for post in posts:
                        pd = post.get("data", {})
                        if pd.get("stickied"):
                            continue

                        title = pd.get("title", "")
                        # Pre-filter: skip memes and low-effort posts
                        flair = pd.get("link_flair_text") or ""
                        if flair.lower() in ("meme", "humor", "funny"):
                            continue

                        post_url = pd.get("url", "")
                        if not post_url or post_url.startswith("/r/"):
                            post_url = f"https://www.reddit.com{pd.get('permalink', '')}"

                        items.append({
                            "url": post_url,
                            "title": sanitize_for_prompt(title),
                            "source": SignalSource.REDDIT.value,
                            "description": sanitize_for_prompt(
                                pd.get("selftext", "")
                            )[:500],
                            "metadata": {
                                "subreddit": sub,
                                "score": pd.get("score", 0),
                                "comments": pd.get("num_comments", 0),
                            },
                        })
                except Exception as e:
                    logger.warning("Failed to fetch Reddit r/%s: %s", sub, e)
                    continue

        return {"status": "success", "items": items, "count": len(items)}
    except Exception as e:
        logger.error("Reddit fetch failed: %s", e)
        return {"status": "error", "error_message": str(e), "items": []}


def fetch_producthunt_ai() -> dict:
    """Fetch recent AI-related product launches from Product Hunt.

    Uses the public Product Hunt homepage feed (no API key needed).

    Returns:
        dict: A dict with 'status' key and 'items' list of signal items.
    """
    try:
        headers = {
            "User-Agent": "XContentAgent/1.0",
            "Accept": "application/json",
        }
        with httpx.Client(timeout=HTTP_TIMEOUT, headers=headers, follow_redirects=True) as client:
            # PH has an RSS feed for newest
            resp = _request_with_retry(client, "GET", "https://www.producthunt.com/feed")

            text = resp.text
            entries = re.findall(r"<item>(.*?)</item>", text, re.DOTALL)
            if not entries:
                entries = re.findall(r"<entry>(.*?)</entry>", text, re.DOTALL)

            items = []
            ai_keywords = [
                "ai", "llm", "gpt", "agent", "rag", "ml",
                "machine learning", "neural", "copilot", "chatbot",
                "automation", "openai", "anthropic", "gemini",
                "vector", "embedding", "workflow", "no-code ai",
            ]
            for entry in entries:
                title_match = re.search(r"<title[^>]*>(.*?)</title>", entry, re.DOTALL)
                link_match = re.search(r"<link>(.*?)</link>", entry)
                if not link_match:
                    link_match = re.search(r'<link[^>]*href="([^"]+)"', entry)
                desc_match = re.search(
                    r"<(?:description|summary)[^>]*>(.*?)</(?:description|summary)>",
                    entry,
                    re.DOTALL,
                )

                if not title_match or not link_match:
                    continue

                title = sanitize_for_prompt(title_match.group(1).strip())
                title_lower = title.lower()
                desc_text = sanitize_for_prompt(
                    desc_match.group(1).strip() if desc_match else ""
                )[:500]
                combined = f"{title_lower} {desc_text.lower()}"

                # Only keep AI-related products
                if not any(kw in combined for kw in ai_keywords):
                    continue

                items.append({
                    "url": link_match.group(1).strip(),
                    "title": title,
                    "source": SignalSource.PRODUCTHUNT.value,
                    "description": desc_text,
                    "metadata": {"source_feed": "producthunt"},
                })

                if len(items) >= 10:
                    break

        return {"status": "success", "items": items, "count": len(items)}
    except Exception as e:
        logger.error("Product Hunt fetch failed: %s", e)
        return {"status": "error", "error_message": str(e), "items": []}


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------


def create_collector_agent() -> Agent:
    """Create the CollectorAgent with source-fetching tools."""
    return Agent(
        name="collector_agent",
        model=FAST_MODEL,
        description=(
            "Collects AI/ML signals from GitHub, HN, arXiv, RSS feeds, "
            "Reddit, and Product Hunt"
        ),
        instruction=(
            "You are a signal collector. Your job is to fetch items from all "
            "available sources. Call each fetch tool exactly once, then combine "
            "all results into a single JSON array of items.\n\n"
            "Steps:\n"
            "1. Call fetch_github_trending\n"
            "2. Call fetch_hackernews_top\n"
            "3. Call fetch_arxiv_papers\n"
            "4. Call fetch_rss_feeds\n"
            "5. Call fetch_reddit_ai\n"
            "6. Call fetch_producthunt_ai\n"
            "7. Combine all items from all sources into one list\n"
            "8. Return the combined list as a JSON array\n\n"
            "Do not filter or rank items -- just collect them all."
        ),
        tools=[
            fetch_github_trending,
            fetch_hackernews_top,
            fetch_arxiv_papers,
            fetch_rss_feeds,
            fetch_reddit_ai,
            fetch_producthunt_ai,
        ],
        output_key="collected_items",
    )
