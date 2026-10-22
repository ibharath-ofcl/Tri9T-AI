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


SectionItem.model_rebuild()
