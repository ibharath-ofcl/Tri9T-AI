"""Explainable change and staleness classification engine for medical-device documentation.

Implements rule-based, deterministic classification across document revisions:
Categories:
- NO_CHANGE: Cryptographically matching content hashes.
- FORMATTING_ONLY: Text identical under whitespace and non-semantic normalization.
- TIMING_CHANGE: Explicit time quantities (seconds, ms, duration) modified.
- NUMERIC_CHANGE: Measured thresholds, cycle counts, pressures, percentages changed.
- STRUCTURAL_CHANGE: Section hierarchy, parentage, or table schemas modified.
- WORDING_CHANGE: Textual modifications without numeric or temporal alterations.
- ADDED / REMOVED / MOVED / AMBIGUOUS: Structural lifecycle states from version lineage.
- UNCLASSIFIED: Fallback when evidence is insufficient.

Invariants:
- A medical QA test case is NEVER marked CURRENT if underlying numbers, times, or safety thresholds changed.
- Objective change detection is strictly separated from clinical safety validation.
- All classifications provide transparent evidence and surrounding context.
"""

from __future__ import annotations
import difflib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.db.models import NodeVersion, Selection, SelectionNode
from app.repositories.document_repository import DocumentRepository

SAFETY_DISCLAIMER: str = (
    "Notice: Automated impact and staleness classification is a software traceability and change-analysis aid, "
    "not clinical validation or regulatory approval. All detected changes require verification by qualified personnel."
)


class StalenessCategory(str, Enum):
    """Granular categorization of section content evolution."""
    NO_CHANGE = "NO_CHANGE"
    FORMATTING_ONLY = "FORMATTING_ONLY"
    WORDING_CHANGE = "WORDING_CHANGE"
    NUMERIC_CHANGE = "NUMERIC_CHANGE"
    TIMING_CHANGE = "TIMING_CHANGE"
    STRUCTURAL_CHANGE = "STRUCTURAL_CHANGE"
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    MOVED = "MOVED"
    AMBIGUOUS = "AMBIGUOUS"
    UNCLASSIFIED = "UNCLASSIFIED"


class NodeStalenessStatus(str, Enum):
    """Per-node staleness status relative to a target version."""
    CURRENT = "CURRENT"
    STALE = "STALE"
    REMOVED = "REMOVED"
    MOVED = "MOVED"
    AMBIGUOUS = "AMBIGUOUS"
    UNAVAILABLE = "UNAVAILABLE"


class AggregateSelectionStatus(str, Enum):
    """High-level status of a version-pinned selection when evaluated against a newer revision."""
    CURRENT = "CURRENT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    IMPACTED = "IMPACTED"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass
class DetectedDelta:
    """Explicit, contextual record of a detected value or threshold modification."""
    delta_type: str  # "TIMING", "NUMERIC", "CODE_RANGE", "TABLE_ROW", "STRUCTURAL"
    old_value: Optional[str]
    new_value: Optional[str]
    unit: Optional[str]
    context: str
    explanation: str


@dataclass
class NodeStalenessAssessment:
    """Full explainable staleness evaluation for a specific node snapshot."""
    node_version_id: str
    logical_node_id: str
    section_number: Optional[str]
    heading: str
    from_version_label: str
    to_version_label: str
    status: NodeStalenessStatus
    classification: StalenessCategory
    from_content_hash: Optional[str]
    to_content_hash: Optional[str]
    target_node_version_id: Optional[str] = None
    target_section_number: Optional[str] = None
    target_heading: Optional[str] = None
    deltas: List[DetectedDelta] = field(default_factory=list)
    diff_summary: Optional[str] = None
    explanation: str = ""
    human_review_required: bool = False
    evidence_level: str = "HIGH"  # "HIGH", "MEDIUM", "LOW"


@dataclass
class SelectionStalenessResult:
    """Aggregated staleness report for an entire named selection."""
    selection_id: str
    selection_name: str
    pinned_version_label: str
    target_version_label: str
    aggregate_status: AggregateSelectionStatus
    summary_counts: Dict[str, int]
    human_review_required: bool
    disclaimer: str
    node_assessments: List[NodeStalenessAssessment]


# Regex patterns for unit and quantity extraction
TIMING_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(seconds?|secs?|s|milliseconds?|ms|minutes?|mins?|m|hours?|hrs?|h)\b",
    re.IGNORECASE,
)
PRESSURE_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(mmHg|kPa|bar|psi)\b",
    re.IGNORECASE,
)
CYCLES_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(measurement\s+cycles?|charge\s+cycles?|cycles?|counts?|times?)\b",
    re.IGNORECASE,
)
PERCENTAGE_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(%|percent)(?!\w)",
    re.IGNORECASE,
)
ERROR_CODE_PATTERN = re.compile(
    r"\b(E\d+(?:[–-]E\d+)?)\b",
)
DECIBEL_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(dB|decibels?)\b",
    re.IGNORECASE,
)


class StalenessClassifier:
    """Rule-based engine for evaluating content differences and determining staleness."""

    @staticmethod
    def normalize_text(text: Optional[str]) -> str:
        """Conservative normalization for non-semantic formatting comparison."""
        if not text:
            return ""
        # Normalize non-breaking spaces and hyphenation variants
        cleaned = text.replace("\u00a0", " ").replace("\u2011", "-").replace("‑", "-")
        # Collapse all whitespace sequences (including line breaks) to single space
        return re.sub(r"\s+", " ", cleaned).strip().lower()

    @staticmethod
    def extract_quantities(text: str) -> List[Tuple[str, str, str, str]]:
        """Extract typed quantities with local window context.

        Returns list of tuples: (delta_type, value, unit, context_snippet)
        """
        results: List[Tuple[str, str, str, str]] = []
        if not text:
            return results

        # 1. Timing
        for m in TIMING_PATTERN.finditer(text):
            val, unit = m.group(1), m.group(2)
            start = max(0, m.start() - 25)
            end = min(len(text), m.end() + 25)
            ctx = re.sub(r"\s+", " ", text[start:end]).strip()
            results.append(("TIMING", val, unit.lower(), ctx))

        # 2. Pressure
        for m in PRESSURE_PATTERN.finditer(text):
            val, unit = m.group(1), m.group(2)
            start = max(0, m.start() - 25)
            end = min(len(text), m.end() + 25)
            ctx = re.sub(r"\s+", " ", text[start:end]).strip()
            results.append(("NUMERIC", val, unit, ctx))

        # 3. Cycles / Counts
        for m in CYCLES_PATTERN.finditer(text):
            val, unit = m.group(1), m.group(2)
            start = max(0, m.start() - 25)
            end = min(len(text), m.end() + 25)
            ctx = re.sub(r"\s+", " ", text[start:end]).strip()
            results.append(("NUMERIC", val, unit.lower(), ctx))

        # 4. Percentages
        for m in PERCENTAGE_PATTERN.finditer(text):
            val, unit = m.group(1), m.group(2)
            start = max(0, m.start() - 25)
            end = min(len(text), m.end() + 25)
            ctx = re.sub(r"\s+", " ", text[start:end]).strip()
            results.append(("NUMERIC", val, unit, ctx))

        # 5. Error Code Ranges
        for m in ERROR_CODE_PATTERN.finditer(text):
            val = m.group(1)
            start = max(0, m.start() - 25)
            end = min(len(text), m.end() + 25)
            ctx = re.sub(r"\s+", " ", text[start:end]).strip()
            results.append(("CODE_RANGE", val, "error code", ctx))

        # 6. Decibels / Alarms
        for m in DECIBEL_PATTERN.finditer(text):
            val, unit = m.group(1), m.group(2)
            start = max(0, m.start() - 25)
            end = min(len(text), m.end() + 25)
            ctx = re.sub(r"\s+", " ", text[start:end]).strip()
            results.append(("NUMERIC", val, unit, ctx))

        return results

    def compare_quantities(
        self, old_text: str, new_text: str
    ) -> List[DetectedDelta]:
        """Pair quantities between old and new text based on context similarity and unit matching."""
        old_items = self.extract_quantities(old_text)
        new_items = self.extract_quantities(new_text)

        deltas: List[DetectedDelta] = []
        matched_new_indices: Set[int] = set()

        for delta_type, old_val, old_unit, old_ctx in old_items:
            best_idx = None
            best_sim = 0.0

            for idx, (n_type, n_val, n_unit, n_ctx) in enumerate(new_items):
                if idx in matched_new_indices:
                    continue
                # Same delta type or compatible units
                if delta_type == n_type and (
                    old_unit == n_unit
                    or ("sec" in old_unit and "sec" in n_unit)
                    or ("cycle" in old_unit and "cycle" in n_unit)
                ):
                    sim = difflib.SequenceMatcher(None, old_ctx.lower(), n_ctx.lower()).ratio()
                    if sim > best_sim and sim >= 0.45:
                        best_sim = sim
                        best_idx = idx

            if best_idx is not None:
                matched_new_indices.add(best_idx)
                n_type, n_val, n_unit, n_ctx = new_items[best_idx]
                if old_val != n_val:
                    # Detected changed value
                    unit_label = old_unit
                    if delta_type == "TIMING":
                        expl = f"Timing parameter changed from {old_val} {old_unit} to {n_val} {n_unit}."
                    elif delta_type == "CODE_RANGE":
                        expl = f"Error code range updated from {old_val} to {n_val}."
                    else:
                        expl = f"Numerical value modified from {old_val} {old_unit} to {n_val} {n_unit}."

                    deltas.append(
                        DetectedDelta(
                            delta_type=delta_type,
                            old_value=old_val,
                            new_value=n_val,
                            unit=unit_label,
                            context=f"Old: '{old_ctx}' -> New: '{n_ctx}'",
                            explanation=expl,
                        )
                    )

        return deltas

    def compare_tables(
        self, meta_from_json: Optional[str], meta_to_json: Optional[str]
    ) -> Tuple[List[DetectedDelta], bool]:
        """Detect changes in embedded table rows, cells, and values."""
        deltas: List[DetectedDelta] = []
        table_structure_changed = False

        if not meta_from_json and not meta_to_json:
            return deltas, False

        tables_from = []
        tables_to = []

        if meta_from_json:
            try:
                tables_from = json.loads(meta_from_json).get("tables", [])
            except Exception:
                pass
        if meta_to_json:
            try:
                tables_to = json.loads(meta_to_json).get("tables", [])
            except Exception:
                pass

        if len(tables_from) != len(tables_to):
            table_structure_changed = True
            deltas.append(
                DetectedDelta(
                    delta_type="STRUCTURAL",
                    old_value=f"{len(tables_from)} table(s)",
                    new_value=f"{len(tables_to)} table(s)",
                    unit="tables count",
                    context="Table presence modified",
                    explanation=f"Table count changed from {len(tables_from)} to {len(tables_to)}.",
                )
            )
            return deltas, table_structure_changed

        for t_idx, (tf, tt) in enumerate(zip(tables_from, tables_to)):
            rows_from = tf.get("rows", [])
            rows_to = tt.get("rows", [])

            # Map rows by first column (e.g. error code 'E1', 'E2', 'E3')
            map_from = {r[0].strip(): r for r in rows_from if len(r) > 0}
            map_to = {r[0].strip(): r for r in rows_to if len(r) > 0}

            # Check removed rows
            for k in map_from:
                if k not in map_to:
                    table_structure_changed = True
                    deltas.append(
                        DetectedDelta(
                            delta_type="TABLE_ROW",
                            old_value=f"Row '{k}'",
                            new_value="None",
                            unit="table row",
                            context=f"Table {t_idx + 1} row '{k}' removed",
                            explanation=f"Table row with key '{k}' was removed in target version.",
                        )
                    )

            # Check added rows
            for k in map_to:
                if k not in map_from:
                    table_structure_changed = True
                    deltas.append(
                        DetectedDelta(
                            delta_type="TABLE_ROW",
                            old_value="None",
                            new_value=f"Row '{k}'",
                            unit="table row",
                            context=f"Table {t_idx + 1} added row '{k}': {' | '.join(map_to[k])}",
                            explanation=f"New table entry '{k}' added in target version.",
                        )
                    )

            # Check modified rows
            for k in map_from:
                if k in map_to:
                    rf = " | ".join(map_from[k])
                    rt = " | ".join(map_to[k])
                    if rf != rt:
                        # Inspect for numerical or timing deltas in this row
                        row_deltas = self.compare_quantities(rf, rt)
                        if row_deltas:
                            deltas.extend(row_deltas)
                        else:
                            deltas.append(
                                DetectedDelta(
                                    delta_type="WORDING",
                                    old_value=rf,
                                    new_value=rt,
                                    unit="row content",
                                    context=f"Table {t_idx + 1} row '{k}' modified",
                                    explanation=f"Content of table row '{k}' was revised.",
                                )
                            )

        return deltas, table_structure_changed

    def classify_node(
        self,
        nv_from: Optional[NodeVersion],
        nv_to: Optional[NodeVersion],
        from_label: str = "v1",
        to_label: str = "v2",
        lineage_status: Optional[str] = None,
    ) -> NodeStalenessAssessment:
        """Classify node difference and staleness with complete explainability."""

        # Case 1: Node was removed in target version
        if nv_from and not nv_to:
            return NodeStalenessAssessment(
                node_version_id=nv_from.id,
                logical_node_id=nv_from.logical_node_id,
                section_number=nv_from.section_number,
                heading=nv_from.heading,
                from_version_label=from_label,
                to_version_label=to_label,
                status=NodeStalenessStatus.REMOVED,
                classification=StalenessCategory.REMOVED,
                from_content_hash=nv_from.content_hash,
                to_content_hash=None,
                target_node_version_id=None,
                target_section_number=None,
                target_heading=None,
                deltas=[],
                diff_summary=f"Section {nv_from.section_number} ({nv_from.heading}) was removed in {to_label}.",
                explanation=f"Section exists in {from_label} but has no corresponding entity in {to_label}.",
                human_review_required=True,
                evidence_level="HIGH",
            )

        # Case 2: Node was newly added in target version
        if not nv_from and nv_to:
            return NodeStalenessAssessment(
                node_version_id="",
                logical_node_id=nv_to.logical_node_id,
                section_number=None,
                heading="",
                from_version_label=from_label,
                to_version_label=to_label,
                status=NodeStalenessStatus.STALE,
                classification=StalenessCategory.ADDED,
                from_content_hash=None,
                to_content_hash=nv_to.content_hash,
                target_node_version_id=nv_to.id,
                target_section_number=nv_to.section_number,
                target_heading=nv_to.heading,
                deltas=[],
                diff_summary=f"Section {nv_to.section_number} ({nv_to.heading}) was added in {to_label}.",
                explanation=f"Section is newly introduced in {to_label}.",
                human_review_required=True,
                evidence_level="HIGH",
            )

        if not nv_from and not nv_to:
            raise ValueError("Cannot classify when both node versions are None.")

        # At this point, both nv_from and nv_to exist!
        assert nv_from is not None and nv_to is not None

        # Check for lineage ambiguity
        if lineage_status == "AMBIGUOUS":
            return NodeStalenessAssessment(
                node_version_id=nv_from.id,
                logical_node_id=nv_from.logical_node_id,
                section_number=nv_from.section_number,
                heading=nv_from.heading,
                from_version_label=from_label,
                to_version_label=to_label,
                status=NodeStalenessStatus.AMBIGUOUS,
                classification=StalenessCategory.AMBIGUOUS,
                from_content_hash=nv_from.content_hash,
                to_content_hash=nv_to.content_hash,
                target_node_version_id=nv_to.id,
                target_section_number=nv_to.section_number,
                target_heading=nv_to.heading,
                deltas=[],
                diff_summary="Lineage match between versions is ambiguous or low-confidence.",
                explanation="Multiple candidate matches or competing structural evidence detected. Human review required.",
                human_review_required=True,
                evidence_level="LOW",
            )

        # Case 3: Content hashes match exactly
        if nv_from.content_hash == nv_to.content_hash:
            # Check if section was moved structurally despite unchanged content
            if nv_from.level != nv_to.level or (
                nv_from.parent_node_version_id is None and nv_to.parent_node_version_id is not None
            ):
                return NodeStalenessAssessment(
                    node_version_id=nv_from.id,
                    logical_node_id=nv_from.logical_node_id,
                    section_number=nv_from.section_number,
                    heading=nv_from.heading,
                    from_version_label=from_label,
                    to_version_label=to_label,
                    status=NodeStalenessStatus.MOVED,
                    classification=StalenessCategory.MOVED,
                    from_content_hash=nv_from.content_hash,
                    to_content_hash=nv_to.content_hash,
                    target_node_version_id=nv_to.id,
                    target_section_number=nv_to.section_number,
                    target_heading=nv_to.heading,
                    deltas=[],
                    diff_summary="Section structural location changed while content remained identical.",
                    explanation=f"Relocated in document structure (Level {nv_from.level} -> {nv_to.level}).",
                    human_review_required=True,
                    evidence_level="HIGH",
                )

            return NodeStalenessAssessment(
                node_version_id=nv_from.id,
                logical_node_id=nv_from.logical_node_id,
                section_number=nv_from.section_number,
                heading=nv_from.heading,
                from_version_label=from_label,
                to_version_label=to_label,
                status=NodeStalenessStatus.CURRENT,
                classification=StalenessCategory.NO_CHANGE,
                from_content_hash=nv_from.content_hash,
                to_content_hash=nv_to.content_hash,
                target_node_version_id=nv_to.id,
                target_section_number=nv_to.section_number,
                target_heading=nv_to.heading,
                deltas=[],
                diff_summary=None,
                explanation="Cryptographic hashes match. Source content and structure are completely unchanged.",
                human_review_required=False,
                evidence_level="HIGH",
            )

        # Case 4: Content hashes differ -> investigate formatting vs semantics
        norm_body_from = self.normalize_text(nv_from.body_text)
        norm_body_to = self.normalize_text(nv_to.body_text)
        norm_heading_from = self.normalize_text(nv_from.heading)
        norm_heading_to = self.normalize_text(nv_to.heading)

        table_deltas, table_structure_changed = self.compare_tables(
            nv_from.source_metadata_json, nv_to.source_metadata_json
        )

        # If normalized text and tables are completely identical -> FORMATTING_ONLY
        if (
            norm_body_from == norm_body_to
            and norm_heading_from == norm_heading_to
            and not table_deltas
            and not table_structure_changed
        ):
            return NodeStalenessAssessment(
                node_version_id=nv_from.id,
                logical_node_id=nv_from.logical_node_id,
                section_number=nv_from.section_number,
                heading=nv_from.heading,
                from_version_label=from_label,
                to_version_label=to_label,
                status=NodeStalenessStatus.CURRENT,
                classification=StalenessCategory.FORMATTING_ONLY,
                from_content_hash=nv_from.content_hash,
                to_content_hash=nv_to.content_hash,
                target_node_version_id=nv_to.id,
                target_section_number=nv_to.section_number,
                target_heading=nv_to.heading,
                deltas=[],
                diff_summary="Whitespace, line breaks, or typography layout changed without semantic alteration.",
                explanation="Non-semantic formatting variation detected. Textual content and parameters are equivalent.",
                human_review_required=False,
                evidence_level="HIGH",
            )

        # Compute unified textual diff
        lines_from = nv_from.body_text.splitlines()
        lines_to = nv_to.body_text.splitlines()
        udiff = list(
            difflib.unified_diff(
                lines_from,
                lines_to,
                fromfile=f"{from_label}:{nv_from.section_number}",
                tofile=f"{to_label}:{nv_to.section_number}",
                lineterm="",
            )
        )
        diff_summary = "\n".join(udiff) if udiff else "Body or table metadata modified."

        # Extract quantities and numerical/timing deltas from body text and tables
        body_deltas = self.compare_quantities(nv_from.body_text, nv_to.body_text)
        all_deltas = body_deltas + table_deltas

        # Determine classification by strict precedence
        has_timing = any(d.delta_type == "TIMING" for d in all_deltas)
        has_numeric = any(d.delta_type in ("NUMERIC", "CODE_RANGE") for d in all_deltas)

        if has_timing:
            category = StalenessCategory.TIMING_CHANGE
            expl = "Timing threshold or auto-deflation duration modified. Safety/timing review required."
        elif has_numeric:
            category = StalenessCategory.NUMERIC_CHANGE
            expl = "Operational numerical parameter, battery limit, or pressure increment modified."
        elif table_structure_changed or nv_from.level != nv_to.level:
            category = StalenessCategory.STRUCTURAL_CHANGE
            expl = "Table structure or hierarchy placement modified between versions."
        else:
            category = StalenessCategory.WORDING_CHANGE
            expl = "Descriptive wording updated without detected numerical or timing threshold changes."

        return NodeStalenessAssessment(
            node_version_id=nv_from.id,
            logical_node_id=nv_from.logical_node_id,
            section_number=nv_from.section_number,
            heading=nv_from.heading,
            from_version_label=from_label,
            to_version_label=to_label,
            status=NodeStalenessStatus.STALE,
            classification=category,
            from_content_hash=nv_from.content_hash,
            to_content_hash=nv_to.content_hash,
            target_node_version_id=nv_to.id,
            target_section_number=nv_to.section_number,
            target_heading=nv_to.heading,
            deltas=all_deltas,
            diff_summary=diff_summary,
            explanation=expl,
            human_review_required=True,
            evidence_level="HIGH" if all_deltas else "MEDIUM",
        )

    def evaluate_selection_staleness(
        self,
        db: Session,
        repository: DocumentRepository,
        selection_id: str,
        target_version_label: str = "v2",
    ) -> SelectionStalenessResult:
        """Evaluate an entire pinned selection against a target document revision."""
        selection = repository.get_selection(db, selection_id)
        if not selection:
            raise ValueError(f"Selection with ID '{selection_id}' not found.")

        pinned_version = selection.document_version
        pinned_label = pinned_version.version_label if pinned_version else "v1"

        # Find target document version
        target_version = repository.get_version_by_label(
            db, document_id=selection.document_id, version_label=target_version_label
        )
        if not target_version:
            raise ValueError(
                f"Target document version '{target_version_label}' does not exist for document '{selection.document_id}'."
            )

        assessments: List[NodeStalenessAssessment] = []

        for sn in selection.selection_nodes:
            nv_from = sn.node_version
            if not nv_from:
                continue

            # Look up corresponding node in target version via logical_node_id
            nv_to = repository.get_node_version_by_logical_and_version(
                db, logical_node_id=nv_from.logical_node_id, version_label=target_version_label
            )

            assessment = self.classify_node(
                nv_from=nv_from,
                nv_to=nv_to,
                from_label=pinned_label,
                to_label=target_version_label,
            )
            assessments.append(assessment)

        # Aggregate counts
        counts = {
            "total": len(assessments),
            "current": sum(1 for a in assessments if a.status == NodeStalenessStatus.CURRENT),
            "stale": sum(1 for a in assessments if a.status == NodeStalenessStatus.STALE),
            "removed": sum(1 for a in assessments if a.status == NodeStalenessStatus.REMOVED),
            "moved": sum(1 for a in assessments if a.status == NodeStalenessStatus.MOVED),
            "ambiguous": sum(1 for a in assessments if a.status == NodeStalenessStatus.AMBIGUOUS),
        }

        # Deterministic precedence: AMBIGUOUS > IMPACTED > REVIEW_REQUIRED > CURRENT
        has_ambiguous = counts["ambiguous"] > 0
        has_removed = counts["removed"] > 0
        has_critical_changes = any(
            a.classification in (StalenessCategory.TIMING_CHANGE, StalenessCategory.NUMERIC_CHANGE)
            for a in assessments
        )
        has_any_stale = counts["stale"] > 0 or counts["moved"] > 0

        if has_ambiguous:
            agg_status = AggregateSelectionStatus.AMBIGUOUS
        elif has_removed or has_critical_changes:
            agg_status = AggregateSelectionStatus.IMPACTED
        elif has_any_stale:
            agg_status = AggregateSelectionStatus.REVIEW_REQUIRED
        else:
            agg_status = AggregateSelectionStatus.CURRENT

        human_review = agg_status != AggregateSelectionStatus.CURRENT

        return SelectionStalenessResult(
            selection_id=selection.id,
            selection_name=selection.name,
            pinned_version_label=pinned_label,
            target_version_label=target_version_label,
            aggregate_status=agg_status,
            summary_counts=counts,
            human_review_required=human_review,
            disclaimer=SAFETY_DISCLAIMER,
            node_assessments=assessments,
        )
