"""Tests for utility functions."""

from x_content_agent.shared.utils import (
    sanitize_for_prompt,
    truncate_for_post,
    url_to_id,
)


class TestUrlToId:
    def test_deterministic(self):
        assert url_to_id("https://example.com") == url_to_id("https://example.com")

    def test_different_urls(self):
        assert url_to_id("https://a.com") != url_to_id("https://b.com")

    def test_strips_whitespace(self):
        assert url_to_id("  https://example.com  ") == url_to_id("https://example.com")

    def test_length(self):
        assert len(url_to_id("https://example.com")) == 16


class TestSanitizeForPrompt:
    def test_empty_string(self):
        assert sanitize_for_prompt("") == ""

    def test_html_entities(self):
        assert sanitize_for_prompt("&amp; &lt; &gt;") == "& < >"

    def test_control_characters(self):
        result = sanitize_for_prompt("hello\x00world\x01test")
        assert "\x00" not in result
        assert "\x01" not in result
        assert "helloworld" in result

    def test_truncation(self):
        long_text = "x" * 3000
        result = sanitize_for_prompt(long_text)
        assert len(result) <= 2004  # 2000 + "..."

    def test_preserves_newlines(self):
        assert "\n" in sanitize_for_prompt("line1\nline2")


class TestTruncateForPost:
    def test_short_text_unchanged(self):
        assert truncate_for_post("hello") == "hello"

    def test_exact_limit(self):
        text = "x" * 280
        assert truncate_for_post(text) == text

    def test_over_limit(self):
        text = "x" * 300
        result = truncate_for_post(text)
        assert len(result) <= 280

    def test_word_boundary(self):
        text = "word " * 60  # ~300 chars
        result = truncate_for_post(text)
        assert result.endswith("...")
        assert len(result) <= 280
