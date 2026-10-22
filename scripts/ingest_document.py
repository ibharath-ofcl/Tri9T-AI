#!/usr/bin/env python3
"""CLI tool for ingesting CT-200 PDF manuals into the relational database and viewing version lineage.

Usage:
    python -m scripts.ingest_document --version v1
    python -m scripts.ingest_document --version v2
    python -m scripts.ingest_document --summary
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

from app.db.session import SessionLocal, init_db
from app.repositories.document_repository import DocumentRepository
from app.services.document_ingestion import DocumentIngestionService, IngestionConflictError


def print_database_summary() -> None:
    """Print comprehensive summary of all ingested documents, versions, and lineage."""
    db = SessionLocal()
    repo = DocumentRepository()
    try:
        docs = repo.list_documents(db)
        if not docs:
            print("No documents found in database. Ingest a version first using: python -m scripts.ingest_document --version v1")
            return

        print("=" * 80)
        print("TRI9T-AI DATABASE INVENTORY & VERSION LINEAGE SUMMARY")
        print("=" * 80)

        for doc in docs:
            print(f"\nDocument Key: {doc.document_key} | Title: {doc.title}")
            print(f"ID: {doc.id} | Latest Version ID: {doc.latest_version_id or 'None'}")
            print(f"Versions Count: {len(doc.versions)} | Logical Nodes Count: {len(doc.logical_nodes)}")

            print("\n  --- INGESTED VERSIONS ---")
            for v in doc.versions:
                print(f"  * Version [{v.version_label}]: ID={v.id}")
                print(f"    Source File : {v.source_filename} ({v.page_count} pages, {v.total_nodes} nodes)")
                print(f"    SHA-256     : {v.source_sha256}")
                print(f"    Ingested At : {v.ingested_at.isoformat()} | Status: {v.status}")

                # Node statistics
                nodes = repo.get_node_versions_for_document_version(db, v.id)
                top_level = [n for n in nodes if n.level == 1]
                print(f"    Top Sections: {len(top_level)} main sections (1 to {len(top_level)})")

            # Cross-version node lineage summary if both v1 and v2 exist
            v1 = repo.get_version_by_label(db, doc.id, "v1")
            v2 = repo.get_version_by_label(db, doc.id, "v2")
            if v1 and v2:
                print("\n  --- CROSS-VERSION NODE LINEAGE (v1 -> v2) ---")
                nodes_v1 = {n.logical_node_id: n for n in repo.get_node_versions_for_document_version(db, v1.id)}
                nodes_v2 = {n.logical_node_id: n for n in repo.get_node_versions_for_document_version(db, v2.id)}

                unchanged = 0
                modified = []
                added = []

                for l_id, n2 in nodes_v2.items():
                    if l_id in nodes_v1:
                        n1 = nodes_v1[l_id]
                        if n1.content_hash == n2.content_hash:
                            unchanged += 1
                        else:
                            modified.append((n1, n2))
                    else:
                        added.append(n2)

                print(f"  Unchanged Nodes : {unchanged}")
                print(f"  Modified Nodes  : {len(modified)}")
                for n1, n2 in modified:
                    print(f"    - §{n2.section_number} {n2.heading} (Hash: {n1.content_hash[:10]}... -> {n2.content_hash[:10]}...)")
                print(f"  Added Nodes     : {len(added)}")
                for n2 in added:
                    print(f"    + §{n2.section_number} {n2.heading} (New Logical Identity)")

        print("\n" + "=" * 80)
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Ingest CT-200 manuals into database.")
    parser.add_argument("--version", choices=["v1", "v2"], help="Version label to ingest ('v1' or 'v2')")
    parser.add_argument("--path", type=str, help="Optional custom PDF file path")
    parser.add_argument("--summary", action="store_true", help="Print summary of ingested documents and lineage")
    args = parser.parse_args()

    # Initialize tables if not already present
    init_db()

    if args.summary or (not args.version and not args.summary):
        print_database_summary()
        return

    custom_path = Path(args.path) if args.path else None
    db = SessionLocal()
    service = DocumentIngestionService()

    try:
        print(f"Starting ingestion for version: {args.version}...")
        result = service.ingest_version(db=db, version_label=args.version, file_path=custom_path)
        print("Ingestion completed successfully!")
        print(f"  Document ID : {result.document_id}")
        print(f"  Version ID  : {result.version_id} ({result.version_label})")
        print(f"  SHA-256     : {result.source_sha256}")
        print(f"  Nodes Count : {result.total_nodes}")
        print(f"  Idempotent  : {result.is_idempotent_replay}")
        if result.match_summary:
            print(f"  Match Stats : {result.match_summary}")
        print(f"  Message     : {result.message}")
    except IngestionConflictError as ice:
        print(f"INGESTION CONFLICT: {ice}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"INGESTION FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
