"""End-to-End Demonstration Script for Stage 4: Version-Pinned Selections, Staleness & Impact.

Demonstrates:
1. Ingesting CT-200 manual v1 into an isolated disposable SQLite database.
2. Creating a named selection pinned to v1 (§2.1.1.1 Battery Life, §3.2 Cuff Inflation, §4.2 Error Codes).
3. Recording exact node-version IDs and cryptographic hashes.
4. Creating a second selection for an unchanged section (§1.1 Intended Use).
5. Ingesting v2 without altering v1 records or selection pinning.
6. Evaluating selection staleness against v2:
   - §2.1.1.1: Numerical change (300 -> 250 cycles, 15% -> 10% battery threshold).
   - §3.2: Numerical change (40 -> 30 mmHg inflation increments).
   - §4.2: Timing change (Auto-deflate 2s -> 1.5s) & Table addition of E6 Bluetooth sync.
7. Verifying that §5.3 Data Export is newly added in v2 and NOT inserted into the v1 selection.
8. Evaluating Selection 2 (unchanged baseline) stays CURRENT.
9. Running document-wide impact analysis showing impacted vs unaffected selections.
10. Proving v1 immutable snapshot retention and idempotency.

Usage:
    python -m scripts.demo_e2e_staleness
"""

import sys
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.repositories.document_repository import DocumentRepository
from app.services.document_ingestion import DocumentIngestionService
from app.services.impact_analyzer import ImpactAnalyzer
from app.services.staleness_classifier import StalenessClassifier


def run_e2e_staleness_demo():
    print("=" * 80)
    print("Tri9T AI — Stage 4 End-to-End Staleness & Impact Detection Demonstration")
    print("=" * 80)

    # Step 1: Initialize isolated disposable SQLite database
    print("\n[Step 1/11] Initializing isolated disposable database (in-memory SQLite)...")
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    repo = DocumentRepository()
    ingestion = DocumentIngestionService(repository=repo)
    classifier = StalenessClassifier()
    analyzer = ImpactAnalyzer(repository=repo, classifier=classifier)

    # Ingest v1
    print("Ingesting v1 manual (data/ct200_manual.pdf)...")
    res_v1 = ingestion.ingest_version(db, version_label="v1")
    db.commit()
    print(f"-> Ingested v1 successfully: doc_id={res_v1.document_id}, v1_id={res_v1.version_id}, total_nodes={res_v1.total_nodes}")

    # Step 2: Query v1 node IDs dynamically
    print("\n[Step 2/11] Querying dynamic v1 node snapshots...")
    v1_nodes = repo.get_node_versions_for_document_version(db, res_v1.version_id)
    node_map_v1 = {n.section_number: n for n in v1_nodes}

    node_battery_v1 = node_map_v1["2.1.1.1"]
    node_cuff_v1 = node_map_v1["3.2"]
    node_err_v1 = node_map_v1["4.2"]
    node_intended_v1 = node_map_v1["1.1"]

    print(f"-> §2.1.1.1 Battery Life:     ID={node_battery_v1.id[:8]}... Hash={node_battery_v1.content_hash[:12]}...")
    print(f"-> §3.2 Cuff Inflation:        ID={node_cuff_v1.id[:8]}... Hash={node_cuff_v1.content_hash[:12]}...")
    print(f"-> §4.2 Error Codes:           ID={node_err_v1.id[:8]}... Hash={node_err_v1.content_hash[:12]}...")
    print(f"-> §1.1 Intended Use:          ID={node_intended_v1.id[:8]}... Hash={node_intended_v1.content_hash[:12]}...")

    # Step 3: Create Selection 1 (Pinned to v1)
    print("\n[Step 3/11] Creating Named Selection 1: 'Safety Critical Suite' pinned to v1...")
    sel_safety = repo.create_selection(
        db=db,
        document_id=res_v1.document_id,
        document_version_id=res_v1.version_id,
        name="Safety Critical Suite",
        description="Core battery, cuff inflation, and error handling sections for QA verification",
        node_version_ids=[node_battery_v1.id, node_cuff_v1.id, node_err_v1.id],
        metadata_json='{"qa_tier": "P0_Safety"}',
    )
    db.commit()
    print(f"-> Created Selection 1: ID={sel_safety.id}, Name='{sel_safety.name}', Pinned Version={sel_safety.document_version.version_label}")
    print(f"-> Selected Node Count: {len(sel_safety.selection_nodes)}")

    # Step 4: Create Selection 2 (Unchanged section pinned to v1)
    print("\n[Step 4/11] Creating Named Selection 2: 'General Specifications' pinned to v1...")
    sel_general = repo.create_selection(
        db=db,
        document_id=res_v1.document_id,
        document_version_id=res_v1.version_id,
        name="General Specifications",
        description="General intended use and device overview",
        node_version_ids=[node_intended_v1.id],
        metadata_json='{"qa_tier": "P2_General"}',
    )
    db.commit()
    print(f"-> Created Selection 2: ID={sel_general.id}, Name='{sel_general.name}', Pinned Version={sel_general.document_version.version_label}")

    # Step 5: Ingest v2 without modifying v1 or selections
    print("\n[Step 5/11] Ingesting v2 manual (data/ct200_manual_v2.pdf)...")
    res_v2 = ingestion.ingest_version(db, version_label="v2")
    db.commit()
    print(f"-> Ingested v2 successfully: v2_id={res_v2.version_id}, total_nodes={res_v2.total_nodes}")

    # Step 6: Verify Selection 1 remains pinned to v1
    print("\n[Step 6/11] Verifying selection version pinning immutability...")
    sel_refetched = repo.get_selection(db, sel_safety.id)
    assert sel_refetched.document_version_id == res_v1.version_id
    print(f"-> Selection '{sel_refetched.name}' pinned document_version_id: {sel_refetched.document_version_id}")
    print(f"-> Pinned version label: {sel_refetched.document_version.version_label} (STRICTLY IMMUTABLE)")

    # Step 7: Run Staleness Assessment on Selection 1 against v2
    print("\n[Step 7/11] Running Staleness Evaluation on Selection 1 against v2...")
    stale_res1 = classifier.evaluate_selection_staleness(
        db=db,
        repository=repo,
        selection_id=sel_safety.id,
        target_version_label="v2",
    )
    print(f"-> Aggregate Selection Status: {stale_res1.aggregate_status.value}")
    print(f"-> Human Review Required:      {stale_res1.human_review_required}")
    print(f"-> Summary Breakdown:          {stale_res1.summary_counts}")

    print("\n--- Detected Value & Threshold Deltas for Selection 1 ---")
    for assessment in stale_res1.node_assessments:
        print(f"\nSection §{assessment.section_number} - {assessment.heading}:")
        print(f"  Classification: {assessment.classification.value}")
        print(f"  Node Status:    {assessment.status.value}")
        print(f"  From Hash:      {assessment.from_content_hash[:16]}...")
        print(f"  To Hash:        {assessment.to_content_hash[:16]}...")
        print(f"  Explanation:    {assessment.explanation}")
        if assessment.deltas:
            for d in assessment.deltas:
                print(f"  [DELTA: {d.delta_type}] {d.explanation}")
                print(f"          Context: {d.context}")

    # Step 8: Verify §5.3 Data Export is ADDED in v2 and not in selection
    print("\n[Step 8/11] Verifying §5.3 Data Export addition and selection boundary...")
    v2_nodes = repo.get_node_versions_for_document_version(db, res_v2.version_id)
    node_5_3 = next((n for n in v2_nodes if n.section_number == "5.3"), None)
    assert node_5_3 is not None
    print(f"-> Found §5.3 Data Export in v2: ID={node_5_3.id[:8]}..., Heading='{node_5_3.heading}'")

    sel_node_sections = [sn.node_version.section_number for sn in sel_refetched.selection_nodes]
    assert "5.3" not in sel_node_sections
    print(f"-> Verified: §5.3 was NOT silently inserted into v1 selection. Selection sections: {sel_node_sections}")

    # Step 9: Run Staleness Assessment on Selection 2 (Unchanged baseline)
    print("\n[Step 9/11] Running Staleness Evaluation on Selection 2 (Unchanged) against v2...")
    stale_res2 = classifier.evaluate_selection_staleness(
        db=db,
        repository=repo,
        selection_id=sel_general.id,
        target_version_label="v2",
    )
    print(f"-> Selection 2 Aggregate Status: {stale_res2.aggregate_status.value}")
    print(f"-> Human Review Required:       {stale_res2.human_review_required}")
    print(f"-> Summary Breakdown:           {stale_res2.summary_counts}")
    assert stale_res2.aggregate_status.value == "CURRENT"
    assert stale_res2.human_review_required is False
    print("-> Verified: Selection 2 correctly classified as CURRENT without false positives.")

    # Step 10: Run Document-Wide Impact Analysis
    print("\n[Step 10/11] Running Document-Wide Impact Analysis (v1 -> v2)...")
    doc_impact = analyzer.analyze_document_impact(
        db=db,
        document_id=res_v1.document_id,
        from_version_label="v1",
        to_version_label="v2",
    )
    print(f"-> Total Selections Evaluated:    {doc_impact.total_selections_evaluated}")
    print(f"-> Impacted Selections Count:     {doc_impact.impacted_selections_count}")
    print(f"-> Review Required Count:         {doc_impact.review_required_selections_count}")
    print(f"-> Current / Safe Selections:     {doc_impact.current_selections_count}")
    print(f"-> Document Human Review Flag:    {doc_impact.human_review_required}")

    print("\nAffected Selections List:")
    for aff in doc_impact.affected_selections:
        print(f"  * Selection ID: {aff.selection_id[:8]}... | Name: '{aff.selection_name}'")
        print(f"    Status: {aff.aggregate_status.value} | Affected Nodes: {aff.affected_nodes_count}")
        print(f"    Reason: {aff.explanation}")

    print("\nUnaffected Selections List:")
    for unaff in doc_impact.unaffected_selections:
        print(f"  * Selection ID: {unaff.selection_id[:8]}... | Name: '{unaff.selection_name}'")
        print(f"    Status: {unaff.aggregate_status.value} | Reason: {unaff.explanation}")

    # Step 11: Idempotency and Re-execution Verification
    print("\n[Step 11/11] Testing Idempotency & Clean Re-ingestion...")
    res_v2_replay = ingestion.ingest_version(db, version_label="v2")
    assert res_v2_replay.is_idempotent_replay is True
    print(f"-> Re-ingestion of v2 correctly returned idempotent replay: is_idempotent={res_v2_replay.is_idempotent_replay}")

    print("\n" + "=" * 80)
    print("Stage 4 End-to-End Demonstration Successfully Completed!")
    print("=" * 80)


if __name__ == "__main__":
    run_e2e_staleness_demo()
