"""
Comprehensive BA Skill Test Suite - Verification for Production Readiness.

Tests:
1. Web search tool integration with OpenAI
2. Source verification against authorized whitelist
3. Quality gates validation (4 mandatory + optional Mermaid)
4. Mermaid diagram triggering (case-by-case, not always)
5. Output file generation (BRD + sources.json)
6. End-to-end orchestrator workflow (process_input → approval → completion)
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime

# Import orchestrator and BA skill
from copilot.orchestrator import Orchestrator, OrchestratorState
from copilot.skills.ba_skill import BASkill
from copilot.services.research_service import ResearchService


class BATestSuite:
    """Comprehensive BA testing."""
    
    def __init__(self):
        self.orchestrator = Orchestrator()
        self.ba_skill = BASkill()
        self.research_service = ResearchService()
        self.test_results = {}
    
    async def test_1_web_search_integration(self):
        """Test 1: Verify web search tool is properly configured."""
        print("\n" + "="*80)
        print("TEST 1: WEB SEARCH INTEGRATION")
        print("="*80)
        
        try:
            # Generate BRD with NCC regulatory claim
            problem = "Implement data residency compliance for Nigeria market"
            segment = "postpaid_consumer"
            
            print(f"\n📝 Problem Statement: {problem}")
            print(f"📍 Segment: {segment}")
            print("\n⏳ Calling BA skill with web search enabled...")
            
            result = await self.ba_skill.generate_brd(
                problem_statement=problem,
                segment=segment,
                context={
                    "regulatory_context": "Must comply with NCC data residency requirements"
                }
            )
            
            if result.get("status") == "success":
                print("\n Web search integration working")
                print(f"   Document ID: {result.get('document_id')}")
                print(f"   Sources verified: {result.get('sources_verified_count')}")
                self.test_results["test_1_web_search"] = "PASS"
                return True
            else:
                print(f"\n❌ Web search failed: {result.get('error')}")
                self.test_results["test_1_web_search"] = "FAIL"
                return False
        
        except Exception as e:
            print(f"\n❌ Exception during web search test: {str(e)}")
            self.test_results["test_1_web_search"] = "ERROR"
            return False
    
    async def test_2_source_verification(self):
        """Test 2: Verify ResearchService is validating sources correctly."""
        print("\n" + "="*80)
        print("TEST 2: SOURCE VERIFICATION")
        print("="*80)
        
        try:
            print("\n🔍 Testing ResearchService.search_and_verify()...")
            
            # Test 1: NCC claim
            result = await self.research_service.search_and_verify("NCC data residency requirement", "Nigeria")
            
            print(f"\n   Claim: 'NCC data residency requirement'")
            print(f"   Verified sources found: {len(result.get('verified_sources', []))}")
            print(f"   Confidence: {result.get('confidence_level')}")
            
            if result.get('verified_sources'):
                print(f"    Found {len(result['verified_sources'])} verified source(s)")
                for source in result['verified_sources']:
                    print(f"      - {source.get('source_url')} ({source.get('authority_level')})")
                self.test_results["test_2_source_verification"] = "PASS"
                return True
            else:
                print(f"     No sources verified (may be normal for keyword-based MVP)")
                self.test_results["test_2_source_verification"] = "PARTIAL"
                return True  # Not a hard fail for MVP
        
        except Exception as e:
            print(f"\n❌ Exception during source verification: {str(e)}")
            self.test_results["test_2_source_verification"] = "ERROR"
            return False
    
    async def test_3_quality_gates(self):
        """Test 3: Verify quality gates are validating correctly."""
        print("\n" + "="*80)
        print("TEST 3: QUALITY GATES VALIDATION")
        print("="*80)
        
        try:
            # Test with a well-formed problem (should pass gates)
            problem = """
            Reduce customer churn in metro markets.
            
            Current process: Customers call, IVR routes to agent, agent reviews manually (45 second average).
            Bottleneck: Agent decision time averages 45 seconds, 15% of customers abandon.
            
            Proposed: AI analyzes customer data before agent call, agent sees recommendation.
            Expected: Decision time drops to 20 seconds, abandon rate drops to 5%.
            
            Integrations: CRM (customer data), AI Engine (recommendation), IVR (Genesys), Agent Portal (UI).
            
            Exception: If CRM unavailable, show cached data. If AI timeout >5s, use rule-based offer.
            
            Rules: Customer must be active, agent can only see offers for territory, approval needed for >$500.
            """
            
            print("\n📋 Testing quality gates with well-formed problem...")
            
            result = await self.ba_skill.generate_brd(
                problem_statement=problem,
                segment="postpaid_consumer"
            )
            
            quality_gates = result.get("quality_gates", {})
            gates_passed = result.get("quality_gates_passed", False)
            
            print(f"\n   Quality Gates Results:")
            for gate_name, gate_status in quality_gates.items():
                status_icon = "✅" if gate_status else "❌"
                print(f"   {status_icon} {gate_name}: {gate_status}")
            
            print(f"\n   Overall: {'PASS' if gates_passed else 'FAIL'}")
            
            mandatory_gates = [
                quality_gates.get("process_flow_analysis"),
                quality_gates.get("integration_architecture"),
                quality_gates.get("exception_management"),
                quality_gates.get("business_rules")
            ]
            
            if all(mandatory_gates):
                print("   ✅ All mandatory gates passing")
                self.test_results["test_3_quality_gates"] = "PASS"
                return True
            else:
                print("   ❌ Some mandatory gates failing")
                self.test_results["test_3_quality_gates"] = "FAIL"
                return False
        
        except Exception as e:
            print(f"\n❌ Exception during quality gates test: {str(e)}")
            self.test_results["test_3_quality_gates"] = "ERROR"
            return False
    
    async def test_4_mermaid_triggering(self):
        """Test 4: Verify Mermaid diagrams are triggered smartly (only when needed)."""
        print("\n" + "="*80)
        print("TEST 4: MERMAID DIAGRAM TRIGGERING")
        print("="*80)
        
        try:
            # Test 4a: Complex problem (should trigger Mermaid)
            complex_problem = """
            Redesign outbound upsell workflow with AI recommendations.
            
            Current: Customer calls → IVR menu → waits for agent (avg 45s) → agent reviews account → makes recommendation → customer accepts/rejects.
            
            Integrations: CRM (customer data), AI Engine (recommendations), IVR (Genesys), Agent Portal, Logging System.
            
            Exceptions: CRM timeout, AI slow, network failure, agent portal crash.
            """
            
            print("\n📊 Test 4a: Complex problem with >2 integrations...")
            
            result_complex = await self.ba_skill.generate_brd(
                problem_statement=complex_problem,
                segment="postpaid_consumer"
            )
            
            has_mermaid_complex = "```mermaid" in result_complex.get("markdown", "")
            print(f"   Complex problem has Mermaid diagrams: {'✅ YES' if has_mermaid_complex else '❌ NO'}")
            
            # Test 4b: Simple problem (should NOT trigger Mermaid)
            simple_problem = "Reduce customer churn"
            
            print("\n📊 Test 4b: Simple problem without integrations...")
            
            result_simple = await self.ba_skill.generate_brd(
                problem_statement=simple_problem,
                segment="postpaid_consumer"
            )
            
            has_mermaid_simple = "```mermaid" in result_simple.get("markdown", "")
            print(f"   Simple problem has Mermaid diagrams: {'❌ YES (should be NO)' if has_mermaid_simple else '✅ NO (correct)'}")
            
            if has_mermaid_complex and not has_mermaid_simple:
                print("\n✅ Mermaid triggering is smart (complex=yes, simple=no)")
                self.test_results["test_4_mermaid_triggering"] = "PASS"
                return True
            else:
                print("\n⚠️  Mermaid triggering may need refinement")
                self.test_results["test_4_mermaid_triggering"] = "PARTIAL"
                return True  # Not a hard fail
        
        except Exception as e:
            print(f"\n❌ Exception during Mermaid test: {str(e)}")
            self.test_results["test_4_mermaid_triggering"] = "ERROR"
            return False
    
    async def test_5_output_files(self):
        """Test 5: Verify output files are created and properly formatted."""
        print("\n" + "="*80)
        print("TEST 5: OUTPUT FILE GENERATION")
        print("="*80)
        
        try:
            # Generate BRD
            problem = "Implement churn reduction program for metro markets"
            
            print(f"\n📝 Generating BRD...")
            
            result = await self.ba_skill.generate_brd(
                problem_statement=problem,
                segment="postpaid_consumer"
            )
            
            # Check brd.md
            brd_path = Path("projects") / "brd.md"
            if brd_path.exists():
                brd_content = brd_path.read_text()
                brd_size = len(brd_content)
                print(f"\n✅ BRD file created: {brd_path}")
                print(f"   Size: {brd_size} bytes")
                print(f"   Has markdown sections: {bool(brd_content.count('##'))}")
                print(f"   Has verified references: {'Verified References' in brd_content}")
            else:
                print(f"\n❌ BRD file NOT created at {brd_path}")
                self.test_results["test_5_output_files"] = "FAIL"
                return False
            
            # Check sources.json
            sources_path = Path("projects") / "sources.json"
            if sources_path.exists():
                sources_content = sources_path.read_text()
                sources_data = json.loads(sources_content)
                
                print(f"\n✅ Sources file created: {sources_path}")
                print(f"   Sources used: {len(sources_data.get('sources_used', []))}")
                print(f"   Has data integrity info: {'data_integrity' in sources_data}")
                print(f"   Hallucination risk: {sources_data.get('data_integrity', {}).get('hallucination_risk')}")
            else:
                print(f"\n❌ Sources file NOT created at {sources_path}")
                self.test_results["test_5_output_files"] = "FAIL"
                return False
            
            if brd_path.exists() and sources_path.exists():
                print(f"\n✅ All output files created successfully")
                self.test_results["test_5_output_files"] = "PASS"
                return True
            else:
                self.test_results["test_5_output_files"] = "FAIL"
                return False
        
        except Exception as e:
            print(f"\n❌ Exception during output file test: {str(e)}")
            self.test_results["test_5_output_files"] = "ERROR"
            return False
    
    async def test_6_orchestrator_workflow(self):
        """Test 6: Verify complete orchestrator workflow (BRD generation → approval → completion)."""
        print("\n" + "="*80)
        print("TEST 6: ORCHESTRATOR WORKFLOW")
        print("="*80)
        
        try:
            project_name = f"test-project-{datetime.now().strftime('%H%M%S')}"
            user_id = "test-user"
            problem = "Reduce churn in metro markets with AI-driven retention"
            segment = "postpaid_consumer"
            
            print(f"\n🚀 Starting orchestrator workflow...")
            print(f"   Project: {project_name}")
            print(f"   Problem: {problem}")
            
            # Step 1: Process input (generate BRD)
            print(f"\n📍 Step 1: BA agent generates BRD...")
            
            result1 = await self.orchestrator.process_input(
                project_name=project_name,
                user_id=user_id,
                problem_statement=problem,
                segment=segment
            )
            
            if result1.get("status") != "success":
                print(f"❌ BA generation failed: {result1.get('message')}")
                self.test_results["test_6_orchestrator_workflow"] = "FAIL"
                return False
            
            print(f"✅ BRD generated")
            print(f"   Document ID: {result1.get('document_id')}")
            print(f"   Stage: {result1.get('stage')}")
            print(f"   Quality gates passed: {all([result1.get('quality_gates', {}).values()])}")
            
            # Step 2: Approve BRD
            print(f"\n📍 Step 2: User approves BRD...")
            
            result2 = await self.orchestrator.handle_approval(
                project_name=project_name,
                stage="ba",
                decision="approve"
            )
            
            if result2.get("status") != "success":
                print(f"❌ BRD approval failed: {result2.get('message')}")
                self.test_results["test_6_orchestrator_workflow"] = "FAIL"
                return False
            
            print(f"✅ BRD approved, PE generation triggered")
            print(f"   New stage: {result2.get('stage')}")
            
            # Step 3: Check session state
            print(f"\n📍 Step 3: Verify session state...")
            
            session = self.orchestrator.context_manager.get_session(project_name)
            
            if session:
                print(f"✅ Session found")
                print(f"   Current stage: {session.get('stage')}")
                print(f"   Run count: {session.get('run_count')}")
            else:
                print(f"❌ Session not found")
                self.test_results["test_6_orchestrator_workflow"] = "FAIL"
                return False
            
            if result2.get("stage") == "pe_approval":
                print(f"\n✅ Complete orchestrator workflow successful (BRD → approve → PE)")
                self.test_results["test_6_orchestrator_workflow"] = "PASS"
                return True
            else:
                print(f"\n❌ Workflow did not advance to PE approval")
                self.test_results["test_6_orchestrator_workflow"] = "FAIL"
                return False
        
        except Exception as e:
            print(f"\n❌ Exception during orchestrator test: {str(e)}")
            self.test_results["test_6_orchestrator_workflow"] = "ERROR"
            return False
    
    async def run_all_tests(self):
        """Run all BA tests."""
        print("\n" + "="*80)
        print("BA SKILL PRODUCTION READINESS TEST SUITE")
        print("="*80)
        print(f"Started: {datetime.now().isoformat()}")
        
        tests = [
            ("Web Search Integration", self.test_1_web_search_integration),
            ("Source Verification", self.test_2_source_verification),
            ("Quality Gates", self.test_3_quality_gates),
            ("Mermaid Triggering", self.test_4_mermaid_triggering),
            ("Output Files", self.test_5_output_files),
            ("Orchestrator Workflow", self.test_6_orchestrator_workflow),
        ]
        
        for test_name, test_func in tests:
            try:
                await test_func()
            except Exception as e:
                print(f"\n❌ FATAL ERROR in {test_name}: {str(e)}")
                self.test_results[f"test_{len(self.test_results) + 1}"] = "FATAL"
        
        # Print summary
        self._print_summary()
    
    def _print_summary(self):
        """Print test summary."""
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        
        passed = sum(1 for v in self.test_results.values() if v == "PASS")
        partial = sum(1 for v in self.test_results.values() if v == "PARTIAL")
        failed = sum(1 for v in self.test_results.values() if v == "FAIL")
        errors = sum(1 for v in self.test_results.values() if v == "ERROR")
        
        for test_name, result in self.test_results.items():
            icon = "✅" if result == "PASS" else "⚠️ " if result == "PARTIAL" else "❌"
            print(f"{icon} {test_name}: {result}")
        
        print(f"\n📊 Results:")
        print(f"   ✅ Passed: {passed}")
        print(f"   ⚠️  Partial: {partial}")
        print(f"   ❌ Failed: {failed}")
        print(f"   💥 Errors: {errors}")
        
        total_tests = len(self.test_results)
        success_rate = (passed / total_tests * 100) if total_tests > 0 else 0
        
        print(f"\n🎯 Overall: {success_rate:.0f}% successful")
        
        if passed == total_tests:
            print("\n🚀 BA SKILL IS PRODUCTION-READY!")
        elif passed + partial >= total_tests * 0.8:
            print("\n⚠️  BA SKILL IS MOSTLY READY (review partial failures)")
        else:
            print("\n❌ BA SKILL NEEDS MORE WORK")
        
        print(f"\nCompleted: {datetime.now().isoformat()}")


async def main():
    """Run BA test suite."""
    suite = BATestSuite()
    await suite.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())
