"""Tests for data models."""

import pytest
from datetime import datetime, timezone

from x_content_agent.shared.models import (
    DraftPost,
    DraftStatus,
    DraftUpdateRequest,
    QualityCheckResult,
    SignalItem,
    SignalSource,
    ScoredItem,
    RelevanceTopic,
)


class TestSignalItem:
    def test_item_id_is_deterministic(self):
        item1 = SignalItem(url="https://example.com/test", title="Test", source=SignalSource.GITHUB)
        item2 = SignalItem(url="https://example.com/test", title="Test2", source=SignalSource.HACKERNEWS)
        assert item1.item_id == item2.item_id  # Same URL = same ID

    def test_different_urls_different_ids(self):
        item1 = SignalItem(url="https://example.com/a", title="A", source=SignalSource.GITHUB)
        item2 = SignalItem(url="https://example.com/b", title="B", source=SignalSource.GITHUB)
        assert item1.item_id != item2.item_id

    def test_url_validation(self):
        with pytest.raises(ValueError):
            SignalItem(url="", title="Test", source=SignalSource.GITHUB)

    def test_title_validation(self):
        with pytest.raises(ValueError):
            SignalItem(url="https://example.com", title="", source=SignalSource.GITHUB)

    def test_url_stripped(self):
        item = SignalItem(url="  https://example.com  ", title="Test", source=SignalSource.GITHUB)
        assert item.url == "https://example.com"


class TestDraftPost:
    def test_draft_id_auto_generated(self):
        draft = DraftPost(item_id="abc123", variant=1, content="Test post")
        assert draft.draft_id == "abc123_v1"

    def test_draft_id_explicit(self):
        draft = DraftPost(draft_id="custom_id", item_id="abc", variant=1, content="Test")
        assert draft.draft_id == "custom_id"

    def test_default_status_pending(self):
        draft = DraftPost(item_id="abc", variant=1, content="Test")
        assert draft.status == DraftStatus.PENDING

    def test_variant_range(self):
        with pytest.raises(ValueError):
            DraftPost(item_id="abc", variant=0, content="Test")
        with pytest.raises(ValueError):
            DraftPost(item_id="abc", variant=3, content="Test")


class TestDraftUpdateRequest:
    def test_max_two_human_lines(self):
        with pytest.raises(ValueError):
            DraftUpdateRequest(human_lines="line1\nline2\nline3")

    def test_two_human_lines_ok(self):
        req = DraftUpdateRequest(human_lines="line1\nline2")
        assert req.human_lines == "line1\nline2"

    def test_empty_update_allowed(self):
        req = DraftUpdateRequest()
        assert req.content is None


class TestQualityCheckResult:
    def test_score_range(self):
        qr = QualityCheckResult(draft_id="d1", passed=True, score=85)
        assert qr.score == 85

    def test_score_bounds(self):
        with pytest.raises(ValueError):
            QualityCheckResult(draft_id="d1", passed=True, score=101)


class TestScoredItem:
    def test_relevance_score_bounds(self):
        with pytest.raises(ValueError):
            ScoredItem(
                item_id="x", url="https://x.com", title="X",
                source=SignalSource.GITHUB, relevance_score=101,
            )

    def test_matched_topics(self):
        item = ScoredItem(
            item_id="x", url="https://x.com", title="X",
            source=SignalSource.GITHUB, relevance_score=80,
            matched_topics=[RelevanceTopic.AI_AGENTS, RelevanceTopic.RAG],
        )
        assert len(item.matched_topics) == 2
