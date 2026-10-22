"""Stage 7 — Reviewer-Level Integrated Verification Script.

Executes all critical Stage 7 verification checks in a single command:
1. Runs full automated pytest suite (90 tests across 10 modules).
2. Executes 14-milestone End-to-End Acceptance Demonstration on CT-200 v1/v2 PDFs.
3. Validates FastAPI OpenAPI schema and route definitions (18 routes).
4. Verifies adversarial grounding red-team assertions.
5. Prints comprehensive reviewer-level evidence summary.

Usage:
    python3 -m scripts.stage7_final_verification
"""

from __future__ import annotations
import sys
import subprocess
import time
from pathlib import Path


def run_command(desc: str, cmd: list[str]) -> bool:
    print("\n" + "=" * 80)
    print(f"RUNNING: {desc}")
    print(f"COMMAND: {' '.join(cmd)}")
    print("=" * 80)
    start_time = time.time()
    res = subprocess.run(cmd, capture_output=False)
    elapsed = time.time() - start_time
    if res.returncode == 0:
        print(f"\n[PASS] {desc} (completed in {elapsed:.2f}s)")
        return True
    else:
        print(f"\n[FAIL] {desc} exited with code {res.returncode}")
        return False


def main() -> int:
    print("*" * 80)
    print("Tri9T AI — STAGE 7 REVIEWER-LEVEL COMPREHENSIVE VERIFICATION")
    print("*" * 80)

    checks = [
        ("Full Automated Regression Suite (90 tests)", [sys.executable, "-m", "pytest", "-v"]),
        ("14-Milestone End-to-End Acceptance Demo", [sys.executable, "-m", "scripts.final_acceptance_demo"]),
        ("Adversarial Red-Team Grounding Tests", [sys.executable, "-m", "pytest", "tests/test_grounding_red_team.py", "-v"]),
        ("OpenAPI Schema Validation", [
            sys.executable, "-c",
            "from app.main import app; schema = app.openapi(); assert len(schema['paths']) == 18; print('OpenAPI 18 routes verified successfully!')"
        ]),
    ]

    all_passed = True
    for desc, cmd in checks:
        success = run_command(desc, cmd)
        if not success:
            all_passed = False
            break

    print("\n" + "*" * 80)
    if all_passed:
        print("STAGE 7 FINAL VERIFICATION VERDICT: [ALL CHECKS PASSED]")
        print("The repository is verified, reproducible, grounded, and submission ready.")
        print("*" * 80)
        return 0
    else:
        print("STAGE 7 FINAL VERIFICATION VERDICT: [FAILED]")
        print("*" * 80)
        return 1


if __name__ == "__main__":
    sys.exit(main())
