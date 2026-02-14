"""Tests for collector agent tool functions.

These tests verify the tool functions handle errors gracefully.
Actual HTTP calls are not made in unit tests -- use integration tests for that.
"""

from unittest.mock import patch, MagicMock

from x_content_agent.agents.collector_agent import (
    fetch_github_trending,
    fetch_hackernews_top,
    fetch_arxiv_papers,
    fetch_rss_feeds,
)


class TestFetchGitHubTrending:
    @patch("x_content_agent.agents.collector_agent.httpx.Client")
    def test_success(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "items": [
                {
                    "html_url": "https://github.com/test/repo",
                    "full_name": "test/repo",
                    "description": "An AI agent framework",
                    "stargazers_count": 100,
                    "language": "Python",
                    "updated_at": "2024-01-01T00:00:00Z",
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        result = fetch_github_trending()
        assert result["status"] == "success"
        assert result["count"] == 1
        assert result["items"][0]["url"] == "https://github.com/test/repo"

    @patch("x_content_agent.agents.collector_agent.httpx.Client")
    def test_error_handling(self, mock_client_cls):
        mock_client_cls.side_effect = Exception("Connection failed")
        result = fetch_github_trending()
        assert result["status"] == "error"
        assert "items" in result
        assert len(result["items"]) == 0


class TestFetchHackerNewsTop:
    @patch("x_content_agent.agents.collector_agent.httpx.Client")
    def test_error_handling(self, mock_client_cls):
        mock_client_cls.side_effect = Exception("Connection failed")
        result = fetch_hackernews_top()
        assert result["status"] == "error"


class TestFetchArxivPapers:
    @patch("x_content_agent.agents.collector_agent.httpx.Client")
    def test_error_handling(self, mock_client_cls):
        mock_client_cls.side_effect = Exception("Connection failed")
        result = fetch_arxiv_papers()
        assert result["status"] == "error"


class TestFetchRSSFeeds:
    @patch("x_content_agent.agents.collector_agent.httpx.Client")
    def test_error_handling(self, mock_client_cls):
        mock_client_cls.side_effect = Exception("Connection failed")
        result = fetch_rss_feeds()
        assert result["status"] == "error"
