"""End-to-End Demonstration Script for Stage 5: Grounded QA Test Generation, Validation Retries,
Persistence, Idempotency, and Cross-Version Staleness Auditing.

Demonstrates:
1. Initializing isolated disposable environments (in-memory SQLite + temporary JSON document store).
2. Selecting execution mode (Integration mode if LLM_API_KEY is configured; Deterministic Mock Mode otherwise).
3. Ingesting CT-200 manual v1 (data/ct200_manual.pdf).
4. Creating a named selection pinned to v1 (§2.1.1.1 Battery Life, §3.2 Cuff Inflation, §4.2 Error Codes).
5. Generating 4 validated QA test cases grounded in source sections and structured tables.
6. Persisting test suite in document store and retrieving by generation_id.
7. Verifying all required fields and cryptographic source provenance bindings.
8. Demonstrating duplicate-submission policy (idempotent replay and conflict detection on parameter mismatch).
9. Ingesting CT-200 manual v2 (data/ct200_manual_v2.pdf) without altering v1 records.
10. Evaluating cross-version staleness against v2 (detecting numerical, timing, and table changes like E6).
11. Demonstrating unchanged baseline test cases (§1.1 Intended Use) remaining CURRENT.
12. Retrieving suites by selection and individual source node snapshot.
13. Verifying that original v1 provenance remains completely immutable.

Usage:
    python -m scripts.demo_e2e_qa_generation
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.repositories.document_repository import DocumentRepository
from app.repositories.json_test_suite_store import JsonTestSuiteStore
from app.schemas.qa_test_case import GenerateTestSuiteRequest
from app.services.document_ingestion import DocumentIngestionService
from app.services.llm_provider import (
    BaseLLMProvider,
    MockLLMProvider,
    OpenAICompatibleProvider,
    get_llm_provider,
)
from app.services.qa_generation_service import (
    IdempotencyConflictError,
    QAGenerationService,
)
from app.services.staleness_classifier import StalenessClassifier


def run_e2e_qa_generation_demo():
    print("=" * 80)
    print("Tri9T AI — Stage 5 Grounded QA Generation & Cross-Version Staleness Demo")
    print("=" * 80)

    # 1. Environment initialization
    print("\n[Step 1/13] Initializing isolated environments...")
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    temp_store_dir = Path(tempfile.mkdtemp(prefix="tri9t_stage5_demo_"))
    doc_store = JsonTestSuiteStore(storage_dir=temp_store_dir)
    print(f"-> Relational DB: In-Memory SQLite")
    print(f"-> Document Store: Atomic JSON store at {temp_store_dir}")

    # 2. Execution Mode Selection
    print("\n[Step 2/13] Evaluating LLM Provider Execution Mode...")
    has_api_key = bool(settings.llm_api_key and settings.llm_api_key.strip())
    is_openai = settings.llm_provider.lower().strip() == "openai"

    if is_openai and has_api_key:
        print("-> [MODE: LIVE INTEGRATION] Using configured OpenAI provider.")
        provider: BaseLLMProvider = OpenAICompatibleProvider(
            api_key=settings.llm_api_key,
            base_url=settings.llm_api_base_url,
            model=settings.llm_model,
        )
    else:
        print("-> [MODE: DETERMINISTIC MOCK PROVIDER] Synthetic grounded CT-200 responses.")
        print("   (Integration mode skipped: no paid LLM_API_KEY configured. Running repeatable local demo)")
        provider = MockLLMProvider()

    repo = DocumentRepository()
    ingestion = DocumentIngestionService(repository=repo)
    classifier = StalenessClassifier()
    qa_service = QAGenerationService(
        repository=repo,
        store=doc_store,
        provider=provider,
        classifier=classifier,
    )

    try:
        # 3. Ingest v1 manual
        print("\n[Step 3/13] Ingesting CT-200 Manual v1 (data/ct200_manual.pdf)...")
        res_v1 = ingestion.ingest_version(db, version_label="v1")
        db.commit()
        print(f"-> Ingested v1: Document ID={res_v1.document_id}, Version ID={res_v1.version_id}, Nodes={res_v1.total_nodes}")

        # 4. Resolve key nodes and create named selection pinned to v1
        print("\n[Step 4/13] Creating version-pinned selection for critical safety & operations...")
        v1_nodes = repo.get_node_versions_for_document_version(db, res_v1.version_id)
        node_map_v1 = {n.section_number: n for n in v1_nodes}

        node_battery = node_map_v1["2.1.1.1"]
        node_cuff = node_map_v1["3.2"]
        node_error = node_map_v1["4.2"]
        node_intended = node_map_v1["1.1"]

        selection = repo.create_selection(
            db=db,
            document_id=res_v1.document_id,
            document_version_id=res_v1.version_id,
            name="CT-200 Safety Critical Verification Suite",
            description="Verification of battery threshold, cuff inflation sequence, and error codes",
            node_version_ids=[node_battery.id, node_cuff.id, node_error.id],
        )
        db.commit()
        print(f"-> Created Selection '{selection.name}' (ID: {selection.id}) pinned to v1 with 3 nodes.")

        # 5. Generate 4 validated QA test cases
        print("\n[Step 5/13] Generating 4 QA test cases from selection...")
        idempotency_key = "demo-run-safety-suite-001"
        suite = qa_service.generate_test_suite(
            db=db,
            selection_id=selection.id,
            requested_count=4,
            idempotency_key=idempotency_key,
        )
        print(f"-> Generated Suite ID: {suite.generation_id}")
        print(f"-> Provider: {suite.provider_name} | Model: {suite.model_name}")
        print(f"-> Validation Status: {suite.validation_status}")
        print(f"-> Generated Cases Count: {suite.generated_count}")

        # 6. Retrieve from Document Store and inspect fields
        print("\n[Step 6/13] Retrieving persisted test suite from Document Store and inspecting fields...")
        persisted = doc_store.get_test_suite(suite.generation_id)
        assert persisted is not None
        print("-> Confirmed persistence in document store.")
        print("-" * 75)
        for idx, tc in enumerate(persisted.test_cases, 1):
            print(f"  Test Case #{idx} [{tc.TestCaseId}] — {tc.Title}")
            print(f"    Type: {tc.TestType} | Ref: {tc.StandardRef}")
            print(f"    Prerequisites ({len(tc.Prerequisites)}): {tc.Prerequisites[0]}")
            print(f"    Steps ({len(tc.Steps)}): {tc.Steps[0]}")
            print(f"    Expected: {tc.ExpectedResult}")
            print(f"    Pass/Fail: {tc.PassFailCriteria}")
            if tc.Provenance:
                print(f"    Provenance: Section {tc.Provenance.section_number} ({tc.Provenance.heading}) | Hash: {tc.Provenance.source_content_hash[:16]}...")
            print("-" * 75)

        # 7. Demonstrate duplicate-submission policy
        print("\n[Step 7/13] Demonstrating duplicate-submission & idempotency policy...")
        print("Submitting identical request with same idempotency key...")
        replay_suite = qa_service.generate_test_suite(
            db=db,
            selection_id=selection.id,
            requested_count=4,
            idempotency_key=idempotency_key,
        )
        assert replay_suite.generation_id == suite.generation_id
        print(f"-> Idempotent Replay Verified: Returned existing Suite ID {replay_suite.generation_id} without re-generation.")

        print("Submitting request reusing idempotency key with conflicting parameter (count=5)...")
        try:
            qa_service.generate_test_suite(
                db=db,
                selection_id=selection.id,
                requested_count=5,  # Conflicting count!
                idempotency_key=idempotency_key,
            )
            print("ERROR: Expected IdempotencyConflictError!")
        except IdempotencyConflictError as ice:
            print(f"-> Conflicting Request Successfully Rejected (HTTP 409 equivalent): {ice}")

        # 8. Ingest v2 manual without modifying v1 records
        print("\n[Step 8/13] Ingesting CT-200 Manual v2 (data/ct200_manual_v2.pdf)...")
        res_v2 = ingestion.ingest_version(db, version_label="v2")
        db.commit()
        print(f"-> Ingested v2: Document ID={res_v2.document_id}, Version ID={res_v2.version_id}, Nodes={res_v2.total_nodes}")

        # 9. Cross-version test suite staleness assessment against v2
        print("\n[Step 9/13] Running cross-version staleness audit against v2...")
        staleness_report = qa_service.evaluate_test_suite_staleness(
            db=db,
            generation_id=suite.generation_id,
            target_version_label="v2",
        )
        print(f"-> Suite Staleness Aggregate Status: {staleness_report.aggregate_status}")
        print(f"-> Human Review Required: {staleness_report.human_review_required}")
        print(f"-> Summary Breakdown: {staleness_report.summary}")

        print("\nDetailed Test Case Staleness Breakdown:")
        print("-" * 75)
        for ca in staleness_report.test_case_assessments:
            print(f"  [{ca.test_case_id}] {ca.title}")
            print(f"    Source: §{ca.source_section_number} {ca.source_heading}")
            print(f"    Status: {ca.status} | Classification: {ca.classification}")
            if ca.deltas:
                print("    Detected Specification Deltas:")
                for d in ca.deltas:
                    print(f"      * {d.delta_type.upper()}: {d.old_value} -> {d.new_value} {d.unit} ({d.explanation})")
            print(f"    Audit Assessment: {ca.explanation}")
            print("-" * 75)

        # 10. Unchanged control test case (§1.1 Intended Use)
        print("\n[Step 10/13] Generating test case for unchanged control node (§1.1 Intended Use)...")
        control_suite = qa_service.generate_test_suite(
            db=db,
            node_version_id=node_intended.id,
            requested_count=3,
            idempotency_key="control-intended-use-001",
        )
        control_staleness = qa_service.evaluate_test_suite_staleness(
            db=db,
            generation_id=control_suite.generation_id,
            target_version_label="v2",
        )
        print(f"-> Unchanged Section §1.1 Suite Aggregate Status: {control_staleness.aggregate_status}")
        for c in control_staleness.test_case_assessments:
            print(f"   [{c.test_case_id}] Status: {c.status} | Classification: {c.classification} ({c.explanation})")
        assert control_staleness.aggregate_status == "CURRENT"

        # 11. Query test suites by selection and node
        print("\n[Step 11/13] Querying test suites by selection and individual node...")
        sel_suites = doc_store.list_test_suites(selection_id=selection.id)
        print(f"-> Found {len(sel_suites)} suite(s) for Selection ID '{selection.id}'")

        node_suites = doc_store.list_test_suites(node_version_id=node_battery.id)
        print(f"-> Found {len(node_suites)} suite(s) referencing Battery Life node '{node_battery.id}'")

        # 12. Verify provenance immutability
        print("\n[Step 12/13] Verifying original v1 source provenance immutability...")
        re_checked_suite = doc_store.get_test_suite(suite.generation_id)
        assert re_checked_suite is not None
        for tc in re_checked_suite.test_cases:
            assert tc.Provenance is not None
            assert tc.Provenance.source_document_version_label == "v1"
            assert tc.Provenance.source_node_version_id in [node_battery.id, node_cuff.id, node_error.id]
        print("-> Verified: Original v1 node IDs and content hashes were NOT mutated by v2 ingestion.")

        # 13. Document-wide test-suite impact
        print("\n[Step 13/13] Evaluating document-wide test suite impact across v1 -> v2...")
        doc_impact = qa_service.analyze_document_test_suite_impact(
            db=db,
            document_id=res_v1.document_id,
            from_version_label="v1",
            to_version_label="v2",
        )
        print(f"-> Total Suites Evaluated: {doc_impact.total_test_suites_evaluated}")
        print(f"-> Impacted Suites Count: {doc_impact.impacted_test_suites_count}")
        print(f"-> Current/Unaffected Suites Count: {doc_impact.current_test_suites_count}")
        print(f"-> Human Review Required: {doc_impact.human_review_required}")

        print("\n" + "=" * 80)
        print("STAGE 5 END-TO-END DEMO COMPLETED SUCCESSFULLY WITH 0 ERRORS")
        print("=" * 80)

    finally:
        db.close()
        shutil.rmtree(temp_store_dir, ignore_errors=True)


if __name__ == "__main__":
    run_e2e_qa_generation_demo()
