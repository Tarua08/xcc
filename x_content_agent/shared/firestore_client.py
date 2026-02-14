"""Firestore client for the X Content Agent system.

Provides typed CRUD operations over the items and drafts collections.
Uses URL-hash-based IDs for idempotent writes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from .models import DraftPost, DraftStatus, SignalItem, ScoredItem

logger = logging.getLogger(__name__)


class FirestoreClient:
    """Thin wrapper over Firestore with typed accessors for agent data."""

    ITEMS_COLLECTION = "items"
    DRAFTS_COLLECTION = "drafts"

    def __init__(self, project_id: Optional[str] = None):
        self._db = firestore.Client(project=project_id)
        logger.info("Firestore client initialized (project=%s)", project_id)

    # ------------------------------------------------------------------
    # Items
    # ------------------------------------------------------------------

    def item_exists(self, item_id: str) -> bool:
        """Check if an item already exists (for dedup)."""
        doc = self._db.collection(self.ITEMS_COLLECTION).document(item_id).get()
        return doc.exists

    def save_item(self, item: SignalItem) -> str:
        """Save a collected signal item. Uses set+merge for idempotency."""
        item_id = item.item_id
        doc_ref = self._db.collection(self.ITEMS_COLLECTION).document(item_id)
        data = item.model_dump(mode="json")
        data["item_id"] = item_id
        doc_ref.set(data, merge=True)
        logger.debug("Saved item %s (%s)", item_id, item.title[:50])
        return item_id

    def get_item(self, item_id: str) -> Optional[SignalItem]:
        """Retrieve a single item by ID."""
        doc = self._db.collection(self.ITEMS_COLLECTION).document(item_id).get()
        if not doc.exists:
            return None
        return SignalItem.model_validate(doc.to_dict())

    def get_today_items(self, date_str: str) -> list[dict]:
        """Get all items collected on a given date (YYYY-MM-DD)."""
        start = datetime.fromisoformat(f"{date_str}T00:00:00+00:00")
        end = datetime.fromisoformat(f"{date_str}T23:59:59+00:00")
        docs = (
            self._db.collection(self.ITEMS_COLLECTION)
            .where(filter=FieldFilter("collected_at", ">=", start))
            .where(filter=FieldFilter("collected_at", "<=", end))
            .stream()
        )
        return [doc.to_dict() for doc in docs]

    # ------------------------------------------------------------------
    # Drafts
    # ------------------------------------------------------------------

    def save_draft(self, draft: DraftPost) -> str:
        """Save a draft post. Uses set+merge for idempotency."""
        doc_ref = self._db.collection(self.DRAFTS_COLLECTION).document(draft.draft_id)
        data = draft.model_dump(mode="json")
        doc_ref.set(data, merge=True)
        logger.debug("Saved draft %s (status=%s)", draft.draft_id, draft.status)
        return draft.draft_id

    def get_draft(self, draft_id: str) -> Optional[DraftPost]:
        """Retrieve a single draft by ID."""
        doc = self._db.collection(self.DRAFTS_COLLECTION).document(draft_id).get()
        if not doc.exists:
            return None
        return DraftPost.model_validate(doc.to_dict())

    def update_draft(self, draft_id: str, updates: dict) -> None:
        """Partial update of a draft document."""
        doc_ref = self._db.collection(self.DRAFTS_COLLECTION).document(draft_id)
        updates["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        doc_ref.update(updates)
        logger.info("Updated draft %s: %s", draft_id, list(updates.keys()))

    def list_drafts(
        self,
        status: Optional[DraftStatus] = None,
        limit: int = 50,
    ) -> list[DraftPost]:
        """List drafts, optionally filtered by status.

        When filtering by status, we skip order_by to avoid requiring
        a composite index (MVP simplicity). Client-side sort instead.
        """
        query = self._db.collection(self.DRAFTS_COLLECTION)
        if status:
            query = query.where(filter=FieldFilter("status", "==", status.value))
        else:
            # Only order_by when no filter (single-field index suffices)
            query = query.order_by("created_at", direction=firestore.Query.DESCENDING)
        query = query.limit(limit)
        docs = query.stream()
        results = []
        for doc in docs:
            try:
                results.append(DraftPost.model_validate(doc.to_dict()))
            except Exception as e:
                logger.warning("Skipping invalid draft %s: %s", doc.id, e)
        # Client-side sort when we couldn't use order_by
        if status:
            results.sort(key=lambda d: d.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return results

    def get_approved_drafts_for_week(self) -> list[DraftPost]:
        """Get all approved drafts that haven't been scheduled yet."""
        return self.list_drafts(status=DraftStatus.APPROVED, limit=100)

    def get_pending_drafts(self) -> list[DraftPost]:
        """Get all drafts pending human review."""
        return self.list_drafts(status=DraftStatus.PENDING)
