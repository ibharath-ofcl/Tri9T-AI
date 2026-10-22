"""Impact analysis service for assessing document revisions across pinned selections.

Provides:
- Selection-centric impact analysis (inspects a specific selection against target version).
- Document-centric impact analysis (inspects all selections pinned to a prior version against target version).
- Medical-device traceability and change explanations.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import Selection
from app.repositories.document_repository import DocumentRepository
from app.services.staleness_classifier import (
    SAFETY_DISCLAIMER,
    AggregateSelectionStatus,
    NodeStalenessAssessment,
    NodeStalenessStatus,
    SelectionStalenessResult,
    StalenessClassifier,
)


@dataclass
class SelectionImpactReport:
    """Detailed impact report for an individual version-pinned selection."""
    selection_id: str
    selection_name: str
    pinned_version_label: str
    target_version_label: str
    aggregate_status: AggregateSelectionStatus
    human_review_required: bool
    disclaimer: str
    affected_nodes_count: int
    unaffected_nodes_count: int
    affected_nodes: List[NodeStalenessAssessment]
    unaffected_nodes: List[NodeStalenessAssessment]
    explanation: str


@dataclass
class DocumentImpactReport:
    """Document-wide impact report across all pinned selections for a version migration."""
    document_id: str
    from_version: str
    to_version: str
    total_selections_evaluated: int
    impacted_selections_count: int
    review_required_selections_count: int
    current_selections_count: int
    human_review_required: bool
    disclaimer: str
    affected_selections: List[SelectionImpactReport]
    unaffected_selections: List[SelectionImpactReport]


class ImpactAnalyzer:
    """Service assessing revision impact on version-pinned selections."""

    def __init__(
        self,
        repository: Optional[DocumentRepository] = None,
        classifier: Optional[StalenessClassifier] = None,
    ):
        self.repository = repository or DocumentRepository()
        self.classifier = classifier or StalenessClassifier()

    def analyze_selection_impact(
        self,
        db: Session,
        selection_id: str,
        target_version_label: str = "v2",
    ) -> SelectionImpactReport:
        """Analyze impact of target version migration on an individual selection."""
        staleness_res: SelectionStalenessResult = self.classifier.evaluate_selection_staleness(
            db=db,
            repository=self.repository,
            selection_id=selection_id,
            target_version_label=target_version_label,
        )

        affected: List[NodeStalenessAssessment] = []
        unaffected: List[NodeStalenessAssessment] = []

        for node_eval in staleness_res.node_assessments:
            if node_eval.status == NodeStalenessStatus.CURRENT:
                unaffected.append(node_eval)
            else:
                affected.append(node_eval)

        # Formulate human explanation
        if staleness_res.aggregate_status == AggregateSelectionStatus.CURRENT:
            explanation = (
                f"All {len(unaffected)} selected sections in '{staleness_res.selection_name}' "
                f"remain identical in version {target_version_label}. No QA test case impact detected."
            )
        elif staleness_res.aggregate_status == AggregateSelectionStatus.IMPACTED:
            timing_deltas = [d for a in affected for d in a.deltas if d.delta_type == "TIMING"]
            num_deltas = [d for a in affected for d in a.deltas if d.delta_type == "NUMERIC"]
            explanation = (
                f"Selection '{staleness_res.selection_name}' is IMPACTED: "
                f"{len(affected)} section(s) have critical modifications "
                f"({len(timing_deltas)} timing delta(s), {len(num_deltas)} numeric delta(s)). "
                f"Downstream verification test cases must be re-evaluated."
            )
        elif staleness_res.aggregate_status == AggregateSelectionStatus.REVIEW_REQUIRED:
            explanation = (
                f"Selection '{staleness_res.selection_name}' requires review: "
                f"{len(affected)} section(s) have wording or structural changes in version {target_version_label}."
            )
        else:
            explanation = (
                f"Selection '{staleness_res.selection_name}' has ambiguous section lineage. "
                f"Manual engineering review required before re-verifying tests."
            )

        return SelectionImpactReport(
            selection_id=staleness_res.selection_id,
            selection_name=staleness_res.selection_name,
            pinned_version_label=staleness_res.pinned_version_label,
            target_version_label=staleness_res.target_version_label,
            aggregate_status=staleness_res.aggregate_status,
            human_review_required=staleness_res.human_review_required,
            disclaimer=SAFETY_DISCLAIMER,
            affected_nodes_count=len(affected),
            unaffected_nodes_count=len(unaffected),
            affected_nodes=affected,
            unaffected_nodes=unaffected,
            explanation=explanation,
        )

    def analyze_document_impact(
        self,
        db: Session,
        document_id: str,
        from_version_label: str = "v1",
        to_version_label: str = "v2",
    ) -> DocumentImpactReport:
        """Evaluate document-wide revision impact across all selections pinned to from_version."""
        doc = self.repository.get_document_by_id(db, document_id)
        if not doc:
            raise ValueError(f"Document with ID '{document_id}' not found.")

        from_version = self.repository.get_version_by_label(db, document_id, from_version_label)
        if not from_version:
            raise ValueError(f"Source document version '{from_version_label}' not found.")

        to_version = self.repository.get_version_by_label(db, document_id, to_version_label)
        if not to_version:
            raise ValueError(f"Target document version '{to_version_label}' not found.")

        # Fetch all selections pinned to from_version
        selections: List[Selection] = self.repository.get_selections_for_version(
            db, from_version.id
        )

        affected_reports: List[SelectionImpactReport] = []
        unaffected_reports: List[SelectionImpactReport] = []

        impacted_count = 0
        review_required_count = 0
        current_count = 0

        for sel in selections:
            impact = self.analyze_selection_impact(
                db=db,
                selection_id=sel.id,
                target_version_label=to_version_label,
            )
            if impact.aggregate_status == AggregateSelectionStatus.CURRENT:
                current_count += 1
                unaffected_reports.append(impact)
            elif impact.aggregate_status == AggregateSelectionStatus.IMPACTED:
                impacted_count += 1
                affected_reports.append(impact)
            else:
                review_required_count += 1
                affected_reports.append(impact)

        human_review = (impacted_count + review_required_count) > 0

        return DocumentImpactReport(
            document_id=document_id,
            from_version=from_version_label,
            to_version=to_version_label,
            total_selections_evaluated=len(selections),
            impacted_selections_count=impacted_count,
            review_required_selections_count=review_required_count,
            current_selections_count=current_count,
            human_review_required=human_review,
            disclaimer=SAFETY_DISCLAIMER,
            affected_selections=affected_reports,
            unaffected_selections=unaffected_reports,
        )
