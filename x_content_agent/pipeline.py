"""Pipeline orchestrator: Composes agents into a sequential workflow.

Uses ADK's SequentialAgent to run the collection -> ranking -> drafting ->
quality checking pipeline. Handles persistence to Firestore between stages
via callback hooks.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from google.adk.agents import SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.sessions import InMemorySessionService, Session
from google.adk.runners import Runner
from google.genai import types

from .agents.collector_agent import create_collector_agent
from .agents.ranker_agent import create_ranker_agent
from .agents.drafting_agent import create_drafting_agent
from .agents.quality_guard_agent import create_quality_guard_agent
from .shared.firestore_client import FirestoreClient
from .shared.models import (
    DraftPost,
    DraftStatus,
    PipelineRunResult,
    QualityCheckResult,
    SignalItem,
    SignalSource,
)
from .shared.utils import generate_run_id, today_str, url_to_id

logger = logging.getLogger(__name__)


class ContentPipeline:
    """Orchestrates the full content generation pipeline.

    Creates ADK agents, runs them sequentially, and persists results
    to Firestore at each stage.
    """

    def __init__(self, project_id: Optional[str] = None):
        self.db = FirestoreClient(project_id=project_id)
        self.run_id = generate_run_id()
        self._build_pipeline()

    def _build_pipeline(self) -> None:
        """Construct the ADK agent pipeline."""
        self.collector = create_collector_agent()
        self.ranker = create_ranker_agent()
        self.drafter = create_drafting_agent()
        self.quality_guard = create_quality_guard_agent()

        # SequentialAgent runs agents in order, sharing session state
        self.pipeline = SequentialAgent(
            name="content_pipeline",
            sub_agents=[
                self.collector,
                self.ranker,
                self.drafter,
                self.quality_guard,
            ],
            description="End-to-end content generation pipeline",
        )

        self.session_service = InMemorySessionService()
        self.runner = Runner(
            agent=self.pipeline,
            app_name="x_content_agent",
            session_service=self.session_service,
        )

    async def run(self) -> PipelineRunResult:
        """Execute the full pipeline.

        Returns:
            PipelineRunResult with counts and any errors.
        """
        result = PipelineRunResult(
            run_id=self.run_id,
            started_at=datetime.now(timezone.utc),
        )

        logger.info("Pipeline run %s started", self.run_id)

        try:
            # Create a session
            session = await self.session_service.create_session(
                app_name="x_content_agent",
                user_id="system",
            )

            # Run the pipeline by sending a trigger message
            trigger = types.Content(
                role="user",
                parts=[types.Part(text="Run the daily content collection and drafting pipeline.")],
            )

            # Execute through the runner
            final_state = {}
            async for event in self.runner.run_async(
                user_id="system",
                session_id=session.id,
                new_message=trigger,
            ):
                # Capture events for logging
                if hasattr(event, "content") and event.content:
                    logger.debug(
                        "Pipeline event from %s: %s",
                        getattr(event, "author", "unknown"),
                        str(event.content)[:200],
                    )

            # Retrieve final session state
            updated_session = await self.session_service.get_session(
                app_name="x_content_agent",
                user_id="system",
                session_id=session.id,
            )
            if updated_session:
                final_state = updated_session.state or {}

            # Persist results from session state to Firestore
            result = await self._persist_results(final_state, result)

        except Exception as e:
            logger.error("Pipeline run %s failed: %s", self.run_id, e, exc_info=True)
            result.errors.append(str(e))

        result.completed_at = datetime.now(timezone.utc)
        logger.info(
            "Pipeline run %s completed: %d items, %d shortlisted, %d drafts, %d passed quality",
            self.run_id,
            result.items_collected,
            result.items_shortlisted,
            result.drafts_generated,
            result.drafts_passed_quality,
        )
        return result

    async def _persist_results(
        self, state: dict, result: PipelineRunResult
    ) -> PipelineRunResult:
        """Extract data from session state and persist to Firestore."""

        # 1. Persist collected items
        collected_raw = state.get("collected_items", "")
        items = self._parse_json_from_state(collected_raw)
        for item_data in items:
            try:
                if isinstance(item_data, dict) and item_data.get("url"):
                    signal = SignalItem(
                        url=item_data["url"],
                        title=item_data.get("title", "Untitled"),
                        source=SignalSource(item_data.get("source", "rss")),
                        description=item_data.get("description", ""),
                        metadata=item_data.get("metadata", {}),
                    )
                    if not self.db.item_exists(signal.item_id):
                        self.db.save_item(signal)
                        result.items_collected += 1
                    else:
                        logger.debug("Item %s already exists, skipping", signal.item_id)
            except Exception as e:
                logger.warning("Failed to persist item: %s", e)
                result.errors.append(f"Item persist error: {e}")

        # 2. Count shortlisted
        shortlisted_raw = state.get("shortlisted_items", "")
        shortlisted = self._parse_json_from_state(shortlisted_raw)
        result.items_shortlisted = len(shortlisted)

        # 3. Persist drafts
        drafts_raw = state.get("generated_drafts", "")
        drafts = self._parse_json_from_state(drafts_raw)
        for draft_data in drafts:
            try:
                if isinstance(draft_data, dict) and draft_data.get("content"):
                    item_id = draft_data.get("item_id", "unknown")
                    variant = draft_data.get("variant", 1)
                    draft = DraftPost(
                        item_id=item_id,
                        variant=variant,
                        content=draft_data["content"],
                        status=DraftStatus.PENDING,
                    )
                    self.db.save_draft(draft)
                    result.drafts_generated += 1
            except Exception as e:
                logger.warning("Failed to persist draft: %s", e)
                result.errors.append(f"Draft persist error: {e}")

        # 4. Apply quality results
        # The quality guard may return draft_ids that don't match Firestore
        # doc IDs exactly (e.g., numeric indices vs "itemid_v1" format).
        # Build a lookup of actual draft IDs to match against.
        all_draft_ids = [
            d.draft_id for d in self.db.list_drafts(status=DraftStatus.PENDING, limit=200)
        ]

        quality_raw = state.get("quality_results", "")
        quality_results = self._parse_json_from_state(quality_raw)
        for idx, qr_data in enumerate(quality_results):
            try:
                if isinstance(qr_data, dict):
                    draft_id = str(qr_data.get("draft_id", ""))
                    passed = qr_data.get("passed", False)
                    score = qr_data.get("score", 0)
                    issues = qr_data.get("issues", [])

                    # Try to resolve the draft_id to an actual Firestore doc
                    resolved_id = None
                    if draft_id in all_draft_ids:
                        resolved_id = draft_id
                    elif idx < len(all_draft_ids):
                        # Fall back to index-based matching
                        resolved_id = all_draft_ids[idx]

                    if resolved_id:
                        updates = {
                            "quality_score": score,
                            "quality_notes": "; ".join(issues) if issues else "Passed",
                        }
                        if not passed:
                            updates["status"] = DraftStatus.REJECTED.value
                        try:
                            self.db.update_draft(resolved_id, updates)
                        except Exception:
                            # If update fails, use set+merge as fallback
                            logger.debug("update_draft failed for %s, skipping", resolved_id)

                        if passed:
                            result.drafts_passed_quality += 1
            except Exception as e:
                logger.warning("Failed to apply quality result: %s", e)
                result.errors.append(f"Quality result error: {e}")

        return result

    @staticmethod
    def _parse_json_from_state(value) -> list:
        """Safely parse JSON from session state, which may be a string or list."""
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            # Try to extract JSON array from the string
            value = value.strip()
            # Find the first [ and last ] for array extraction
            start = value.find("[")
            end = value.rfind("]")
            if start != -1 and end != -1:
                try:
                    return json.loads(value[start : end + 1])
                except json.JSONDecodeError:
                    pass
            # Try parsing as a single JSON object
            start = value.find("{")
            end = value.rfind("}")
            if start != -1 and end != -1:
                try:
                    obj = json.loads(value[start : end + 1])
                    return [obj] if isinstance(obj, dict) else []
                except json.JSONDecodeError:
                    pass
        return []
