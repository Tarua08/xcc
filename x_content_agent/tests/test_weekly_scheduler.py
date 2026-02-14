"""Tests for weekly scheduler tool functions."""

import json

from x_content_agent.agents.weekly_scheduler_agent import (
    compile_weekly_schedule,
    format_schedule_for_display,
)


class TestCompileWeeklySchedule:
    def test_empty_drafts(self):
        result = compile_weekly_schedule("[]")
        assert result["status"] == "success"
        assert len(result["schedule"]) == 0

    def test_distributes_across_days(self):
        drafts = [
            {"draft_id": f"d{i}", "content": f"Post {i}", "human_lines": ""}
            for i in range(5)
        ]
        result = compile_weekly_schedule(json.dumps(drafts))
        assert result["status"] == "success"
        assert result["total_scheduled"] == 5
        # Should use at least 3 days (max 2 per day)
        days = {e["scheduled_day"] for e in result["schedule"]}
        assert len(days) >= 3

    def test_max_per_day(self):
        drafts = [
            {"draft_id": f"d{i}", "content": f"Post {i}", "human_lines": ""}
            for i in range(4)
        ]
        result = compile_weekly_schedule(json.dumps(drafts))
        day_counts = {}
        for entry in result["schedule"]:
            day = entry["scheduled_day"]
            day_counts[day] = day_counts.get(day, 0) + 1
        for count in day_counts.values():
            assert count <= 2

    def test_error_handling(self):
        result = compile_weekly_schedule("invalid json")
        assert result["status"] == "error"


class TestFormatScheduleForDisplay:
    def test_empty_schedule(self):
        result = format_schedule_for_display("[]")
        assert result["status"] == "success"
        assert "No posts" in result["formatted"]

    def test_formats_correctly(self):
        schedule = [
            {
                "draft_id": "d1",
                "content": "Test post",
                "human_lines": "My take on this.",
                "scheduled_day": "Monday",
                "scheduled_date": "2024-01-15",
            }
        ]
        result = format_schedule_for_display(json.dumps(schedule))
        assert result["status"] == "success"
        assert "Monday" in result["formatted"]
        assert "Test post" in result["formatted"]
        assert "My take on this." in result["formatted"]
