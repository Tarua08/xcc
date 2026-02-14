"""WeeklySchedulerAgent: Compiles approved drafts into a weekly posting schedule.

This agent reads approved drafts from Firestore and organizes them into
a week's posting schedule. It does NOT auto-post -- it produces a
copy-paste-ready list for the human.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from google.adk.agents import Agent

from ..shared.llm_client import FAST_MODEL

logger = logging.getLogger(__name__)

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def compile_weekly_schedule(approved_drafts_json: str) -> dict:
    """Organize approved drafts into a weekly posting schedule.

    Distributes drafts across weekdays, with at most 2 posts per day.
    Prioritizes weekdays (Mon-Fri) over weekends.

    Args:
        approved_drafts_json: JSON string of approved draft objects.

    Returns:
        dict: Status and the compiled schedule.
    """
    try:
        drafts = (
            json.loads(approved_drafts_json)
            if isinstance(approved_drafts_json, str)
            else approved_drafts_json
        )

        if not drafts:
            return {
                "status": "success",
                "schedule": [],
                "message": "No approved drafts to schedule.",
            }

        # Distribute across weekdays (max 2 per day, prefer weekdays)
        schedule = []
        today = datetime.now(timezone.utc)
        # Start from next Monday
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        start_date = today + timedelta(days=days_until_monday)

        day_index = 0
        posts_today = 0
        max_per_day = 2

        for draft in drafts:
            if day_index >= 7:
                break  # Only schedule one week ahead

            scheduled_date = start_date + timedelta(days=day_index)
            day_name = WEEKDAYS[day_index]

            schedule.append({
                "draft_id": draft.get("draft_id", ""),
                "content": draft.get("content", ""),
                "human_lines": draft.get("human_lines", ""),
                "scheduled_day": day_name,
                "scheduled_date": scheduled_date.strftime("%Y-%m-%d"),
            })

            posts_today += 1
            if posts_today >= max_per_day:
                day_index += 1
                posts_today = 0

        return {
            "status": "success",
            "schedule": schedule,
            "total_scheduled": len(schedule),
            "week_starting": start_date.strftime("%Y-%m-%d"),
        }
    except (json.JSONDecodeError, TypeError) as e:
        logger.error("Failed to compile schedule: %s", e)
        return {"status": "error", "error_message": str(e)}


def format_schedule_for_display(schedule_json: str) -> dict:
    """Format the schedule as a human-readable copy-paste list.

    Args:
        schedule_json: JSON string of the schedule from compile_weekly_schedule.

    Returns:
        dict: Status and formatted text.
    """
    try:
        schedule = (
            json.loads(schedule_json)
            if isinstance(schedule_json, str)
            else schedule_json
        )

        if not schedule:
            return {
                "status": "success",
                "formatted": "No posts scheduled for this week.",
            }

        lines = ["=" * 50, "WEEKLY POSTING SCHEDULE", "=" * 50, ""]
        current_day = ""
        for entry in schedule:
            day = entry.get("scheduled_day", "")
            date = entry.get("scheduled_date", "")
            if day != current_day:
                current_day = day
                lines.append(f"--- {day} ({date}) ---")

            content = entry.get("content", "")
            human_lines = entry.get("human_lines", "")
            full_post = content
            if human_lines:
                full_post = f"{content}\n\n{human_lines}"

            lines.append(f"\n{full_post}")
            lines.append(f"[Draft ID: {entry.get('draft_id', '')}]")
            lines.append("")

        lines.append("=" * 50)
        lines.append(f"Total posts: {len(schedule)}")
        return {"status": "success", "formatted": "\n".join(lines)}
    except (json.JSONDecodeError, TypeError) as e:
        logger.error("Failed to format schedule: %s", e)
        return {"status": "error", "error_message": str(e)}


def create_weekly_scheduler_agent() -> Agent:
    """Create the WeeklySchedulerAgent."""
    return Agent(
        name="weekly_scheduler_agent",
        model=FAST_MODEL,
        description="Compiles approved drafts into a weekly posting schedule",
        instruction=(
            "You compile approved drafts into a weekly posting schedule.\n\n"
            "Steps:\n"
            "1. Use compile_weekly_schedule with the approved drafts\n"
            "2. Use format_schedule_for_display to create a readable list\n"
            "3. Return the formatted schedule\n\n"
            "Important:\n"
            "- Distribute posts evenly across the week\n"
            "- Max 2 posts per day\n"
            "- Prefer weekdays over weekends\n"
            "- Include human signature lines if present\n"
            "- This is a copy-paste list -- no auto-posting"
        ),
        tools=[compile_weekly_schedule, format_schedule_for_display],
        output_key="weekly_schedule",
    )
