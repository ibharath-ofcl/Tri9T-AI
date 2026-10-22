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
    DetectedValueDeltaSchema,
    DocumentImpactSummary,
    DocumentSummaryResponse,
    DocumentVersionSummary,
    NodeChangeComparisonResponse,
    NodeDetailResponse,
    NodeStalenessReport,
    SearchHit,
    SearchResponse,
    SectionItem,
    SelectionCreateRequest,
    SelectionDetailResponse,
    SelectionImpactResponse,
    SelectionNodeDetail,
    SelectionStalenessResponse,
    SelectionSummaryItem,
    SelectionUpdateRequest,
    VersionNodeSnapshotResponse,
)
from app.schemas.document import DocumentTree
from app.services.document_ingestion import (
    DocumentIngestionService,
    IngestionConflictError,
    IngestionResult,
)
from app.services.impact_analyzer import DocumentImpactReport, ImpactAnalyzer, SelectionImpactReport
from app.services.pdf_parser import CT200PDFParser
from app.services.staleness_classifier import (
    SelectionStalenessResult,
    StalenessClassifier,
)
from app.services.version_matcher import ChangeClassification
from app.repositories.test_suite_store import get_test_suite_store
from app.schemas.qa_test_case import (
    DocumentTestSuiteImpactResponse,
    GenerateTestSuiteRequest,
    GeneratedTestSuitePayload,
    TestSuiteStalenessResponse,
)
from app.services.llm_provider import (
    LLMConfigurationError,
    LLMProviderError,
    LLMTransientError,
)
from app.services.qa_generation_service import (
    GenerationValidationError,
    IdempotencyConflictError,
    QAGenerationService,
)

app = FastAPI(
    title=settings.app_name,
    version="0.5.0",
    description="Document Intelligence, Lineage, Staleness & QA Generation API for CT-200 Blood Pressure Monitor Manuals",
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
classifier = StalenessClassifier()
impact_analyzer = ImpactAnalyzer(repository=repo, classifier=classifier)
test_suite_store = get_test_suite_store()
qa_service = QAGenerationService(
    repository=repo,
    store=test_suite_store,
    classifier=classifier,
)

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


# ---------------------------------------------------------------------------
# Stage 4 Endpoints: Selections, Staleness, and Impact Detection
# ---------------------------------------------------------------------------

def _build_selection_detail_response(sel) -> SelectionDetailResponse:
    """Helper to convert a Selection entity into SelectionDetailResponse."""
    node_details = []
    for sn in sel.selection_nodes:
        nv = sn.node_version
        if nv:
            node_details.append(
                SelectionNodeDetail(
                    node_version_id=nv.id,
                    logical_node_id=nv.logical_node_id,
                    section_number=nv.section_number,
                    heading=nv.heading,
                    level=nv.level,
                    content_hash=nv.content_hash,
                    page_start=nv.page_start,
                    page_end=nv.page_end,
                    source_order=nv.source_order,
                )
            )
    return SelectionDetailResponse(
        id=sel.id,
        document_id=sel.document_id,
        document_version_id=sel.document_version_id,
        version_label=sel.document_version.version_label if sel.document_version else "unknown",
        name=sel.name,
        description=sel.description,
        created_at=sel.created_at,
        updated_at=sel.updated_at,
        total_nodes=len(node_details),
        nodes=node_details,
        metadata_json=sel.metadata_json,
    )


def _to_node_staleness_report(a) -> NodeStalenessReport:
    """Helper to map NodeStalenessAssessment dataclass to Pydantic NodeStalenessReport."""
    deltas = [
        DetectedValueDeltaSchema(
            delta_type=d.delta_type,
            old_value=d.old_value,
            new_value=d.new_value,
            unit=d.unit,
            context=d.context,
            explanation=d.explanation,
        )
        for d in a.deltas
    ]
    return NodeStalenessReport(
        node_version_id=a.node_version_id,
        logical_node_id=a.logical_node_id,
        section_number=a.section_number,
        heading=a.heading,
        from_version_label=a.from_version_label,
        to_version_label=a.to_version_label,
        status=a.status.value if hasattr(a.status, "value") else str(a.status),
        classification=a.classification.value if hasattr(a.classification, "value") else str(a.classification),
        from_content_hash=a.from_content_hash,
        to_content_hash=a.to_content_hash,
        target_node_version_id=a.target_node_version_id,
        target_section_number=a.target_section_number,
        target_heading=a.target_heading,
        deltas=deltas,
        diff_summary=a.diff_summary,
        explanation=a.explanation,
        human_review_required=a.human_review_required,
        evidence_level=a.evidence_level,
    )


def _to_selection_impact_response(r: SelectionImpactReport) -> SelectionImpactResponse:
    """Helper to map SelectionImpactReport dataclass to Pydantic SelectionImpactResponse."""
    return SelectionImpactResponse(
        selection_id=r.selection_id,
        selection_name=r.selection_name,
        pinned_version_label=r.pinned_version_label,
        target_version_label=r.target_version_label,
        aggregate_status=r.aggregate_status.value if hasattr(r.aggregate_status, "value") else str(r.aggregate_status),
        human_review_required=r.human_review_required,
        disclaimer=r.disclaimer,
        affected_nodes_count=r.affected_nodes_count,
        unaffected_nodes_count=r.unaffected_nodes_count,
        affected_nodes=[_to_node_staleness_report(a) for a in r.affected_nodes],
        unaffected_nodes=[_to_node_staleness_report(u) for u in r.unaffected_nodes],
        explanation=r.explanation,
    )


@app.post(
    f"{settings.api_v1_prefix}/selections",
    response_model=SelectionDetailResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Selections"],
    summary="Create a named, version-pinned selection",
)
def create_selection_endpoint(
    req: SelectionCreateRequest,
    db: Session = Depends(get_db),
) -> SelectionDetailResponse:
    """Create a named selection of nodes pinned to an exact immutable document version."""
    # Resolve document_id and document_version_id
    doc_id = req.document_id
    doc_version_id = req.document_version_id

    if doc_version_id:
        doc_version = repo.get_document_version(db, doc_version_id)
        if not doc_version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"DocumentVersion with ID '{doc_version_id}' not found.",
            )
        doc_id = doc_version.document_id
    elif doc_id and req.version_label:
        doc_version = repo.get_version_by_label(db, document_id=doc_id, version_label=req.version_label)
        if not doc_version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Version '{req.version_label}' not found for document '{doc_id}'.",
            )
        doc_version_id = doc_version.id
    elif req.version_label:
        docs = repo.list_documents(db)
        if not docs:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No documents found in database. Ingest manuals before creating selections.",
            )
        doc = docs[0]
        doc_id = doc.id
        doc_version = repo.get_version_by_label(db, document_id=doc.id, version_label=req.version_label)
        if not doc_version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Version '{req.version_label}' not found for document '{doc.id}'.",
            )
        doc_version_id = doc_version.id
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must provide either 'document_version_id' or 'version_label' (with optional 'document_id').",
        )

    try:
        selection = repo.create_selection(
            db=db,
            document_id=doc_id,  # type: ignore
            document_version_id=doc_version_id,  # type: ignore
            name=req.name,
            description=req.description,
            node_version_ids=req.node_version_ids,
            metadata_json=req.metadata_json,
        )
        db.commit()
        return _build_selection_detail_response(selection)
    except ValueError as val_err:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(val_err))
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@app.get(
    f"{settings.api_v1_prefix}/selections",
    response_model=List[SelectionSummaryItem],
    tags=["Selections"],
    summary="List named selections",
)
def list_selections_endpoint(
    document_id: Optional[str] = Query(None, description="Filter by document ID"),
    version: Optional[str] = Query(None, description="Filter by pinned version label ('v1', 'v2')"),
    db: Session = Depends(get_db),
) -> List[SelectionSummaryItem]:
    """List all created selections with optional document and version filtering."""
    selections = repo.list_selections(db, document_id=document_id, version_label=version)
    results = []
    for s in selections:
        results.append(
            SelectionSummaryItem(
                id=s.id,
                document_id=s.document_id,
                document_version_id=s.document_version_id,
                version_label=s.document_version.version_label if s.document_version else "unknown",
                name=s.name,
                description=s.description,
                created_at=s.created_at,
                updated_at=s.updated_at,
                total_nodes=len(s.selection_nodes),
            )
        )
    return results


@app.get(
    f"{settings.api_v1_prefix}/selections/{{selection_id}}",
    response_model=SelectionDetailResponse,
    tags=["Selections"],
    summary="Retrieve selection details and pinned nodes",
)
def get_selection_endpoint(
    selection_id: str,
    db: Session = Depends(get_db),
) -> SelectionDetailResponse:
    """Retrieve full details of a version-pinned selection including all selected node snapshots."""
    sel = repo.get_selection(db, selection_id)
    if not sel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Selection with ID '{selection_id}' not found.",
        )
    return _build_selection_detail_response(sel)


@app.patch(
    f"{settings.api_v1_prefix}/selections/{{selection_id}}",
    response_model=SelectionDetailResponse,
    tags=["Selections"],
    summary="Update selection metadata or node membership",
)
def update_selection_endpoint(
    selection_id: str,
    req: SelectionUpdateRequest,
    db: Session = Depends(get_db),
) -> SelectionDetailResponse:
    """Update selection name, description, or nodes within the same pinned document version."""
    sel = repo.get_selection(db, selection_id)
    if not sel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Selection with ID '{selection_id}' not found.",
        )

    try:
        updated = repo.update_selection(
            db=db,
            selection=sel,
            name=req.name,
            description=req.description,
            node_version_ids=req.node_version_ids,
            metadata_json=req.metadata_json,
        )
        db.commit()
        return _build_selection_detail_response(updated)
    except ValueError as val_err:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(val_err))
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@app.delete(
    f"{settings.api_v1_prefix}/selections/{{selection_id}}",
    tags=["Selections"],
    summary="Delete a selection",
)
def delete_selection_endpoint(
    selection_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Delete a selection and its membership links without affecting document versions or nodes."""
    sel = repo.get_selection(db, selection_id)
    if not sel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Selection with ID '{selection_id}' not found.",
        )
    repo.delete_selection(db, sel)
    db.commit()
    return {
        "status": "success",
        "message": f"Selection '{selection_id}' successfully deleted.",
    }


@app.get(
    f"{settings.api_v1_prefix}/selections/{{selection_id}}/staleness",
    response_model=SelectionStalenessResponse,
    tags=["Staleness & Impact"],
    summary="Evaluate staleness of a pinned selection against a target version",
)
def get_selection_staleness_endpoint(
    selection_id: str,
    target_version: str = Query("v2", description="Target version label to evaluate against (e.g. 'v2')"),
    db: Session = Depends(get_db),
) -> SelectionStalenessResponse:
    """Assess whether sections in a pinned selection are stale relative to target version."""
    try:
        res: SelectionStalenessResult = classifier.evaluate_selection_staleness(
            db=db,
            repository=repo,
            selection_id=selection_id,
            target_version_label=target_version,
        )
        return SelectionStalenessResponse(
            selection_id=res.selection_id,
            selection_name=res.selection_name,
            pinned_version_label=res.pinned_version_label,
            target_version_label=res.target_version_label,
            aggregate_status=res.aggregate_status.value,
            summary=res.summary_counts,
            human_review_required=res.human_review_required,
            disclaimer=res.disclaimer,
            node_assessments=[_to_node_staleness_report(a) for a in res.node_assessments],
        )
    except ValueError as val_err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(val_err))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@app.get(
    f"{settings.api_v1_prefix}/selections/{{selection_id}}/impact",
    response_model=SelectionImpactResponse,
    tags=["Staleness & Impact"],
    summary="Generate explainable impact report for an individual selection",
)
def get_selection_impact_endpoint(
    selection_id: str,
    target_version: str = Query("v2", description="Target version label to evaluate against (e.g. 'v2')"),
    db: Session = Depends(get_db),
) -> SelectionImpactResponse:
    """Analyze which nodes in a selection are affected, removed, moved, or ambiguous in target version."""
    try:
        report: SelectionImpactReport = impact_analyzer.analyze_selection_impact(
            db=db,
            selection_id=selection_id,
            target_version_label=target_version,
        )
        return _to_selection_impact_response(report)
    except ValueError as val_err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(val_err))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@app.get(
    f"{settings.api_v1_prefix}/documents/{{document_id}}/impact",
    response_model=DocumentImpactSummary,
    tags=["Staleness & Impact"],
    summary="Document-wide impact report across all pinned selections",
)
def get_document_impact_endpoint(
    document_id: str,
    from_version: str = Query("v1", description="Baseline version (e.g. 'v1')"),
    to_version: str = Query("v2", description="Target version (e.g. 'v2')"),
    db: Session = Depends(get_db),
) -> DocumentImpactSummary:
    """Evaluate document-wide revision impact across all selections pinned to from_version."""
    try:
        report: DocumentImpactReport = impact_analyzer.analyze_document_impact(
            db=db,
            document_id=document_id,
            from_version_label=from_version,
            to_version_label=to_version,
        )
        return DocumentImpactSummary(
            document_id=report.document_id,
            from_version=report.from_version,
            to_version=report.to_version,
            total_selections_evaluated=report.total_selections_evaluated,
            impacted_selections_count=report.impacted_selections_count,
            review_required_selections_count=report.review_required_selections_count,
            current_selections_count=report.current_selections_count,
            human_review_required=report.human_review_required,
            disclaimer=report.disclaimer,
            affected_selections=[_to_selection_impact_response(s) for s in report.affected_selections],
            unaffected_selections=[_to_selection_impact_response(s) for s in report.unaffected_selections],
        )
    except ValueError as val_err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(val_err))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


# ---------------------------------------------------------------------------
# Stage 5 Endpoints: Grounded QA Test Generation, Retrieval & Staleness
# ---------------------------------------------------------------------------

@app.post(
    f"{settings.api_v1_prefix}/selections/{{selection_id}}/test-suites",
    response_model=GeneratedTestSuitePayload,
    status_code=status.HTTP_201_CREATED,
    tags=["QA Test Generation"],
    summary="Generate 3-5 grounded QA test cases from a version-pinned selection",
)
def generate_selection_test_suites_endpoint(
    selection_id: str,
    req: GenerateTestSuiteRequest = GenerateTestSuiteRequest(),
    db: Session = Depends(get_db),
) -> GeneratedTestSuitePayload:
    """Generate, strictly validate, and persist QA test cases from a pinned selection."""
    try:
        return qa_service.generate_test_suite(
            db=db,
            selection_id=selection_id,
            requested_count=req.count,
            idempotency_key=req.idempotency_key,
            focus_topic=req.test_type_focus,
        )
    except IdempotencyConflictError as ice:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(ice))
    except ValueError as val_err:
        err_msg = str(val_err)
        if "not found" in err_msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg)
    except LLMConfigurationError as cfg_err:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(cfg_err))
    except GenerationValidationError as gve:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(gve))
    except LLMTransientError as te:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(te))
    except LLMProviderError as pe:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(pe))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@app.post(
    f"{settings.api_v1_prefix}/nodes/{{node_version_id}}/test-suites",
    response_model=GeneratedTestSuitePayload,
    status_code=status.HTTP_201_CREATED,
    tags=["QA Test Generation"],
    summary="Generate 3-5 grounded QA test cases from an individual node version",
)
def generate_node_test_suites_endpoint(
    node_version_id: str,
    req: GenerateTestSuiteRequest = GenerateTestSuiteRequest(),
    db: Session = Depends(get_db),
) -> GeneratedTestSuitePayload:
    """Generate, strictly validate, and persist QA test cases from an individual node snapshot."""
    try:
        return qa_service.generate_test_suite(
            db=db,
            node_version_id=node_version_id,
            requested_count=req.count,
            idempotency_key=req.idempotency_key,
            focus_topic=req.test_type_focus,
        )
    except IdempotencyConflictError as ice:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(ice))
    except ValueError as val_err:
        err_msg = str(val_err)
        if "not found" in err_msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg)
    except LLMConfigurationError as cfg_err:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(cfg_err))
    except GenerationValidationError as gve:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(gve))
    except LLMTransientError as te:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(te))
    except LLMProviderError as pe:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(pe))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@app.get(
    f"{settings.api_v1_prefix}/test-suites/{{generation_id}}",
    response_model=GeneratedTestSuitePayload,
    tags=["QA Test Generation"],
    summary="Retrieve a generated test suite and individual test cases by generation ID",
)
def get_test_suite_endpoint(generation_id: str) -> GeneratedTestSuitePayload:
    """Retrieve persisted test suite with complete source provenance and test case schemas."""
    suite = qa_service.store.get_test_suite(generation_id)
    if not suite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Generated test suite with ID '{generation_id}' not found in document store.",
        )
    return suite


@app.get(
    f"{settings.api_v1_prefix}/selections/{{selection_id}}/test-suites",
    response_model=List[GeneratedTestSuitePayload],
    tags=["QA Test Generation"],
    summary="List all generated test suites for a selection",
)
def list_selection_test_suites_endpoint(
    selection_id: str,
    limit: int = Query(50, ge=1, le=200, description="Max test suites to return"),
    db: Session = Depends(get_db),
) -> List[GeneratedTestSuitePayload]:
    """Retrieve all test suites generated from the specified selection."""
    sel = repo.get_selection(db, selection_id)
    if not sel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Selection with ID '{selection_id}' not found.",
        )
    return qa_service.store.list_test_suites(selection_id=selection_id, limit=limit)


@app.get(
    f"{settings.api_v1_prefix}/nodes/{{node_version_id}}/test-suites",
    response_model=List[GeneratedTestSuitePayload],
    tags=["QA Test Generation"],
    summary="List all test suites referencing an exact source node snapshot",
)
def list_node_test_suites_endpoint(
    node_version_id: str,
    limit: int = Query(50, ge=1, le=200, description="Max test suites to return"),
    db: Session = Depends(get_db),
) -> List[GeneratedTestSuitePayload]:
    """Retrieve all test suites containing test cases bound to the specified node version."""
    nv = repo.get_node_version(db, node_version_id)
    if not nv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node version with ID '{node_version_id}' not found.",
        )
    return qa_service.store.list_test_suites(node_version_id=node_version_id, limit=limit)


@app.get(
    f"{settings.api_v1_prefix}/test-suites/{{generation_id}}/staleness",
    response_model=TestSuiteStalenessResponse,
    tags=["QA Test Staleness & Impact"],
    summary="Evaluate test suite staleness against a target document version",
)
def get_test_suite_staleness_endpoint(
    generation_id: str,
    target_version: str = Query("v2", description="Target version label (e.g. 'v2')"),
    db: Session = Depends(get_db),
) -> TestSuiteStalenessResponse:
    """Assess whether generated test cases are stale relative to target version without mutating original provenance."""
    try:
        return qa_service.evaluate_test_suite_staleness(
            db=db,
            generation_id=generation_id,
            target_version_label=target_version,
        )
    except ValueError as val_err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(val_err))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@app.get(
    f"{settings.api_v1_prefix}/documents/{{document_id}}/test-suite-impact",
    response_model=DocumentTestSuiteImpactResponse,
    tags=["QA Test Staleness & Impact"],
    summary="Document-wide impact analysis across all generated test suites",
)
def get_document_test_suite_impact_endpoint(
    document_id: str,
    from_version: str = Query("v1", description="Baseline version (e.g. 'v1')"),
    to_version: str = Query("v2", description="Target version (e.g. 'v2')"),
    db: Session = Depends(get_db),
) -> DocumentTestSuiteImpactResponse:
    """Evaluate document-wide revision impact across all test suites generated for from_version."""
    try:
        return qa_service.analyze_document_test_suite_impact(
            db=db,
            document_id=document_id,
            from_version_label=from_version,
            to_version_label=to_version,
        )
    except ValueError as val_err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(val_err))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


