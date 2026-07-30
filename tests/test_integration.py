"""Integration tests for complete workflow."""

import pytest
from apps.copilot.src.copilot.orchestrator import Orchestrator


@pytest.mark.asyncio
async def test_full_workflow_ba_to_approval():
    """Test complete BA workflow from start to approval."""
    orchestrator = Orchestrator()
    
    result = await orchestrator.process_input(
        project_name="integration-test-1",
        user_id="test_user",
        problem_statement="Reduce customer churn in metro markets due to poor network coverage and competitor pressure",
        segment="postpaid_consumer",
        context={
            "affected_customers": "150,000",
            "revenue_at_risk": "$2.5M annually"
        }
    )
    
    assert result["status"] == "success"
    assert result["stage"] == "ba_approval"
    assert "document_id" in result
    assert result["output"] is not None


@pytest.mark.asyncio
async def test_approval_workflow():
    """Test approval decision workflow."""
    orchestrator = Orchestrator()
    
    project_name = "approval-test-1"
    
    await orchestrator.process_input(
        project_name=project_name,
        user_id="test_user",
        problem_statement="Improve network coverage",
        segment="postpaid_consumer"
    )
    
    approval_result = await orchestrator.handle_approval(
        project_name=project_name,
        stage="ba",
        decision="needs_changes",
        feedback="Add more specific metrics"
    )
    
    assert approval_result["status"] == "success"
    assert approval_result["stage"] == "ba_clarifying"


@pytest.mark.asyncio
async def test_project_status():
    """Test getting project status."""
    orchestrator = Orchestrator()
    
    project_name = "status-test-1"
    
    await orchestrator.process_input(
        project_name=project_name,
        user_id="test_user",
        problem_statement="Test problem",
        segment="postpaid_consumer"
    )
    
    session = orchestrator.context_manager.get_session(project_name)
    
    assert session is not None
    assert session["stage"] == "ba_approval"
    assert session["problem_statement"] == "Test problem"
