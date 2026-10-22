"""FastAPI application for CT-200 Document Intelligence Engine.

Provides:
- Ingestion endpoints with atomic transactions and idempotency.
- Persistent document browsing and section tree navigation.
- Node inspection with full provenance, tables, and diagnostics.
- Cross-version search with text snippets.
- Cross-version diffing and logical node lineage comparison.
- Backward-compatible /health and /preview endpoints.
"""

import difflib
import json
from typing import Any, Dict, List, Optional
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db, init_db
from app.repositories.document_repository import DocumentRepository
from app.schemas.api import (
    DocumentSummaryResponse,
    DocumentVersionSummary,
    NodeChangeComparisonResponse,
    NodeDetailResponse,
    SearchHit,
    SearchResponse,
    SectionItem,
    VersionNodeSnapshotResponse,
)
from app.schemas.document import DocumentTree
from app.services.document_ingestion import (
    DocumentIngestionService,
    IngestionConflictError,
    IngestionResult,
)
from app.services.pdf_parser import CT200PDFParser
from app.services.version_matcher import ChangeClassification

app = FastAPI(
    title=settings.app_name,
    version="0.3.0",
    description="Document Intelligence & Lineage API for CT-200 Blood Pressure Monitor Manuals",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Singletons for services
parser = CT200PDFParser()
repo = DocumentRepository()
ingestion_service = DocumentIngestionService(repository=repo, parser=parser)

MANUAL_VERSIONS = {
    "v1": settings.v1_manual_path,
    "v2": settings.v2_manual_path,
}


@app.on_event("startup")
def startup_event():
    """Ensure database tables are initialized at startup."""
    init_db()


# ---------------------------------------------------------------------------
# System Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
def get_health() -> Dict[str, Any]:
    """Health check endpoint verifying system responsiveness and asset presence."""
    v1_exists = settings.v1_manual_path.exists()
    v2_exists = settings.v2_manual_path.exists()
    return {
        "status": "healthy" if (v1_exists and v2_exists) else "degraded",
        "app_name": settings.app_name,
        "environment": settings.app_env,
        "version": "0.3.0",
        "assets_status": {
            "v1_manual_present": v1_exists,
            "v2_manual_present": v2_exists,
            "data_dir": str(settings.data_dir),
        },
    }


# ---------------------------------------------------------------------------
# Stage 2 Development Preview Endpoint (Preserved)
# ---------------------------------------------------------------------------

@app.get(
    f"{settings.api_v1_prefix}/documents/preview",
    response_model=DocumentTree,
    tags=["Development"],
    summary="Preview parsed document hierarchy in-memory",
)
def preview_document(
    version: str = Query("v1", description="Manual version to parse ('v1' or 'v2')", regex="^(v1|v2)$")
) -> DocumentTree:
    """Parse and return full document tree without database persistence."""
    if version not in MANUAL_VERSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid version '{version}'. Allowed: {list(MANUAL_VERSIONS.keys())}",
        )
    target_file = MANUAL_VERSIONS[version]
    if not target_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Manual file for version '{version}' not found on server at {target_file.name}",
        )
    return parser.parse(target_file, version_label=version)


# ---------------------------------------------------------------------------
# Persistent Ingestion Endpoint
# ---------------------------------------------------------------------------

@app.post(
    f"{settings.api_v1_prefix}/documents/ingest",
    tags=["Ingestion"],
    summary="Ingest a document version into relational storage",
)
def ingest_document_endpoint(
    version: str = Query("v1", description="Version label ('v1' or 'v2')", regex="^(v1|v2)$"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Atomically ingest a manual revision, establishing cross-version node lineage."""
    try:
        res: IngestionResult = ingestion_service.ingest_version(db=db, version_label=version)
        return {
            "status": "success",
            "document_id": res.document_id,
            "version_id": res.version_id,
            "version_label": res.version_label,
            "source_sha256": res.source_sha256,
            "page_count": res.page_count,
            "total_nodes": res.total_nodes,
            "is_idempotent_replay": res.is_idempotent_replay,
            "match_summary": res.match_summary,
            "diagnostics_count": res.diagnostics_count,
            "message": res.message,
        }
    except IngestionConflictError as ice:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(ice))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


# ---------------------------------------------------------------------------
# Endpoint A: List Document Versions
# ---------------------------------------------------------------------------

@app.get(
    f"{settings.api_v1_prefix}/documents",
    response_model=List[DocumentSummaryResponse],
    tags=["Documents"],
    summary="List conceptual documents and all ingested versions",
)
def list_documents(db: Session = Depends(get_db)) -> List[DocumentSummaryResponse]:
    """Return all registered document identities and their immutable ingested versions."""
    docs = repo.list_documents(db)
    results = []
    for d in docs:
        versions_summary = [
            DocumentVersionSummary(
                version_id=v.id,
                version_label=v.version_label,
                source_filename=v.source_filename,
                source_sha256=v.source_sha256,
                page_count=v.page_count,
                total_nodes=v.total_nodes,
                ingested_at=v.ingested_at,
                status=v.status,
            )
            for v in d.versions
        ]
        results.append(
            DocumentSummaryResponse(
                document_id=d.id,
                document_key=d.document_key,
                title=d.title,
                latest_version_id=d.latest_version_id,
                versions=versions_summary,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Endpoint B: List Top-Level Sections
# ---------------------------------------------------------------------------

def _build_section_tree(nv, db: Session) -> SectionItem:
    """Helper to recursively build SectionItem hierarchy."""
    child_items = []
    for c in nv.children:
        child_items.append(_build_section_tree(c, db))
    return SectionItem(
        node_version_id=nv.id,
        logical_node_id=nv.logical_node_id,
        section_number=nv.section_number,
        heading=nv.heading,
        level=nv.level,
        page_start=nv.page_start,
        page_end=nv.page_end,
        source_order=nv.source_order,
        content_hash=nv.content_hash,
        children_count=len(nv.children),
        children=child_items,
    )


@app.get(
    f"{settings.api_v1_prefix}/documents/{{document_id}}/sections",
    response_model=List[SectionItem],
    tags=["Documents"],
    summary="List top-level sections and subsections for a version",
)
def get_document_sections(
    document_id: str,
    version: Optional[str] = Query(None, description="Version label ('v1', 'v2'). Defaults to latest version."),
    db: Session = Depends(get_db),
) -> List[SectionItem]:
    """Retrieve the complete section hierarchy tree for the specified document version."""
    doc = repo.get_document_by_id(db, document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found.",
        )

    # Determine version label
    target_version_label = version
    if not target_version_label:
        if doc.latest_version:
            target_version_label = doc.latest_version.version_label
        elif doc.versions:
            target_version_label = doc.versions[-1].version_label
        else:
            return []

    top_sections = repo.get_top_level_sections(db, document_id=doc.id, version_label=target_version_label)
    return [_build_section_tree(s, db) for s in top_sections]


# ---------------------------------------------------------------------------
# Endpoint C: Retrieve Node by ID
# ---------------------------------------------------------------------------

@app.get(
    f"{settings.api_v1_prefix}/nodes/{{node_version_id}}",
    response_model=NodeDetailResponse,
    tags=["Nodes"],
    summary="Retrieve full node details, provenance, tables, and diagnostics",
)
def get_node_detail(
    node_version_id: str,
    db: Session = Depends(get_db),
) -> NodeDetailResponse:
    """Fetch complete immutable record for a node version."""
    nv = repo.get_node_version(db, node_version_id)
    if not nv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node version with ID '{node_version_id}' not found.",
        )

    tables = []
    if nv.source_metadata_json:
        try:
            meta = json.loads(nv.source_metadata_json)
            tables = meta.get("tables", [])
        except Exception:
            pass

    diagnostics = []
    if nv.diagnostics_json:
        try:
            diagnostics = json.loads(nv.diagnostics_json)
        except Exception:
            pass

    child_items = [
        SectionItem(
            node_version_id=c.id,
            logical_node_id=c.logical_node_id,
            section_number=c.section_number,
            heading=c.heading,
            level=c.level,
            page_start=c.page_start,
            page_end=c.page_end,
            source_order=c.source_order,
            content_hash=c.content_hash,
            children_count=len(c.children),
        )
        for c in nv.children
    ]

    return NodeDetailResponse(
        node_version_id=nv.id,
        logical_node_id=nv.logical_node_id,
        document_version_id=nv.document_version_id,
        version_label=nv.document_version.version_label if nv.document_version else "unknown",
        heading=nv.heading,
        section_number=nv.section_number,
        level=nv.level,
        parent_node_version_id=nv.parent_node_version_id,
        body_text=nv.body_text,
        content_hash=nv.content_hash,
        heading_hash=nv.heading_hash,
        body_hash=nv.body_hash,
        page_start=nv.page_start,
        page_end=nv.page_end,
        source_order=nv.source_order,
        tables=tables,
        diagnostics=diagnostics,
        children=child_items,
    )


# ---------------------------------------------------------------------------
# Endpoint D: Search Headings and Body Text
# ---------------------------------------------------------------------------

@app.get(
    f"{settings.api_v1_prefix}/search",
    response_model=SearchResponse,
    tags=["Search"],
    summary="Search headings and body text with version filtering",
)
def search_nodes(
    q: str = Query(..., min_length=1, description="Search term or phrase"),
    version: Optional[str] = Query(None, description="Filter by version ('v1', 'v2')"),
    section: Optional[str] = Query(None, description="Filter by section number prefix (e.g. '2.')"),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of hits"),
    db: Session = Depends(get_db),
) -> SearchResponse:
    """Execute case-insensitive search across headings and body text."""
    nodes = repo.search_nodes(
        db=db,
        query=q,
        version_label=version,
        section_filter=section,
        limit=limit,
    )

    hits: List[SearchHit] = []
    q_lower = q.lower()

    for n in nodes:
        # Create a snippet around matched term
        text = n.body_text or ""
        idx = text.lower().find(q_lower)
        if idx != -1:
            start = max(0, idx - 40)
            end = min(len(text), idx + len(q) + 60)
            snippet = ("..." if start > 0 else "") + text[start:end].strip() + ("..." if end < len(text) else "")
        elif q_lower in (n.heading or "").lower():
            snippet = f"Heading match: {n.heading}"
        elif n.source_metadata_json and q_lower in n.source_metadata_json.lower():
            snippet = f"Table match: {q}"
        else:
            snippet = (text[:100] + "...") if len(text) > 100 else text

        hits.append(
            SearchHit(
                node_version_id=n.id,
                logical_node_id=n.logical_node_id,
                version_label=n.document_version.version_label if n.document_version else "unknown",
                section_number=n.section_number,
                heading=n.heading,
                snippet=snippet,
                content_hash=n.content_hash,
                page_start=n.page_start,
                page_end=n.page_end,
            )
        )

    return SearchResponse(
        query=q,
        version_filter=version,
        total_hits=len(hits),
        hits=hits,
    )


# ---------------------------------------------------------------------------
# Endpoint E: Compare Versions for a Logical Node
# ---------------------------------------------------------------------------

@app.get(
    f"{settings.api_v1_prefix}/nodes/{{logical_node_id}}/changes",
    response_model=NodeChangeComparisonResponse,
    tags=["Lineage & Changes"],
    summary="Compare node content and structure across versions",
)
def compare_node_versions(
    logical_node_id: str,
    from_version: str = Query("v1", description="Baseline version (e.g. 'v1')"),
    to_version: str = Query("v2", description="Target version (e.g. 'v2')"),
    db: Session = Depends(get_db),
) -> NodeChangeComparisonResponse:
    """Compare a conceptual logical node between two versions, highlighting textual and hash changes."""
    logical_node = repo.get_logical_node(db, logical_node_id)
    if not logical_node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Logical node with ID '{logical_node_id}' not found.",
        )

    nv_from = repo.get_node_version_by_logical_and_version(db, logical_node_id, from_version)
    nv_to = repo.get_node_version_by_logical_and_version(db, logical_node_id, to_version)

    if not nv_from and not nv_to:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Logical node '{logical_node_id}' does not exist in either '{from_version}' or '{to_version}'.",
        )

    from_snapshot = VersionNodeSnapshotResponse(
        exists=nv_from is not None,
        version_label=from_version,
        node_version_id=nv_from.id if nv_from else None,
        section_number=nv_from.section_number if nv_from else None,
        heading=nv_from.heading if nv_from else None,
        content_hash=nv_from.content_hash if nv_from else None,
        page_range=f"P{nv_from.page_start}-{nv_from.page_end}" if nv_from else None,
        body_text=nv_from.body_text if nv_from else None,
    )

    to_snapshot = VersionNodeSnapshotResponse(
        exists=nv_to is not None,
        version_label=to_version,
        node_version_id=nv_to.id if nv_to else None,
        section_number=nv_to.section_number if nv_to else None,
        heading=nv_to.heading if nv_to else None,
        content_hash=nv_to.content_hash if nv_to else None,
        page_range=f"P{nv_to.page_start}-{nv_to.page_end}" if nv_to else None,
        body_text=nv_to.body_text if nv_to else None,
    )

    diff_summary = None
    if nv_from and not nv_to:
        classification = ChangeClassification.REMOVED.value
        is_content_changed = True
        notes = f"Section was present in {from_version} but removed in {to_version}."
    elif not nv_from and nv_to:
        classification = ChangeClassification.ADDED.value
        is_content_changed = True
        notes = f"Section was newly added in {to_version}."
    else:
        # Exists in both
        if nv_from.content_hash == nv_to.content_hash:
            classification = ChangeClassification.UNCHANGED.value
            is_content_changed = False
            notes = "Content hashes and section structure are identical."
        else:
            classification = ChangeClassification.MODIFIED.value
            is_content_changed = True
            notes = "Content changed between versions."

            # Compute unified diff
            lines_from = nv_from.body_text.splitlines()
            lines_to = nv_to.body_text.splitlines()
            udiff = list(
                difflib.unified_diff(
                    lines_from,
                    lines_to,
                    fromfile=f"{from_version}:{nv_from.section_number}",
                    tofile=f"{to_version}:{nv_to.section_number}",
                    lineterm="",
                )
            )
            diff_summary = "\n".join(udiff) if udiff else "Formatting or table metadata changed."

    return NodeChangeComparisonResponse(
        logical_node_id=logical_node_id,
        canonical_section_number=logical_node.canonical_section_number,
        canonical_heading=logical_node.canonical_heading,
        change_classification=classification,
        is_content_changed=is_content_changed,
        from_version=from_snapshot,
        to_version=to_snapshot,
        diff_summary=diff_summary,
        matching_confidence=1.0,
        notes=notes,
    )
