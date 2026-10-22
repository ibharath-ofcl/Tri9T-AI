"""Document ingestion and versioning service.

Orchestrates PDF parsing, schema validation, cross-version logical lineage matching,
and atomic relational persistence into SQLite with idempotency guarantees.
"""

from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Document, DocumentVersion, LogicalNode, NodeVersion
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import DocumentNode, DocumentTree
from app.services.pdf_parser import CT200PDFParser
from app.services.version_matcher import (
    ChangeClassification,
    MatchResult,
    PriorNodeSnapshot,
    VersionMatcher,
)


class IngestionConflictError(Exception):
    """Raised when a version label exists with a conflicting checksum."""
    pass


@dataclass
class IngestionResult:
    """Telemetry report produced after ingesting a document revision."""
    document_id: str
    version_id: str
    version_label: str
    source_sha256: str
    page_count: int
    total_nodes: int
    is_idempotent_replay: bool
    match_summary: Dict[str, int] = field(default_factory=dict)
    diagnostics_count: int = 0
    message: str = ""


class DocumentIngestionService:
    """High-reliability ingestion service managing immutable document version lifecycles."""

    def __init__(
        self,
        repository: Optional[DocumentRepository] = None,
        parser: Optional[CT200PDFParser] = None,
        matcher: Optional[VersionMatcher] = None,
    ):
        self.repo = repository or DocumentRepository()
        self.parser = parser or CT200PDFParser()
        self.matcher = matcher or VersionMatcher()

    def resolve_version_path(self, version_label: str, custom_path: Optional[Path] = None) -> Path:
        """Resolve filesystem path for version or validate provided path."""
        if custom_path:
            if not custom_path.exists():
                raise FileNotFoundError(f"Specified document path does not exist: {custom_path}")
            return custom_path

        if version_label == "v1":
            path = settings.v1_manual_path
        elif version_label == "v2":
            path = settings.v2_manual_path
        else:
            raise ValueError(f"Unknown version label '{version_label}' without explicit file path.")

        if not path.exists():
            raise FileNotFoundError(f"Standard manual asset not found on disk at: {path}")
        return path

    def ingest_version(
        self,
        db: Session,
        version_label: str,
        file_path: Optional[Path] = None,
        document_key: str = "CT-200",
    ) -> IngestionResult:
        """Ingest a PDF manual into the persistent database atomically.

        Guarantees:
        - Idempotent: Repeated ingestion of same version + checksum returns existing record.
        - Conflict detection: Mismatched checksum for existing version label raises IngestionConflictError.
        - Non-destructive: Existing versions (e.g. v1) are never mutated by new ingestions (v2).
        - Atomic: Failures trigger complete rollback; no partial trees are saved.
        """
        target_path = self.resolve_version_path(version_label, file_path)
        file_bytes = target_path.read_bytes()
        file_sha256 = hashlib.sha256(file_bytes).hexdigest()

        # Step 1: Ensure conceptual Document entity exists
        doc = self.repo.get_or_create_document(
            db=db,
            document_key=document_key,
            title="CardioTrack CT-200 Home Blood Pressure Monitor — Technical & User Manual",
        )

        # Step 2: Idempotency and Conflict Check
        existing_version = self.repo.get_version_by_label(db, doc.id, version_label)
        if existing_version:
            if existing_version.source_sha256 == file_sha256 and existing_version.status == "SUCCESS":
                # Idempotent replay: return existing snapshot without duplicating records
                return IngestionResult(
                    document_id=doc.id,
                    version_id=existing_version.id,
                    version_label=version_label,
                    source_sha256=file_sha256,
                    page_count=existing_version.page_count,
                    total_nodes=existing_version.total_nodes,
                    is_idempotent_replay=True,
                    message="Idempotent: Version already exists with matching checksum. No changes made.",
                )
            else:
                raise IngestionConflictError(
                    f"Version '{version_label}' already exists for document '{document_key}' "
                    f"with checksum '{existing_version.source_sha256}', which conflicts with "
                    f"new checksum '{file_sha256}'. Silently overwriting historical records is forbidden."
                )

        # Step 3: Parse PDF using deterministic parser
        tree: DocumentTree = self.parser.parse(target_path, version_label=version_label)
        if not tree.nodes:
            raise ValueError(f"Parsed document tree is empty for file: {target_path}")

        # Flatten parsed tree for processing
        flat_parsed_nodes: List[DocumentNode] = []
        parent_map_new: Dict[str, Optional[DocumentNode]] = {}

        def flatten(node: DocumentNode, parent: Optional[DocumentNode]):
            flat_parsed_nodes.append(node)
            parent_map_new[node.node_id] = parent
            for c in node.children:
                flatten(c, node)

        for root in tree.nodes:
            flatten(root, None)

        # Step 4: Check for prior version to establish lineage
        prior_version: Optional[DocumentVersion] = None
        if version_label == "v2":
            prior_version = self.repo.get_version_by_label(db, doc.id, "v1")
        elif doc.latest_version_id:
            prior_version = self.repo.get_document_version(db, doc.latest_version_id)

        # Step 5: Perform cross-version logical node matching
        match_results: Dict[str, MatchResult] = {}
        match_summary: Dict[str, int] = {
            ChangeClassification.UNCHANGED.value: 0,
            ChangeClassification.MODIFIED.value: 0,
            ChangeClassification.ADDED.value: 0,
            ChangeClassification.REMOVED.value: 0,
            ChangeClassification.MOVED.value: 0,
            ChangeClassification.AMBIGUOUS.value: 0,
        }

        if prior_version:
            prior_node_versions = self.repo.get_node_versions_for_document_version(db, prior_version.id)
            # Build prior snapshots
            prior_snapshots: List[PriorNodeSnapshot] = []
            prior_nv_dict = {nv.id: nv for nv in prior_node_versions}

            for nv in prior_node_versions:
                parent_nv = prior_nv_dict.get(nv.parent_node_version_id) if nv.parent_node_version_id else None
                # Construct structural path
                p_path_parts = []
                curr_p = nv
                while curr_p:
                    p_path_parts.append(curr_p.section_number or curr_p.heading)
                    curr_p = prior_nv_dict.get(curr_p.parent_node_version_id) if curr_p.parent_node_version_id else None
                structural_path = " > ".join(reversed(p_path_parts))

                prior_snapshots.append(
                    PriorNodeSnapshot(
                        node_version_id=nv.id,
                        logical_node_id=nv.logical_node_id,
                        section_number=nv.section_number,
                        heading=nv.heading,
                        normalized_heading=self.matcher.normalize_heading(nv.heading),
                        parent_logical_id=parent_nv.logical_node_id if parent_nv else None,
                        parent_section_number=parent_nv.section_number if parent_nv else None,
                        structural_path=structural_path,
                        content_hash=nv.content_hash,
                        body_text=nv.body_text,
                        source_order=nv.source_order,
                    )
                )

            match_results, removed_nodes = self.matcher.match_versions(
                prev_nodes=prior_snapshots,
                new_nodes=flat_parsed_nodes,
                parent_map_new=parent_map_new,
            )

            # Record match stats
            for mr in match_results.values():
                match_summary[mr.classification.value] += 1
            match_summary[ChangeClassification.REMOVED.value] = len(removed_nodes)

        else:
            # Baseline version (e.g. v1): all nodes are initial logical identities
            for n in flat_parsed_nodes:
                match_results[n.node_id] = MatchResult(
                    new_node_order=n.document_order,
                    new_section_number=n.section_number,
                    new_heading=n.heading or "",
                    classification=ChangeClassification.ADDED,
                    is_new_logical_node=True,
                    notes="Baseline document version ingestion.",
                )
                match_summary[ChangeClassification.ADDED.value] += 1

        # Step 6: Atomic Database Ingestion
        try:
            # Create DocumentVersion record
            doc_version = DocumentVersion(
                document_id=doc.id,
                version_label=version_label,
                source_filename=target_path.name,
                source_sha256=file_sha256,
                page_count=tree.metadata.page_count,
                total_nodes=len(flat_parsed_nodes),
                parser_version="0.2.0",
                status="SUCCESS",
                metadata_json=json.dumps(tree.metadata.model_dump()),
                diagnostics_json=json.dumps([d.model_dump() for d in tree.diagnostics]),
            )
            db.add(doc_version)
            db.flush()

            # Map from parser node_id to newly persisted NodeVersion.id
            node_id_to_nv_id: Dict[str, str] = {}

            # First pass: Create or resolve LogicalNodes and persist NodeVersions
            for parsed_node in flat_parsed_nodes:
                m_result = match_results[parsed_node.node_id]

                if m_result.is_new_logical_node or not m_result.logical_node_id:
                    # Create a new conceptual LogicalNode
                    logical_node = LogicalNode(
                        document_id=doc.id,
                        canonical_section_number=parsed_node.section_number,
                        canonical_heading=parsed_node.heading,
                    )
                    db.add(logical_node)
                    db.flush()
                    logical_node_id = logical_node.id
                    m_result.logical_node_id = logical_node_id
                else:
                    logical_node_id = m_result.logical_node_id

                # Format source metadata (tables and layout details)
                tables_data = [t.model_dump() for t in parsed_node.tables]
                source_meta = {
                    "heading_font_size": parsed_node.heading_font_size,
                    "heading_is_bold": parsed_node.heading_is_bold,
                    "extraction_confidence": parsed_node.extraction_confidence,
                    "tables": tables_data,
                    "match_classification": m_result.classification.value,
                    "match_confidence": m_result.confidence_score,
                    "match_notes": m_result.notes,
                }

                nv = NodeVersion(
                    document_version_id=doc_version.id,
                    logical_node_id=logical_node_id,
                    parent_node_version_id=None,  # Linked in second pass
                    heading=parsed_node.heading or "",
                    section_number=parsed_node.section_number,
                    level=parsed_node.level,
                    body_text=parsed_node.body_text,
                    content_hash=parsed_node.content_hash,
                    heading_hash=parsed_node.heading_hash,
                    body_hash=parsed_node.body_hash,
                    page_start=parsed_node.page_start,
                    page_end=parsed_node.page_end,
                    source_order=parsed_node.document_order,
                    source_metadata_json=json.dumps(source_meta),
                    diagnostics_json=json.dumps(parsed_node.warnings),
                )
                db.add(nv)
                db.flush()
                node_id_to_nv_id[parsed_node.node_id] = nv.id

            # Second pass: Link parent_node_version_id within the same document_version
            for parsed_node in flat_parsed_nodes:
                parent_parsed = parent_map_new.get(parsed_node.node_id)
                if parent_parsed:
                    parent_nv_id = node_id_to_nv_id.get(parent_parsed.node_id)
                    current_nv_id = node_id_to_nv_id[parsed_node.node_id]
                    nv_to_update = db.get(NodeVersion, current_nv_id)
                    if nv_to_update:
                        nv_to_update.parent_node_version_id = parent_nv_id

            # Step 7: Update document latest_version_id pointer
            doc.latest_version_id = doc_version.id
            db.commit()

            return IngestionResult(
                document_id=doc.id,
                version_id=doc_version.id,
                version_label=version_label,
                source_sha256=file_sha256,
                page_count=doc_version.page_count,
                total_nodes=doc_version.total_nodes,
                is_idempotent_replay=False,
                match_summary=match_summary,
                diagnostics_count=len(tree.diagnostics),
                message=f"Successfully ingested {version_label} ({doc_version.total_nodes} nodes).",
            )

        except Exception as exc:
            db.rollback()
            raise exc
