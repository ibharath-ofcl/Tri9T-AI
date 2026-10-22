"""API request and response Pydantic models for Stage 3 browsing and search."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DocumentVersionSummary(BaseModel):
    version_id: str
    version_label: str
    source_filename: str
    source_sha256: str
    page_count: int
    total_nodes: int
    ingested_at: datetime
    status: str


class DocumentSummaryResponse(BaseModel):
    document_id: str
    document_key: str
    title: str
    latest_version_id: Optional[str] = None
    versions: List[DocumentVersionSummary] = Field(default_factory=list)


class SectionItem(BaseModel):
    node_version_id: str
    logical_node_id: str
    section_number: Optional[str] = None
    heading: str
    level: int
    page_start: int
    page_end: int
    source_order: int
    content_hash: str
    children_count: int = 0
    children: List["SectionItem"] = Field(default_factory=list)


class NodeDetailResponse(BaseModel):
    node_version_id: str
    logical_node_id: str
    document_version_id: str
    version_label: str
    heading: str
    section_number: Optional[str] = None
    level: int
    parent_node_version_id: Optional[str] = None
    body_text: str
    content_hash: str
    heading_hash: str
    body_hash: str
    page_start: int
    page_end: int
    source_order: int
    tables: List[Dict[str, Any]] = Field(default_factory=list)
    diagnostics: List[str] = Field(default_factory=list)
    children: List[SectionItem] = Field(default_factory=list)


class SearchHit(BaseModel):
    node_version_id: str
    logical_node_id: str
    version_label: str
    section_number: Optional[str] = None
    heading: str
    snippet: str
    content_hash: str
    page_start: int
    page_end: int


class SearchResponse(BaseModel):
    query: str
    version_filter: Optional[str] = None
    total_hits: int
    hits: List[SearchHit] = Field(default_factory=list)


class VersionNodeSnapshotResponse(BaseModel):
    exists: bool
    version_label: str
    node_version_id: Optional[str] = None
    section_number: Optional[str] = None
    heading: Optional[str] = None
    content_hash: Optional[str] = None
    page_range: Optional[str] = None
    body_text: Optional[str] = None


class NodeChangeComparisonResponse(BaseModel):
    logical_node_id: str
    canonical_section_number: Optional[str] = None
    canonical_heading: Optional[str] = None
    change_classification: str
    is_content_changed: bool
    from_version: VersionNodeSnapshotResponse
    to_version: VersionNodeSnapshotResponse
    diff_summary: Optional[str] = None
    matching_confidence: float = 1.0
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Stage 4 Schemas: Selections, Staleness, and Impact Detection
# ---------------------------------------------------------------------------

class SelectionCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="Human-readable selection name")
    description: Optional[str] = Field(None, description="Optional description of QA scope")
    document_id: Optional[str] = Field(None, description="Document ID (optional if document_version_id given)")
    version_label: Optional[str] = Field(None, description="Version label ('v1', 'v2')")
    document_version_id: Optional[str] = Field(None, description="Exact document version ID to pin")
    node_version_ids: List[str] = Field(..., min_length=1, description="List of node_version UUIDs to select")
    metadata_json: Optional[str] = Field(None, description="Optional metadata for downstream QA generation")


class SelectionUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = None
    node_version_ids: Optional[List[str]] = Field(None, description="New list of node_version IDs (must belong to pinned version)")
    metadata_json: Optional[str] = None


class SelectionNodeDetail(BaseModel):
    node_version_id: str
    logical_node_id: str
    section_number: Optional[str] = None
    heading: str
    level: int
    content_hash: str
    page_start: int
    page_end: int
    source_order: int


class SelectionDetailResponse(BaseModel):
    id: str
    document_id: str
    document_version_id: str
    version_label: str
    name: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    total_nodes: int
    nodes: List[SelectionNodeDetail] = Field(default_factory=list)
    metadata_json: Optional[str] = None


class SelectionSummaryItem(BaseModel):
    id: str
    document_id: str
    document_version_id: str
    version_label: str
    name: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    total_nodes: int


class DetectedValueDeltaSchema(BaseModel):
    delta_type: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    unit: Optional[str] = None
    context: str
    explanation: str


class NodeStalenessReport(BaseModel):
    node_version_id: str
    logical_node_id: str
    section_number: Optional[str] = None
    heading: str
    from_version_label: str
    to_version_label: str
    status: str
    classification: str
    from_content_hash: Optional[str] = None
    to_content_hash: Optional[str] = None
    target_node_version_id: Optional[str] = None
    target_section_number: Optional[str] = None
    target_heading: Optional[str] = None
    deltas: List[DetectedValueDeltaSchema] = Field(default_factory=list)
    diff_summary: Optional[str] = None
    explanation: str
    human_review_required: bool
    evidence_level: str


class SelectionStalenessResponse(BaseModel):
    selection_id: str
    selection_name: str
    pinned_version_label: str
    target_version_label: str
    aggregate_status: str
    summary: Dict[str, int]
    human_review_required: bool
    disclaimer: str
    node_assessments: List[NodeStalenessReport] = Field(default_factory=list)


class SelectionImpactResponse(BaseModel):
    selection_id: str
    selection_name: str
    pinned_version_label: str
    target_version_label: str
    aggregate_status: str
    human_review_required: bool
    disclaimer: str
    affected_nodes_count: int
    unaffected_nodes_count: int
    affected_nodes: List[NodeStalenessReport] = Field(default_factory=list)
    unaffected_nodes: List[NodeStalenessReport] = Field(default_factory=list)
    explanation: str


class DocumentImpactSummary(BaseModel):
    document_id: str
    from_version: str
    to_version: str
    total_selections_evaluated: int
    impacted_selections_count: int
    review_required_selections_count: int
    current_selections_count: int
    human_review_required: bool
    disclaimer: str
    affected_selections: List[SelectionImpactResponse] = Field(default_factory=list)
    unaffected_selections: List[SelectionImpactResponse] = Field(default_factory=list)


SectionItem.model_rebuild()

