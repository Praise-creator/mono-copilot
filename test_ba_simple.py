#!/usr/bin/env python3
"""
Simple BA Skill Test - Shows BA working in terminal
"""

import asyncio
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from copilot.skills.ba_skill import BASkill


async def test_ba_simple():
    """Run a simple BA test and show results."""
    
    print("\nBA SKILL TEST")
    print("-" * 80)
    
    skill = BASkill()
    
    problem = """
    Reduce customer churn in metro markets.
    
    Current process: Customer calls, IVR routes to agent, agent reviews account manually.
    Bottleneck: Agent decision time averages 45 seconds, 15 percent of customers abandon.
    
    Proposed: AI analyzes customer data before agent call, agent sees recommendation.
    Expected: Decision time drops to 20 seconds, abandon rate drops to 5 percent.
    
    Integrations: CRM (customer data), AI Engine (recommendation), IVR (Genesys), Agent Portal.
    
    Exception: If CRM unavailable, show cached data. If AI timeout exceeds 5 seconds, use rule-based offer.
    
    Rules: Customer must be active, agent can only see offers for territory, approval needed for offers over 500 dollars.
    """
    
    print("\nProblem Statement:")
    print(problem.strip())
    
    print("\n" + "-" * 80)
    print("Generating BRD with BA Skill...")
    print("-" * 80 + "\n")
    
    try:
        result = await skill.generate_brd(
            problem_statement=problem,
            segment="postpaid_consumer",
            context={
                "bottleneck": "Agent decision time averages 45 seconds",
                "systems_involved": ["CRM", "AI Engine", "IVR", "Agent Portal"]
            }
        )
        
        if result.get("status") == "success":
            print("Status: SUCCESS\n")
            
            print("Document ID:", result.get("document_id"))
            print("File Path:", result.get("file_path"))
            print("Sources Verified:", result.get("sources_verified_count"))
            print("Run Count:", result.get("run_count"))
            
            print("\nQuality Gates:")
            for gate, status in result.get("quality_gates", {}).items():
                status_str = "PASS" if status else "FAIL"
                print(f"  {gate}: {status_str}")
            
            overall = "PASS" if result.get("quality_gates_passed") else "FAIL"
            print(f"\nOverall Quality Gates: {overall}")
            
            print("\nBRD Preview (first 1000 characters):")
            print("-" * 80)
            markdown = result.get("markdown", "")
            print(markdown[:1000])
            if len(markdown) > 1000:
                print("\n... (BRD continues)")
            
            print("\nVerified References Section:")
            print("-" * 80)
            if "Verified References" in markdown:
                lines = markdown.split("\n")
                in_refs = False
                for line in lines:
                    if "Verified References" in line:
                        in_refs = True
                    if in_refs:
                        print(line)
                        if line.startswith("---"):
                            break
            else:
                print("(No verified references found)")
            
            print("\n" + "-" * 80)
            print("BA Skill Test Complete")
            print("-" * 80)
            
        else:
            print("Status: FAILED")
            print("Error:", result.get("error"))
    
    except Exception as e:
        print(f"Exception: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_ba_simple())
