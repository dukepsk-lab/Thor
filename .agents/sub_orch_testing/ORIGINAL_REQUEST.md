# Original User Request

## 2026-06-19T05:14:05Z

You are the E2E Testing Orchestrator for the ML Trading System Validation Harness project.
Your working directory is c:\Users\swing\Desktop\TRADING\Thor\.agents\sub_orch_testing\.
Your scope is to design the comprehensive opaque-box test suite for the validation harness, derived from user requirements in c:\Users\swing\Desktop\TRADING\Thor\ORIGINAL_REQUEST.md.

Please do the following:
1. Create your directory c:\Users\swing\Desktop\TRADING\Thor\.agents\sub_orch_testing\ and maintain BRIEFING.md, plan.md, progress.md, context.md, and SCOPE.md there.
2. Implement the test cases using a systematic 4-tier approach (Tier 1: Feature Coverage, Tier 2: Boundary/Corner Cases, Tier 3: Cross-Feature Combinations, Tier 4: Real-World Workloads) under c:\Users\swing\Desktop\TRADING\Thor\validation_harness\tests\.
3. Publish TEST_READY.md under c:\Users\swing\Desktop\TRADING\Thor\.agents\orchestrator\ (since the parent orchestrator reads from here) and also at c:\Users\swing\Desktop\TRADING\Thor\validation_harness\TEST_READY.md if possible.
4. Work with workers/reviewers to verify that your test runner can run all the tests.
5. Set up the E2E Test Suite and let the parent know when TEST_READY.md is generated.

Do NOT write source code for the actual validation harness modules (ingestion.py, cpcv.py, metrics.py) - only the test suite files under validation_harness/tests/.
Follow all rules and constraints of the Project Pattern.
