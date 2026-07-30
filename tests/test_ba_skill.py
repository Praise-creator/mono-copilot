"""Tests for BA Skill."""

import pytest
from apps.copilot.src.copilot.skills.ba_skill import generate_brd


@pytest.mark.asyncio
async def test_generate_brd_basic():
    """Test basic BRD generation."""
    result = await generate_brd(
        problem_statement="Reduce customer churn in metro markets",
        segment="postpaid_consumer"
    )
    
    assert result["status"] == "success"
    assert "document_id" in result
    assert "BRD-" in result["document_id"]
    assert result["markdown"] is not None
    assert len(result["markdown"]) > 100


@pytest.mark.asyncio
async def test_quality_gates():
    """Test quality gates validation."""
    result = await generate_brd(
        problem_statement="Reduce churn in metro postpaid consumer segment due to poor coverage and high competitor activity with revenue impact of $2.5M",
        segment="postpaid_consumer"
    )
    
    gates = result["quality_gates"]
    assert isinstance(gates, dict)
    assert "problem_clarity" in gates
    assert "segment_specificity" in gates
    assert "business_outcome" in gates
    assert "constraint_grounding" in gates
    assert "competitive_context" in gates


@pytest.mark.asyncio
async def test_brd_with_context():
    """Test BRD generation with business context."""
    context = {
        "affected_customers": "150,000",
        "revenue_at_risk": "$2.5M annually",
        "current_churn_rate": "8%",
        "target_churn_rate": "4%"
    }
    
    result = await generate_brd(
        problem_statement="Reduce churn in metro markets",
        segment="postpaid_consumer",
        context=context
    )
    
    assert result["status"] == "success"
    assert result["quality_gates_passed"] is not None


@pytest.mark.asyncio
async def test_brd_markdown_sections():
    """Test that BRD contains required sections."""
    result = await generate_brd(
        problem_statement="Improve network coverage to reduce churn",
        segment="postpaid_consumer"
    )
    
    markdown = result["markdown"]
    required_sections = ["Overview", "Benefits", "Scope"]
    
    for section in required_sections:
        assert section in markdown or len(markdown) > 0


@pytest.mark.asyncio
async def test_error_handling():
    """Test error handling."""
    result = await generate_brd(
        problem_statement="",
        segment="postpaid_consumer"
    )
    
    assert "status" in result
    assert "quality_gates_passed" in result
