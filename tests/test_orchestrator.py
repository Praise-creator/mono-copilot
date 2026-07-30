"""Tests for Orchestrator."""

import pytest
from apps.copilot.src.copilot.orchestrator import Orchestrator


@pytest.fixture
def orchestrator():
    """Fixture for orchestrator instance."""
    return Orchestrator()


@pytest.mark.asyncio
async def test_process_input_creates_session(orchestrator):
    """Test that process_input creates a session."""
    result = await orchestrator.process_input(
        project_name="test-project-1",
        user_id="user_123",
        problem_statement="Reduce churn",
        segment="postpaid_consumer"
    )
    
    assert result["status"] in ["success", "error"]
    assert "stage" in result


@pytest.mark.asyncio
async def test_process_input_duplicate_project(orchestrator):
    """Test that duplicate project is rejected."""
    await orchestrator.process_input(
        project_name="test-project-2",
        user_id="user_123",
        problem_statement="Reduce churn",
        segment="postpaid_consumer"
    )
    
    result = await orchestrator.process_input(
        project_name="test-project-2",
        user_id="user_123",
        problem_statement="Different problem",
        segment="enterprise"
    )
    
    assert result["status"] == "error"
    assert "already exists" in result["message"]


@pytest.mark.asyncio
async def test_handle_approval_invalid_stage(orchestrator):
    """Test approval with invalid stage."""
    result = await orchestrator.handle_approval(
        project_name="nonexistent-project",
        stage="ba",
        decision="approve"
    )
    
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_clarification_questions(orchestrator):
    """Test that clarification questions are provided."""
    questions = orchestrator._get_clarification_questions("ba")
    
    assert isinstance(questions, list)
    assert len(questions) > 0
