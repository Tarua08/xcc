"""Structured data models for the X Content Agent system.

All inter-agent communication uses these Pydantic models to enforce
type safety and validation. Firestore documents map directly to/from
these models via .model_dump() / .model_validate().
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import logging

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class SignalSource(str, Enum):
    GITHUB = "github"
    HACKERNEWS = "hackernews"
    REDDIT = "reddit"
    PRODUCTHUNT = "producthunt"
    ARXIV = "arxiv"
    RSS = "rss"


class DraftStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RelevanceTopic(str, Enum):
    AI_AGENTS = "ai_agents"
    RAG = "rag"
    EVAL_FRAMEWORKS = "eval_frameworks"
    DEPLOYMENTS = "deployments"
    DB_AWARE_AGENTS = "db_aware_agents"


# ---------------------------------------------------------------------------
# Collected signal item
# ---------------------------------------------------------------------------


class SignalItem(BaseModel):
    """A single signal collected from an external source."""

    url: str
    title: str
    source: SignalSource
    description: str = ""
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = Field(default_factory=dict)

    @property
    def item_id(self) -> str:
        """Deterministic ID from URL hash for deduplication."""
        return hashlib.sha256(self.url.encode()).hexdigest()[:16]

    @field_validator("url")
    @classmethod
    def url_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("URL must not be empty")
        return v.strip()

    @field_validator("title")
    @classmethod
    def title_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title must not be empty")
        return v.strip()


# ---------------------------------------------------------------------------
# Ranked / scored item
# ---------------------------------------------------------------------------


class ScoredItem(BaseModel):
    """An item after relevance scoring by the RankerAgent."""

    item_id: str
    url: str
    title: str
    source: SignalSource
    description: str = ""
    relevance_score: float = Field(ge=0.0, le=100.0)
    matched_topics: list[RelevanceTopic] = Field(default_factory=list)
    score_reasoning: str = ""
    scored_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Draft post
# ---------------------------------------------------------------------------


class DraftPost(BaseModel):
    """A generated draft X post awaiting human review."""

    draft_id: str = ""
    item_id: str
    variant: int = Field(ge=1, le=2)
    content: str
    status: DraftStatus = DraftStatus.PENDING
    quality_score: float = Field(default=0.0, ge=0.0, le=100.0)
    quality_notes: str = ""
    human_lines: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reviewed_at: Optional[datetime] = None
    review_notes: str = ""

    def model_post_init(self, __context) -> None:
        if not self.draft_id:
            # Sanitize item_id: Firestore doc IDs cannot contain '/'
            safe_id = self.item_id.replace("/", "_")
            self.draft_id = f"{safe_id}_v{self.variant}"

    @field_validator("content")
    @classmethod
    def content_length_check(cls, v: str) -> str:
        if len(v) > 280:
            logger.warning(
                "Draft content is %d chars (over 280 limit); quality guard will flag it",
                len(v),
            )
        return v


# ---------------------------------------------------------------------------
# Quality check result
# ---------------------------------------------------------------------------


class QualityCheckResult(BaseModel):
    """Result of quality guard evaluation on a draft."""

    draft_id: str
    passed: bool
    score: float = Field(ge=0.0, le=100.0)
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Weekly schedule entry
# ---------------------------------------------------------------------------


class ScheduleEntry(BaseModel):
    """An approved draft ready for posting."""

    draft_id: str
    item_id: str
    content: str
    human_lines: str = ""
    approved_at: Optional[datetime] = None
    scheduled_day: Optional[str] = None  # e.g. "Monday", "Tuesday"


# ---------------------------------------------------------------------------
# API request/response models for the approval UI
# ---------------------------------------------------------------------------


class DraftUpdateRequest(BaseModel):
    """Request body for updating a draft via the approval UI."""

    content: Optional[str] = None
    human_lines: Optional[str] = None
    status: Optional[DraftStatus] = None
    review_notes: Optional[str] = None

    @field_validator("human_lines")
    @classmethod
    def limit_human_lines(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            lines = [l for l in v.strip().split("\n") if l.strip()]
            if len(lines) > 2:
                raise ValueError("Maximum 2 human signature lines allowed")
        return v


class PipelineRunResult(BaseModel):
    """Summary of a pipeline execution."""

    run_id: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    items_collected: int = 0
    items_shortlisted: int = 0
    drafts_generated: int = 0
    drafts_passed_quality: int = 0
    errors: list[str] = Field(default_factory=list)
