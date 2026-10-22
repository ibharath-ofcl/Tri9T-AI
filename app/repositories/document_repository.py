"""Repository layer for Document, DocumentVersion, LogicalNode, and NodeVersion entities."""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import Document, DocumentVersion, LogicalNode, NodeVersion


class DocumentRepository:
    """Repository handling all database queries and transactions for document intelligence."""

    def get_or_create_document(self, db: Session, document_key: str, title: str) -> Document:
        """Find existing Document by key or create a new conceptual document record."""
        stmt = select(Document).where(Document.document_key == document_key)
        doc = db.execute(stmt).scalar_one_or_none()
        if not doc:
            doc = Document(document_key=document_key, title=title)
            db.add(doc)
            db.flush()
        return doc

    def get_document_by_key(self, db: Session, document_key: str) -> Optional[Document]:
        """Fetch document by unique document key."""
        stmt = select(Document).where(Document.document_key == document_key)
        return db.execute(stmt).scalar_one_or_none()

    def get_document_by_id(self, db: Session, document_id: str) -> Optional[Document]:
        """Fetch document by primary key UUID."""
        return db.get(Document, document_id)

    def list_documents(self, db: Session) -> List[Document]:
        """List all registered conceptual documents."""
        stmt = select(Document).options(joinedload(Document.versions)).order_by(Document.created_at)
        return list(db.execute(stmt).unique().scalars().all())

    def get_version_by_label(
        self, db: Session, document_id: str, version_label: str
    ) -> Optional[DocumentVersion]:
        """Get a document version by document ID and version label (e.g. 'v1')."""
        stmt = (
            select(DocumentVersion)
            .where(
                DocumentVersion.document_id == document_id,
                DocumentVersion.version_label == version_label,
            )
        )
        return db.execute(stmt).scalar_one_or_none()

    def get_document_version(self, db: Session, version_id: str) -> Optional[DocumentVersion]:
        """Get document version by ID with document relationship loaded."""
        stmt = (
            select(DocumentVersion)
            .options(joinedload(DocumentVersion.document))
            .where(DocumentVersion.id == version_id)
        )
        return db.execute(stmt).scalar_one_or_none()

    def get_node_version(self, db: Session, node_version_id: str) -> Optional[NodeVersion]:
        """Get a specific node version with its parent, children, and logical node loaded."""
        stmt = (
            select(NodeVersion)
            .options(
                joinedload(NodeVersion.logical_node),
                joinedload(NodeVersion.children),
                joinedload(NodeVersion.document_version),
            )
            .where(NodeVersion.id == node_version_id)
        )
        return db.execute(stmt).unique().scalar_one_or_none()

    def get_top_level_sections(
        self, db: Session, document_id: str, version_label: str
    ) -> List[NodeVersion]:
        """Fetch all Level-1 sections for a given document version."""
        stmt = (
            select(NodeVersion)
            .join(DocumentVersion, NodeVersion.document_version_id == DocumentVersion.id)
            .options(joinedload(NodeVersion.children))
            .where(
                DocumentVersion.document_id == document_id,
                DocumentVersion.version_label == version_label,
                NodeVersion.level == 1,
            )
            .order_by(NodeVersion.source_order)
        )
        return list(db.execute(stmt).unique().scalars().all())

    def get_node_versions_for_document_version(
        self, db: Session, document_version_id: str
    ) -> List[NodeVersion]:
        """Get all node versions for a given document version ordered by source order."""
        stmt = (
            select(NodeVersion)
            .options(joinedload(NodeVersion.logical_node))
            .where(NodeVersion.document_version_id == document_version_id)
            .order_by(NodeVersion.source_order)
        )
        return list(db.execute(stmt).unique().scalars().all())

    def search_nodes(
        self,
        db: Session,
        query: str,
        version_label: Optional[str] = None,
        section_filter: Optional[str] = None,
        limit: int = 50,
    ) -> List[NodeVersion]:
        """Search node versions by heading or body text with version and section filtering."""
        stmt = (
            select(NodeVersion)
            .join(DocumentVersion, NodeVersion.document_version_id == DocumentVersion.id)
            .options(
                joinedload(NodeVersion.logical_node),
                joinedload(NodeVersion.document_version),
            )
        )

        filters = []
        if query:
            pattern = f"%{query}%"
            filters.append(
                or_(
                    NodeVersion.heading.ilike(pattern),
                    NodeVersion.body_text.ilike(pattern),
                    NodeVersion.source_metadata_json.ilike(pattern),
                )
            )

        if version_label:
            filters.append(DocumentVersion.version_label == version_label)

        if section_filter:
            filters.append(NodeVersion.section_number.startswith(section_filter))

        if filters:
            stmt = stmt.where(*filters)

        stmt = stmt.order_by(NodeVersion.source_order).limit(limit)
        return list(db.execute(stmt).unique().scalars().all())

    def get_node_version_by_logical_and_version(
        self, db: Session, logical_node_id: str, version_label: str
    ) -> Optional[NodeVersion]:
        """Get a node version for a given logical node in a specific document version."""
        stmt = (
            select(NodeVersion)
            .join(DocumentVersion, NodeVersion.document_version_id == DocumentVersion.id)
            .options(
                joinedload(NodeVersion.logical_node),
                joinedload(NodeVersion.document_version),
            )
            .where(
                NodeVersion.logical_node_id == logical_node_id,
                DocumentVersion.version_label == version_label,
            )
        )
        return db.execute(stmt).unique().scalar_one_or_none()

    def get_logical_node(self, db: Session, logical_node_id: str) -> Optional[LogicalNode]:
        """Fetch logical node by ID."""
        return db.get(LogicalNode, logical_node_id)
