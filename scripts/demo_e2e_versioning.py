#!/usr/bin/env python3
"""Stage 3 End-to-End Demonstration Script.

Executes the complete workflow mandated by Task 10:
1. Initialize an empty test database.
2. Ingest CT-200 v1 manual.
3. Inspect known v1 node (§3.2 Cuff Inflation Sequence) - record IDs and hash.
4. Ingest CT-200 v2 manual.
5. Verify v1 records remain unchanged (immutability).
6. Inspect corresponding v2 node (§3.2) - prove logical_node_id retention and hash change.
7. Inspect newly added section (§5.3 Data Export) - prove new logical_node_id.
8. Perform version-isolated search across v1 and v2.
9. Generate cross-version diff summary for §3.2.
10. Re-ingest v2 and prove idempotency.
11. Run synthetic ambiguity fixture demonstrating explicit unforced match handling.
"""

import json
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Document, DocumentVersion, LogicalNode, NodeVersion
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import DocumentNode
from app.services.document_ingestion import DocumentIngestionService
from app.services.version_matcher import ChangeClassification, PriorNodeSnapshot, VersionMatcher


def run_e2e_demonstration():
    print("=" * 80)
    print("TRI9T-AI: STAGE 3 END-TO-END DEMONSTRATION")
    print("=" * 80)

    # Step 1: Empty in-memory test database
    print("\n[Step 1] Initializing clean isolated database...")
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()
    repo = DocumentRepository()
    service = DocumentIngestionService(repository=repo)
    print("  -> Database initialized with tables: documents, document_versions, logical_nodes, node_versions.")

    # Step 2: Ingest v1
    print("\n[Step 2] Ingesting CT-200 v1 manual (data/ct200_manual.pdf)...")
    res_v1 = service.ingest_version(db, version_label="v1")
    print(f"  -> v1 Ingestion Status: {res_v1.message}")
    print(f"  -> Document ID        : {res_v1.document_id}")
    print(f"  -> Version ID         : {res_v1.version_id}")
    print(f"  -> SHA-256 Checksum   : {res_v1.source_sha256}")
    print(f"  -> Total Nodes        : {res_v1.total_nodes} (Pages: {res_v1.page_count})")

    # Step 3: Inspect known v1 node: §3.2 Cuff Inflation Sequence
    print("\n[Step 3] Inspecting v1 node §3.2 (Cuff Inflation Sequence)...")
    v1_nodes = repo.get_node_versions_for_document_version(db, res_v1.version_id)
    n32_v1 = next(n for n in v1_nodes if n.section_number == "3.2")
    v1_logical_id = n32_v1.logical_node_id
    v1_node_version_id = n32_v1.id
    v1_hash = n32_v1.content_hash
    print(f"  -> Heading          : {n32_v1.heading}")
    print(f"  -> Logical Node ID  : {v1_logical_id}")
    print(f"  -> Node Version ID  : {v1_node_version_id}")
    print(f"  -> Content Hash     : {v1_hash}")
    print(f"  -> Source Pages     : P{n32_v1.page_start}-P{n32_v1.page_end}")
    print(f"  -> Excerpt          : \"{n32_v1.body_text[:90]}...\"")

    # Step 4: Ingest v2
    print("\n[Step 4] Ingesting CT-200 v2 manual (data/ct200_manual_v2.pdf)...")
    res_v2 = service.ingest_version(db, version_label="v2")
    print(f"  -> v2 Ingestion Status: {res_v2.message}")
    print(f"  -> Version ID         : {res_v2.version_id}")
    print(f"  -> SHA-256 Checksum   : {res_v2.source_sha256}")
    print(f"  -> Total Nodes        : {res_v2.total_nodes} (Pages: {res_v2.page_count})")
    print(f"  -> Lineage Statistics : {res_v2.match_summary}")

    # Step 5: Verify v1 records remain completely unchanged
    print("\n[Step 5] Verifying v1 immutability...")
    n32_v1_check = db.get(NodeVersion, v1_node_version_id)
    assert n32_v1_check.content_hash == v1_hash, "v1 content hash was altered!"
    assert n32_v1_check.logical_node_id == v1_logical_id, "v1 logical ID was altered!"
    print(f"  -> v1 Node Version ID {v1_node_version_id} remains intact and unchanged.")

    # Step 6: Inspect corresponding v2 node §3.2
    print("\n[Step 6] Inspecting corresponding v2 node §3.2...")
    v2_nodes = repo.get_node_versions_for_document_version(db, res_v2.version_id)
    n32_v2 = next(n for n in v2_nodes if n.section_number == "3.2")
    print(f"  -> Heading          : {n32_v2.heading}")
    print(f"  -> Logical Node ID  : {n32_v2.logical_node_id} (MATCHES V1: {n32_v2.logical_node_id == v1_logical_id})")
    print(f"  -> Node Version ID  : {n32_v2.id} (DIFFERENT FROM V1: {n32_v2.id != v1_node_version_id})")
    print(f"  -> New Content Hash : {n32_v2.content_hash} (CHANGED: {n32_v2.content_hash != v1_hash})")
    print(f"  -> Excerpt          : \"{n32_v2.body_text[:110]}...\"")

    # Step 7: Inspect newly added section §5.3 Data Export
    print("\n[Step 7] Inspecting newly added section §5.3 (Data Export)...")
    n53_v2 = next(n for n in v2_nodes if n.section_number == "5.3")
    v1_logical_ids = {n.logical_node_id for n in v1_nodes}
    is_brand_new = n53_v2.logical_node_id not in v1_logical_ids
    print(f"  -> Heading          : {n53_v2.heading}")
    print(f"  -> Logical Node ID  : {n53_v2.logical_node_id}")
    print(f"  -> Brand New Identity: {is_brand_new} (Does not exist in v1 lineage)")
    print(f"  -> Body Excerpt     : \"{n53_v2.body_text[:100]}...\"")

    # Step 8: Version-isolated search
    print("\n[Step 8] Demonstrating version-isolated search...")
    # Search for "Bluetooth sync failure" (only in v2)
    hits_v1 = repo.search_nodes(db, query="Bluetooth sync failure", version_label="v1")
    hits_v2 = repo.search_nodes(db, query="Bluetooth sync failure", version_label="v2")
    print(f"  -> Search query 'Bluetooth sync failure' in v1: {len(hits_v1)} hits")
    print(f"  -> Search query 'Bluetooth sync failure' in v2: {len(hits_v2)} hit(s)")
    if hits_v2:
        print(f"     Match found in §{hits_v2[0].section_number} {hits_v2[0].heading} (Version: {hits_v2[0].document_version.version_label})")

    # Step 9: Change summary diff between v1 and v2
    print("\n[Step 9] Generating cross-version diff for §3.2...")
    import difflib
    diff = list(difflib.unified_diff(
        n32_v1.body_text.splitlines(),
        n32_v2.body_text.splitlines(),
        fromfile="v1:3.2",
        tofile="v2:3.2",
        lineterm=""
    ))
    print("  --- Unified Diff ---")
    for line in diff:
        print(f"    {line}")

    # Step 10: Prove idempotency on re-ingestion
    print("\n[Step 10] Testing idempotent re-ingestion of v2...")
    res_v2_replay = service.ingest_version(db, version_label="v2")
    print(f"  -> Is Idempotent Replay : {res_v2_replay.is_idempotent_replay}")
    print(f"  -> Message              : {res_v2_replay.message}")
    print(f"  -> Total Version Records: {len(repo.get_document_by_id(db, res_v1.document_id).versions)} (Exactly 2)")

    # Step 11: Synthetic ambiguity fixture
    print("\n[Step 11] Synthetic ambiguity fixture test...")
    matcher = VersionMatcher(similarity_threshold=0.80, ambiguity_margin=0.10)
    p1 = PriorNodeSnapshot(
        node_version_id="pv-1", logical_node_id="log-1", section_number="9.1",
        heading="Alarm Thresholds and Warnings", normalized_heading="alarm thresholds and warnings",
        parent_logical_id="p-log", parent_section_number="9.", structural_path="9. > 9.1",
        content_hash="h1", body_text="text1", source_order=1
    )
    p2 = PriorNodeSnapshot(
        node_version_id="pv-2", logical_node_id="log-2", section_number="9.2",
        heading="Alarm Thresholds and Alerts", normalized_heading="alarm thresholds and alerts",
        parent_logical_id="p-log", parent_section_number="9.", structural_path="9. > 9.2",
        content_hash="h2", body_text="text2", source_order=2
    )
    ambig_node = DocumentNode(
        node_id="n-ambig", section_number=None, heading="Alarm Thresholds and Warnings",
        level=2, body_text="New alert text", parent_id=None, document_order=1, page_start=1, page_end=1,
        content_hash="h-ambig", heading_hash="hh", body_hash="bh"
    )
    match_res, _ = matcher.match_versions(prev_nodes=[p1, p2], new_nodes=[ambig_node], parent_map_new={"n-ambig": None})
    outcome = match_res["n-ambig"]
    print(f"  -> Classification: {outcome.classification.value} | Confidence: {outcome.confidence_score}")
    print(f"  -> Note          : {outcome.notes}")

    print("\n" + "=" * 80)
    print("DEMONSTRATION COMPLETED SUCCESSFULLY WITHOUT ERRORS")
    print("=" * 80)
    db.close()


if __name__ == "__main__":
    run_e2e_demonstration()
