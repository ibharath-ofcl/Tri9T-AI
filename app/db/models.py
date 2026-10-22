"""Relational data models for document versioning, logical node lineage, and immutable trees.

Entities:
- Document: Conceptual identity of a manual (owns multiple versions).
- DocumentVersion: Immutable ingestion record of a manual version (v1, v2).
- LogicalNode: Permanent cross-version identity of a conceptual section.
- NodeVersion: Structural occurrence, text, and cryptographic hashes of a section in a version.
- Selection, SelectionNode: Version-pinned selections (prepared for Stage 4/5).
"""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def generate_uuid() -> str:
    """Generate string UUID4 primary key."""
    return str(uuid.uuid4())


class Document(Base):
    """Conceptual document identity (e.g. CT-200 Blood Pressure Monitor Manual)."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    document_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    latest_version_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("document_versions.id", use_alter=True, name="fk_documents_latest_version_id"),
        nullable=True,
    )

    # Relationships
    versions: Mapped[List[DocumentVersion]] = relationship(
        "DocumentVersion",
        back_populates="document",
        foreign_keys="[DocumentVersion.document_id]",
        cascade="all, delete-orphan",
        order_by="DocumentVersion.ingested_at",
    )
    logical_nodes: Mapped[List[LogicalNode]] = relationship(
        "LogicalNode",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    latest_version: Mapped[Optional[DocumentVersion]] = relationship(
        "DocumentVersion",
        foreign_keys=[latest_version_id],
        post_update=True,
    )


class DocumentVersion(Base):
    """Immutable ingestion snapshot of a specific document revision."""

    __tablename__ = "document_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_label: Mapped[str] = mapped_column(String(32), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_nodes: Mapped[int] = mapped_column(Integer, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    parser_version: Mapped[str] = mapped_column(String(32), default="0.2.0", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="SUCCESS", nullable=False)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    diagnostics_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("document_id", "version_label", name="uq_doc_version_label"),
    )

    # Relationships
    document: Mapped[Document] = relationship("Document", back_populates="versions", foreign_keys=[document_id])
    node_versions: Mapped[List[NodeVersion]] = relationship(
        "NodeVersion",
        back_populates="document_version",
        cascade="all, delete-orphan",
        order_by="NodeVersion.source_order",
    )
    selections: Mapped[List[Selection]] = relationship(
        "Selection",
        back_populates="document_version",
        cascade="all, delete-orphan",
    )


class LogicalNode(Base):
    """Permanent identity of a conceptual section across revisions."""

    __tablename__ = "logical_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canonical_section_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    canonical_heading: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    document: Mapped[Document] = relationship("Document", back_populates="logical_nodes")
    node_versions: Mapped[List[NodeVersion]] = relationship(
        "NodeVersion",
        back_populates="logical_node",
        cascade="all, delete-orphan",
        order_by="NodeVersion.source_order",
    )


class NodeVersion(Base):
    """Specific revision content and structural placement of a logical node in a version."""

    __tablename__ = "node_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    document_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    logical_node_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("logical_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_node_version_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("node_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    heading: Mapped[str] = mapped_column(String(255), nullable=False)
    section_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    heading_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    body_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    source_order: Mapped[int] = mapped_column(Integer, nullable=False)
    source_metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    diagnostics_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("document_version_id", "logical_node_id", name="uq_doc_version_logical_node"),
    )

    # Relationships
    document_version: Mapped[DocumentVersion] = relationship("DocumentVersion", back_populates="node_versions")
    logical_node: Mapped[LogicalNode] = relationship("LogicalNode", back_populates="node_versions")
    parent: Mapped[Optional[NodeVersion]] = relationship(
        "NodeVersion",
        remote_side=[id],
        back_populates="children",
    )
    children: Mapped[List[NodeVersion]] = relationship(
        "NodeVersion",
        back_populates="parent",
        cascade="all",
        order_by="NodeVersion.source_order",
    )


class Selection(Base):
    """Version-pinned named selection for QA generation."""

    __tablename__ = "selections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    document_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    document_version: Mapped[DocumentVersion] = relationship("DocumentVersion", back_populates="selections")
    selection_nodes: Mapped[List[SelectionNode]] = relationship(
        "SelectionNode",
        back_populates="selection",
        cascade="all, delete-orphan",
    )


class SelectionNode(Base):
    """Association table linking a selection to a specific NodeVersion."""

    __tablename__ = "selection_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    selection_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("selections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("node_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint("selection_id", "node_version_id", name="uq_selection_node_version"),
    )

    selection: Mapped[Selection] = relationship("Selection", back_populates="selection_nodes")
    node_version: Mapped[NodeVersion] = relationship("NodeVersion")
