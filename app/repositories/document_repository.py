"""Repository layer for Document, DocumentVersion, LogicalNode, and NodeVersion entities."""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    Document,
    DocumentVersion,
    LogicalNode,
    NodeVersion,
    Selection,
    SelectionNode,
)


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

    # -----------------------------------------------------------------------
    # Selection Repository Methods
    # -----------------------------------------------------------------------

    def create_selection(
        self,
        db: Session,
        document_id: str,
        document_version_id: str,
        name: str,
        description: Optional[str] = None,
        node_version_ids: Optional[List[str]] = None,
        metadata_json: Optional[str] = None,
    ) -> Selection:
        """Create a version-pinned named selection validating node references."""
        if not node_version_ids:
            raise ValueError("Selection creation requires a non-empty list of node_version_ids.")

        # Deduplicate node_version_ids preserving order
        seen = set()
        deduped_node_ids = []
        for nid in node_version_ids:
            if nid not in seen:
                seen.add(nid)
                deduped_node_ids.append(nid)

        # Validate that all nodes exist and belong strictly to this document_version_id and document_id
        stmt = select(NodeVersion).where(NodeVersion.id.in_(deduped_node_ids))
        nodes = list(db.execute(stmt).scalars().all())
        found_map = {n.id: n for n in nodes}

        missing_ids = [nid for nid in deduped_node_ids if nid not in found_map]
        if missing_ids:
            raise ValueError(f"Unknown node_version_ids: {missing_ids}")

        for nid, node in found_map.items():
            if node.document_version_id != document_version_id:
                raise ValueError(
                    f"NodeVersion '{nid}' belongs to version '{node.document_version_id}', "
                    f"not pinned version '{document_version_id}'. Mixed-version selections are forbidden."
                )

        selection = Selection(
            document_id=document_id,
            document_version_id=document_version_id,
            name=name,
            description=description,
            metadata_json=metadata_json,
        )
        db.add(selection)
        db.flush()

        for idx, nid in enumerate(deduped_node_ids):
            sn = SelectionNode(
                selection_id=selection.id,
                node_version_id=nid,
                order_index=idx,
            )
            selection.selection_nodes.append(sn)

        db.flush()
        return self.get_selection(db, selection.id)  # type: ignore

    def get_selection(self, db: Session, selection_id: str) -> Optional[Selection]:
        """Fetch selection by ID with document, document_version, and selection_nodes loaded."""
        stmt = (
            select(Selection)
            .options(
                joinedload(Selection.document),
                joinedload(Selection.document_version),
                joinedload(Selection.selection_nodes).joinedload(SelectionNode.node_version).joinedload(NodeVersion.logical_node),
            )
            .where(Selection.id == selection_id)
        )
        return db.execute(stmt).unique().scalar_one_or_none()

    def list_selections(
        self,
        db: Session,
        document_id: Optional[str] = None,
        version_label: Optional[str] = None,
    ) -> List[Selection]:
        """List selections with optional document and version filtering."""
        stmt = (
            select(Selection)
            .join(DocumentVersion, Selection.document_version_id == DocumentVersion.id)
            .options(
                joinedload(Selection.document_version),
                joinedload(Selection.selection_nodes),
            )
        )
        filters = []
        if document_id:
            filters.append(Selection.document_id == document_id)
        if version_label:
            filters.append(DocumentVersion.version_label == version_label)

        if filters:
            stmt = stmt.where(*filters)

        stmt = stmt.order_by(Selection.created_at.desc())
        return list(db.execute(stmt).unique().scalars().all())

    def update_selection(
        self,
        db: Session,
        selection: Selection,
        name: Optional[str] = None,
        description: Optional[str] = None,
        node_version_ids: Optional[List[str]] = None,
        metadata_json: Optional[str] = None,
    ) -> Selection:
        """Update selection metadata or nodes within the same pinned document version."""
        if name is not None:
            selection.name = name
        if description is not None:
            selection.description = description
        if metadata_json is not None:
            selection.metadata_json = metadata_json

        if node_version_ids is not None:
            # Deduplicate preserving order
            seen = set()
            deduped_ids = []
            for nid in node_version_ids:
                if nid not in seen:
                    seen.add(nid)
                    deduped_ids.append(nid)

            if deduped_ids:
                stmt = select(NodeVersion).where(NodeVersion.id.in_(deduped_ids))
                nodes = list(db.execute(stmt).scalars().all())
                found_map = {n.id: n for n in nodes}
                missing_ids = [nid for nid in deduped_ids if nid not in found_map]
                if missing_ids:
                    raise ValueError(f"Unknown node_version_ids: {missing_ids}")

                for nid, node in found_map.items():
                    if node.document_version_id != selection.document_version_id:
                        raise ValueError(
                            f"Node '{nid}' belongs to version '{node.document_version_id}', "
                            f"not selection's pinned version '{selection.document_version_id}'."
                        )

            # Clear existing selection nodes
            selection.selection_nodes.clear()
            db.flush()

            for idx, nid in enumerate(deduped_ids):
                sn = SelectionNode(
                    selection_id=selection.id,
                    node_version_id=nid,
                    order_index=idx,
                )
                selection.selection_nodes.append(sn)

        selection.updated_at = datetime.now(timezone.utc)
        db.flush()
        return self.get_selection(db, selection.id)  # type: ignore

    def delete_selection(self, db: Session, selection: Selection) -> None:
        """Delete a selection and its membership links without affecting document versions or nodes."""
        db.delete(selection)
        db.flush()

    def get_selections_for_version(
        self, db: Session, document_version_id: str
    ) -> List[Selection]:
        """Fetch all selections pinned to a specific document version."""
        stmt = (
            select(Selection)
            .options(
                joinedload(Selection.selection_nodes).joinedload(SelectionNode.node_version),
            )
            .where(Selection.document_version_id == document_version_id)
            .order_by(Selection.created_at)
        )
        return list(db.execute(stmt).unique().scalars().all())
