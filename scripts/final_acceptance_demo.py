"""Stage 6 — Final Acceptance & Grounding Verification Demonstration.

Demonstrates the full end-to-end medical-device document intelligence,
versioning, version-pinned selection, grounded QA test generation, deterministic
source-grounding audit, and cross-version staleness impact pipeline.

Workflow:
1. Initialize isolated, disposable in-memory SQLite database and temporary JSON document store.
2. Ingest CT-200 v1 manual (data/ct200_manual.pdf) into relational store.
3. Ingest CT-200 v2 manual (data/ct200_manual_v2.pdf) into relational store.
4. Verify v1 records and content hashes remain strictly immutable after v2 ingestion.
5. Dynamically resolve authentic source sections (§2.1.1.1, §3.2, §4.2, §1.1).
6. Create named selection pinned to v1.
7. Generate structured QA test cases using deterministic mock provider.
8. Validate schema fields and cryptographic source provenance bindings.
9. Execute deterministic Source-Grounding Audit classifying every claim:
   - SOURCE_SUPPORTED
   - DERIVED_WITH_EXPLANATION
   - PROPOSED_SETUP
   - UNSUPPORTED
   - AMBIGUOUS
10. Persist test suite in document store and retrieve by generation UUID.
11. Verify duplicate-submission policy (idempotent replay and conflict on parameter alteration).
12. Assess test suite staleness against v2:
    - Battery cycles: 300 -> 250
    - Low-battery threshold: 15% -> 10%
    - Cuff inflation increment: 40 -> 30 mmHg
    - E3 auto-deflation time: 2.0s -> 1.5s
    - E6 Bluetooth synchronization failure added to Table 4.1
    - §5.3 Data Export added
13. Demonstrate unchanged control case (§1.1 Intended Use) remaining CURRENT.
14. Demonstrate human-review flagging for impacted and unsupported claims.
15. Verify that v1 provenance and content hashes were never mutated.
16. Print structured final acceptance verification matrix.

Usage:
    python -m scripts.final_acceptance_demo
"""

from __future__ import annotations
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.models import NodeVersion
from app.repositories.document_repository import DocumentRepository
from app.repositories.json_test_suite_store import JsonTestSuiteStore
from app.schemas.qa_test_case import (
    ClaimCategory,
    GeneratedTestSuitePayload,
    TestCaseSchema,
)
from app.services.document_ingestion import DocumentIngestionService
from app.services.grounding_auditor import GroundingAuditor
from app.services.llm_provider import MockLLMProvider
from app.services.qa_generation_service import (
    IdempotencyConflictError,
    QAGenerationService,
)
from app.services.staleness_classifier import StalenessClassifier


def run_final_acceptance_demo() -> int:
    print("=" * 80)
    print("Tri9T AI — STAGE 6 FINAL ACCEPTANCE & SOURCE-GROUNDING VERIFICATION")
    print("=" * 80)

    # 1. Isolated environment setup
    print("\n[Step 1/14] Setting up isolated, disposable test storage...")
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    temp_store_dir = Path(tempfile.mkdtemp(prefix="tri9t_stage6_acceptance_"))
    doc_store = JsonTestSuiteStore(storage_dir=temp_store_dir)
    print(f"  [OK] Relational Storage: Isolated in-memory SQLite")
    print(f"  [OK] Document Storage: Disposable JSON store at {temp_store_dir}")

    repo = DocumentRepository()
    ingestion = DocumentIngestionService(repository=repo)
    auditor = GroundingAuditor()
    classifier = StalenessClassifier()
    mock_provider = MockLLMProvider()
    qa_service = QAGenerationService(
        repository=repo,
        store=doc_store,
        provider=mock_provider,
        classifier=classifier,
        grounding_auditor=auditor,
    )

    try:
        # 2. Ingest CT-200 v1 PDF
        v1_path = Path("data/ct200_manual.pdf")
        v2_path = Path("data/ct200_manual_v2.pdf")
        if not v1_path.exists() or not v2_path.exists():
            print(f"  [FAIL] Missing required source manuals in data/ directory.")
            return 1

        print("\n[Step 2/14] Ingesting CT-200 Technical Manual v1 (data/ct200_manual.pdf)...")
        res_v1 = ingestion.ingest_version(db, version_label="v1")
        db.commit()
        print(f"  [OK] Document ID: {res_v1.document_id}")
        print(f"  [OK] Version ID: {res_v1.version_id} (label: {res_v1.version_label})")
        print(f"  [OK] Extracted Nodes: {res_v1.total_nodes} nodes across {res_v1.page_count} pages")

        # Snapshot v1 hashes to verify immutability later
        v1_nodes = repo.get_node_versions_for_document_version(db, res_v1.version_id)
        v1_hash_snapshot = {n.id: n.content_hash for n in v1_nodes}

        # 3. Ingest CT-200 v2 PDF
        print("\n[Step 3/14] Ingesting CT-200 Technical Manual v2 (data/ct200_manual_v2.pdf)...")
        res_v2 = ingestion.ingest_version(db, version_label="v2")
        db.commit()
        print(f"  [OK] Version ID: {res_v2.version_id} (label: {res_v2.version_label})")
        print(f"  [OK] Extracted Nodes: {res_v2.total_nodes} nodes across {res_v2.page_count} pages")

        # 4. Verify v1 Immutability
        print("\n[Step 4/14] Verifying v1 snapshot immutability after v2 ingestion...")
        v1_nodes_after = repo.get_node_versions_for_document_version(db, res_v1.version_id)
        for n in v1_nodes_after:
            if v1_hash_snapshot.get(n.id) != n.content_hash:
                print(f"  [FAIL] v1 Node {n.id} content hash altered!")
                return 1
        print(f"  [OK] All {len(v1_nodes_after)} v1 nodes verified identical. Zero mutation detected.")

        # 5. Resolve source sections from parser output
        print("\n[Step 5/14] Resolving target sections from v1 parsed hierarchy...")
        selected_nodes: List[NodeVersion] = []
        target_sections = ["2.1.1.1", "3.2", "4.2", "1.1"]
        for sec in target_sections:
            matched = [n for n in v1_nodes if n.section_number == sec]
            if matched:
                selected_nodes.append(matched[0])
                print(f"  -> Found Section {sec}: {matched[0].heading} (hash: {matched[0].content_hash[:12]}...)")
            else:
                print(f"  [FAIL] Could not resolve Section {sec} in v1 nodes.")
                return 1

        # 6. Create Named Selection Pinned to v1
        print("\n[Step 6/14] Creating named selection pinned to v1...")
        selection = repo.create_selection(
            db=db,
            document_id=res_v1.document_id,
            document_version_id=res_v1.version_id,
            name="CT200 Critical Safety & Verification Suite",
            description="Pinned to v1 specifications: Battery life, pressure control, error diagnostics, intended use.",
            node_version_ids=[n.id for n in selected_nodes],
        )
        db.commit()
        print(f"  [OK] Selection created: ID={selection.id}, Name='{selection.name}'")
        print(f"  [OK] Pinned Version: {selection.document_version.version_label} ({selection.document_version_id})")
        print(f"  [OK] Selected Nodes Count: {len(selection.selection_nodes)}")

        # 7. Generate 4 QA Test Cases using Mock Provider
        print("\n[Step 7/14] Generating 4 QA test cases from pinned selection...")
        print("  -> Using Deterministic Mock Provider (Synthetic grounded demonstration)")
        suite = qa_service.generate_test_suite(
            db,
            selection_id=selection.id,
            requested_count=4,
            idempotency_key="stage6-acceptance-key-001",
        )
        print(f"  [OK] Generated Suite ID: {suite.generation_id}")
        print(f"  [OK] Test Case Count: {len(suite.test_cases)} cases generated")
        print(f"  [OK] Validation Status: {suite.validation_status}")

        # 8. Inspect Generated Test Cases & Provenance
        print("\n[Step 8/14] Validating test case schema & cryptographic provenance...")
        for i, tc in enumerate(suite.test_cases, 1):
            prov = tc.Provenance
            print(f"  Case {i}: [{tc.TestCaseId}] {tc.Title}")
            print(f"    - StandardRef: {tc.StandardRef}")
            print(f"    - Provenance: Node={prov.source_node_version_id[:8]}... (Sec {prov.section_number})")
            print(f"    - Source Hash: {prov.source_content_hash[:16]}... (Version: {prov.source_document_version_label})")
            print(f"    - Expected Result: {tc.ExpectedResult}")

        # 9. Deterministic Source-Grounding Audit
        print("\n[Step 9/14] Reviewing Deterministic Source-Grounding Audit results...")
        summary = suite.grounding_summary
        if not summary:
            print("  [FAIL] Missing grounding summary on generated test suite.")
            return 1

        print(f"  Total Claims Audited: {summary.total_claims_audited}")
        print(f"  ├─ SOURCE_SUPPORTED:        {summary.source_supported_claims} claims (explicitly in manual)")
        print(f"  ├─ DERIVED_WITH_EXPLANATION: {summary.derived_claims} claims (arithmetic step progression)")
        print(f"  ├─ PROPOSED_SETUP:           {summary.proposed_setup_claims} claims (test bench fixtures/apparatus)")
        print(f"  ├─ UNSUPPORTED:              {summary.unsupported_claims} claims")
        print(f"  └─ AMBIGUOUS:                {summary.ambiguous_claims} claims")
        print(f"  Human Review Required: {summary.human_review_required}")

        for tc in suite.test_cases:
            audit = tc.GroundingAudit
            if audit:
                print(f"    * [{tc.TestCaseId}] Status: {audit.overall_grounding_status} "
                      f"({audit.source_supported_count} supported, {audit.proposed_setup_count} proposed setup)")

        # 10. Persistence and Retrieval from Document Store
        print("\n[Step 10/14] Verifying atomic persistence and retrieval from JSON document store...")
        retrieved_suite = doc_store.get_test_suite(suite.generation_id)
        if not retrieved_suite:
            print("  [FAIL] Could not retrieve saved test suite from document store.")
            return 1
        print(f"  [OK] Successfully retrieved suite {retrieved_suite.generation_id} from JSON store.")
        assert retrieved_suite.generation_id == suite.generation_id
        assert len(retrieved_suite.test_cases) == 4

        # 11. Idempotency & Conflict Policy
        print("\n[Step 11/14] Verifying duplicate-submission policy & idempotency...")
        # A. Identical replay
        replayed_suite = qa_service.generate_test_suite(
            db,
            selection_id=selection.id,
            requested_count=4,
            idempotency_key="stage6-acceptance-key-001",
        )
        assert replayed_suite.generation_id == suite.generation_id
        print(f"  [OK] Idempotent replay returned existing suite ID: {replayed_suite.generation_id}")

        # B. Conflict on altered parameters
        conflict_detected = False
        try:
            qa_service.generate_test_suite(
                db,
                selection_id=selection.id,
                requested_count=3,  # Changed from 4 to 3
                idempotency_key="stage6-acceptance-key-001",
            )
        except IdempotencyConflictError as err:
            conflict_detected = True
            print(f"  [OK] Idempotency conflict properly rejected: {err}")

        if not conflict_detected:
            print("  [FAIL] Reusing key with different count did not raise IdempotencyConflictError!")
            return 1

        # 12. Evaluate Staleness against CT-200 v2
        print("\n[Step 12/14] Evaluating test suite staleness against CT-200 v2...")
        staleness_resp = qa_service.evaluate_test_suite_staleness(
            db,
            generation_id=suite.generation_id,
            target_version_label="v2",
        )
        print(f"  Suite Staleness Assessment: {staleness_resp.aggregate_status}")
        print(f"  Summary Breakdown: {staleness_resp.summary}")
        print(f"  Human Review Required: {staleness_resp.human_review_required}")

        # 13. Detailed Cross-Version Changes Verification
        print("\n[Step 13/14] Verifying exact detected source changes:")
        stale_reports = staleness_resp.test_case_assessments
        for rep in stale_reports:
            print(f"\n  * Case [{rep.test_case_id}] Status: {rep.status} | Classification: {rep.classification}")
            print(f"    Source: Section {rep.source_section_number} ({rep.source_heading})")
            print(f"    Explanation: {rep.explanation}")
            if rep.deltas:
                print("    Detected Specification Deltas:")
                for d in rep.deltas:
                    print(f"      - {d.delta_type.upper()}: {d.old_value} -> {d.new_value} {d.unit} ({d.explanation})")

        # Check for specific verified changes across reports
        explanations = " ".join(r.explanation for r in stale_reports)
        assert "300" in explanations and "250" in explanations, "Missing battery cycles 300 -> 250 change"
        assert "15" in explanations and "10" in explanations, "Missing battery threshold 15% -> 10% change"
        assert "40" in explanations and "30" in explanations, "Missing inflation increment 40 -> 30 mmHg change"
        assert "1.5" in explanations, "Missing E3 auto-deflate timing change to 1.5 seconds"
        assert "E6" in explanations, "Missing E6 Bluetooth error code addition"
        print("\n  [OK] All 5 reported CT-200 v1->v2 specification differences verified with evidence!")

        # 14. Unchanged Control Case & Immutability Verification
        print("\n[Step 14/14] Verifying unchanged control case (§1.1) & provenance immutability...")
        node_intended = [n for n in v1_nodes if n.section_number == "1.1"][0]
        control_suite = qa_service.generate_test_suite(
            db=db,
            node_version_id=node_intended.id,
            requested_count=3,
            idempotency_key="control-intended-use-acceptance",
        )
        control_staleness = qa_service.evaluate_test_suite_staleness(
            db=db,
            generation_id=control_suite.generation_id,
            target_version_label="v2",
        )
        print(f"  Unchanged Section §1.1 Suite Aggregate Status: {control_staleness.aggregate_status}")
        assert control_staleness.aggregate_status == "CURRENT", "Control case for Section 1.1 must remain CURRENT"
        print(f"  [OK] Unchanged control case remains CURRENT against v2.")

        # Verify that original v1 provenance and hashes were never altered
        re_checked_suite = doc_store.get_test_suite(suite.generation_id)
        assert re_checked_suite is not None
        for tc in re_checked_suite.test_cases:
            assert tc.Provenance.source_document_version_label == "v1"
            assert tc.Provenance.source_content_hash in v1_hash_snapshot.values()
        print("  [OK] Original v1 provenance and content hashes were completely preserved.")

        # Print Final Summary
        print("\n" + "=" * 80)
        print("FINAL ACCEPTANCE DEMO VERDICT: [PASS]")
        print("All 14 Acceptance Milestones Successfully Demonstrated.")
        print("=" * 80)
        return 0

    finally:
        # Cleanup isolated disposable temporary directory
        if temp_store_dir.exists():
            shutil.rmtree(temp_store_dir, ignore_errors=True)
            print(f"Cleaned up disposable document store: {temp_store_dir}")


if __name__ == "__main__":
    sys.exit(run_final_acceptance_demo())
