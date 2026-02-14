"""Tests for quality guard tool functions."""

from x_content_agent.agents.quality_guard_agent import (
    check_character_limit,
    check_hype_language,
    check_substance,
)


class TestCheckHypeLanguage:
    def test_no_hype(self):
        result = check_hype_language("Try using LangGraph for multi-step RAG pipelines.")
        assert result["status"] == "success"
        assert not result["has_hype"]

    def test_detects_game_changer(self):
        result = check_hype_language("This is a game-changer for AI agents!")
        assert result["has_hype"]

    def test_detects_revolutionary(self):
        result = check_hype_language("A revolutionary new approach to RAG.")
        assert result["has_hype"]

    def test_detects_changes_everything(self):
        result = check_hype_language("This changes everything about deployment.")
        assert result["has_hype"]


class TestCheckCharacterLimit:
    def test_within_limit(self):
        result = check_character_limit("Short post")
        assert result["within_limit"]
        assert result["over_by"] == 0

    def test_over_limit(self):
        result = check_character_limit("x" * 300)
        assert not result["within_limit"]
        assert result["over_by"] == 20

    def test_exact_limit(self):
        result = check_character_limit("x" * 280)
        assert result["within_limit"]


class TestCheckSubstance:
    def test_has_action_verb(self):
        result = check_substance("Try deploying this with Docker for faster iteration.")
        assert result["indicators"]["has_action_verb"]

    def test_has_tradeoff_language(self):
        result = check_substance("Fast, but the tradeoff is higher memory usage.")
        assert result["indicators"]["has_tradeoff_language"]

    def test_has_question(self):
        result = check_substance("Have you tried running RAG eval on your pipeline?")
        assert result["indicators"]["has_question"]

    def test_low_substance(self):
        result = check_substance("AI is amazing and the future is bright.")
        assert result["substance_score"] < 50
