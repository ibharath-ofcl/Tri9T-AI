"""Pydantic models for extracted CT-200 document structures.

Provides both recursive hierarchy representations (DocumentNode -> children)
and flat relational models (DocumentFlatNode) to avoid circular serialization
issues when storing or transmitting trees.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TableData(BaseModel):
    """Structured representation of an extracted table."""
    headers: List[str] = Field(default_factory=list, description="Column header strings")
    rows: List[List[str]] = Field(default_factory=list, description="Matrix of row values")
    page_number: int = Field(..., description="Source page number where table resides")
    bbox: Optional[List[float]] = Field(None, description="Bounding box [x0, top, x1, bottom]")
    caption: Optional[str] = Field(None, description="Optional associated caption text")


class SourceBlock(BaseModel):
    """Provenance tracking for an individual extracted layout block."""
    page_number: int
    block_type: str = Field(..., description="'heading' | 'paragraph' | 'list_item' | 'table'")
    text: str
    font_name: Optional[str] = None
    font_size: Optional[float] = None
    is_bold: bool = False
    bbox: Optional[List[float]] = None


class DiagnosticWarning(BaseModel):
    """Diagnostic uncertainty or structural irregularity record."""
    code: str = Field(..., description="Machine-readable warning code (e.g., IR-1, IR-3)")
    message: str = Field(..., description="Human-readable description of the anomaly")
    severity: str = Field(default="warning", description="'info' | 'warning' | 'error'")
    section_number: Optional[str] = None
    page_number: Optional[int] = None


class DocumentNode(BaseModel):
    """Hierarchical document node representing a section, subsection, or title."""
    node_id: str = Field(..., description="Deterministic or unique occurrence identifier")
    section_number: Optional[str] = Field(None, description="Detected numbering pattern (e.g., '2.1.1.1')")
    heading: Optional[str] = Field(None, description="Heading text of the section")
    level: int = Field(..., description="Hierarchy depth (0=doc title, 1=main section, 2=sub, etc.)")
    body_text: str = Field(default="", description="Aggregated body content text")
    parent_id: Optional[str] = Field(None, description="Occurrence ID of parent section node")
    document_order: int = Field(..., description="1-indexed sequence order in original PDF stream")
    page_start: int = Field(..., description="First source page where section content appears")
    page_end: int = Field(..., description="Last source page where section content appears")
    heading_font_size: Optional[float] = Field(None, description="Font size in pt for heading line")
    heading_is_bold: bool = Field(default=False, description="Whether heading font was bold")
    extraction_confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Extraction confidence score")
    warnings: List[str] = Field(default_factory=list, description="Uncertainties or edge cases flagged")
    content_hash: str = Field(..., description="SHA-256 hash of normalized heading + body")
    heading_hash: str = Field(..., description="SHA-256 hash of normalized heading text")
    body_hash: str = Field(..., description="SHA-256 hash of normalized body text")
    tables: List[TableData] = Field(default_factory=list, description="Tables associated with this section")
    source_blocks: List[SourceBlock] = Field(default_factory=list, description="Provenance blocks")
    children: List[DocumentNode] = Field(default_factory=list, description="Recursive child section nodes")


class DocumentFlatNode(BaseModel):
    """Non-recursive flat projection of DocumentNode for serialization and relational persistence."""
    node_id: str
    section_number: Optional[str] = None
    heading: Optional[str] = None
    level: int
    body_text: str
    parent_id: Optional[str] = None
    child_ids: List[str] = Field(default_factory=list)
    document_order: int
    page_start: int
    page_end: int
    extraction_confidence: float
    warnings: List[str] = Field(default_factory=list)
    content_hash: str
    heading_hash: str
    body_hash: str
    tables_count: int = 0


class DocumentMetadata(BaseModel):
    """Document-level metadata and ingestion telemetry."""
    filename: str
    version: str = Field(default="unknown", description="'v1' | 'v2' | user-defined")
    file_size_bytes: int
    sha256: str
    page_count: int
    total_nodes: int
    extracted_at: str


class DocumentTree(BaseModel):
    """Top-level reconstructed document structure."""
    metadata: DocumentMetadata
    title: Optional[str] = None
    nodes: List[DocumentNode] = Field(default_factory=list, description="Top-level nodes with recursive children")
    diagnostics: List[DiagnosticWarning] = Field(default_factory=list, description="Global and node diagnostics")
    summary: Dict[str, Any] = Field(default_factory=dict, description="Summary statistics")


# Rebuild recursive model references
DocumentNode.model_rebuild()
