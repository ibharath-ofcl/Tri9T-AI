"""Multi-signal cross-version logical node matching and lineage engine.

Establishes conceptual identity across document versions (v1 -> v2) using:
1. Exact section numbering and structural ancestor paths.
2. Normalized heading text similarity.
3. Content hash equivalence.
4. Structural move and relocation detection.
5. Explicit ambiguity detection (avoids forcing uncertain matches).

Outputs classifications: UNCHANGED, MODIFIED, ADDED, REMOVED, MOVED, AMBIGUOUS.
"""

from __future__ import annotations
import difflib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

from app.schemas.document import DocumentNode


class ChangeClassification(str, Enum):
    """Categorization of a section's lifecycle across versions."""
    UNCHANGED = "UNCHANGED"
    MODIFIED = "MODIFIED"
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    MOVED = "MOVED"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass
class MatchResult:
    """Result of matching a node in the new version against the previous version."""
    new_node_order: int
    new_section_number: Optional[str]
    new_heading: str
    classification: ChangeClassification
    logical_node_id: Optional[str] = None
    prev_node_version_id: Optional[str] = None
    prev_section_number: Optional[str] = None
    confidence_score: float = 1.0
    notes: str = ""
    is_new_logical_node: bool = False


@dataclass
class PriorNodeSnapshot:
    """Lightweight representation of a node from the prior document version."""
    node_version_id: str
    logical_node_id: str
    section_number: Optional[str]
    heading: str
    normalized_heading: str
    parent_logical_id: Optional[str]
    parent_section_number: Optional[str]
    structural_path: str
    content_hash: str
    body_text: str
    source_order: int


class VersionMatcher:
    """Multi-signal matcher establishing logical node lineage across document revisions."""

    def __init__(self, similarity_threshold: float = 0.80, ambiguity_margin: float = 0.10):
        self.similarity_threshold = similarity_threshold
        self.ambiguity_margin = ambiguity_margin

    @staticmethod
    def normalize_heading(heading: str) -> str:
        """Normalize heading text for comparison (lowercase, strip numbering and punctuation)."""
        if not heading:
            return ""
        # Strip leading section numbers like '1.', '2.1', '2.1.1.1'
        cleaned = re.sub(r"^\d+(\.\d+)*\.?\s*", "", heading)
        # Lowercase and normalize whitespace
        cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
        # Remove trailing/leading punctuation
        cleaned = re.sub(r"^[^\w]+|[^\w]+$", "", cleaned)
        return cleaned

    def compute_similarity(self, s1: str, s2: str) -> float:
        """Compute string similarity ratio between 0.0 and 1.0."""
        if not s1 and not s2:
            return 1.0
        if not s1 or not s2:
            return 0.0
        return difflib.SequenceMatcher(None, s1, s2).ratio()

    def match_versions(
        self,
        prev_nodes: List[PriorNodeSnapshot],
        new_nodes: List[DocumentNode],
        parent_map_new: Dict[str, Optional[DocumentNode]],
    ) -> Tuple[Dict[str, MatchResult], List[PriorNodeSnapshot]]:
        """Match all nodes in new_nodes against prev_nodes.

        Returns:
            - Dict mapping new_node.node_id -> MatchResult
            - List of unmatched prev_nodes classified as REMOVED
        """
        results: Dict[str, MatchResult] = {}
        matched_prev_ids: Set[str] = set()

        # Build lookup indices for prior nodes
        by_sec_num: Dict[str, List[PriorNodeSnapshot]] = {}
        by_norm_heading: Dict[str, List[PriorNodeSnapshot]] = {}

        for p in prev_nodes:
            if p.section_number:
                by_sec_num.setdefault(p.section_number, []).append(p)
            by_norm_heading.setdefault(p.normalized_heading, []).append(p)

        # Build paths for new nodes
        new_paths: Dict[str, str] = {}
        for n in new_nodes:
            path_parts = []
            curr: Optional[DocumentNode] = n
            while curr:
                path_parts.append(curr.section_number or curr.heading or "")
                curr = parent_map_new.get(curr.node_id)
            new_paths[n.node_id] = " > ".join(reversed(path_parts))

        # Pass 1: High-confidence Section Number + Parent Path Match
        for n in new_nodes:
            sec = n.section_number
            norm_heading = self.normalize_heading(n.heading or "")
            parent_new = parent_map_new.get(n.node_id)
            parent_sec = parent_new.section_number if parent_new else None

            if sec and sec in by_sec_num:
                candidates = by_sec_num[sec]
                # Filter candidates by parent context if multiple
                matched_candidate = None
                if len(candidates) == 1:
                    matched_candidate = candidates[0]
                else:
                    # Duplicate section number or duplicate heading context
                    for c in candidates:
                        if c.parent_section_number == parent_sec:
                            matched_candidate = c
                            break

                if matched_candidate and matched_candidate.node_version_id not in matched_prev_ids:
                    # Verify heading isn't completely contradictory
                    h_sim = self.compute_similarity(norm_heading, matched_candidate.normalized_heading)
                    if h_sim >= 0.50:
                        matched_prev_ids.add(matched_candidate.node_version_id)
                        # Determine UNCHANGED vs MODIFIED
                        is_hash_identical = n.content_hash == matched_candidate.content_hash
                        classification = (
                            ChangeClassification.UNCHANGED
                            if is_hash_identical
                            else ChangeClassification.MODIFIED
                        )
                        results[n.node_id] = MatchResult(
                            new_node_order=n.document_order,
                            new_section_number=n.section_number,
                            new_heading=n.heading or "",
                            classification=classification,
                            logical_node_id=matched_candidate.logical_node_id,
                            prev_node_version_id=matched_candidate.node_version_id,
                            prev_section_number=matched_candidate.section_number,
                            confidence_score=round(0.85 + (0.15 * h_sim), 2),
                            notes=(
                                "Exact section number and structural path match."
                                if is_hash_identical
                                else "Section number matched; content hash changed."
                            ),
                            is_new_logical_node=False,
                        )
                        continue

        # Pass 2: Heading & Structural Path Match for unassigned nodes
        for n in new_nodes:
            if n.node_id in results:
                continue

            norm_heading = self.normalize_heading(n.heading or "")
            parent_new = parent_map_new.get(n.node_id)
            parent_sec = parent_new.section_number if parent_new else None

            # Look for candidate matches among available previous nodes
            scored_candidates: List[Tuple[PriorNodeSnapshot, float]] = []
            for p in prev_nodes:
                if p.node_version_id in matched_prev_ids:
                    continue

                h_sim = self.compute_similarity(norm_heading, p.normalized_heading)
                if h_sim >= self.similarity_threshold:
                    # Score bonus if parent matches
                    parent_match = p.parent_section_number == parent_sec
                    score = h_sim + (0.2 if parent_match else -0.1)
                    scored_candidates.append((p, score))

            scored_candidates.sort(key=lambda x: x[1], reverse=True)

            if scored_candidates:
                top_candidate, top_score = scored_candidates[0]

                # Check for ambiguity (multiple equally plausible candidates)
                if len(scored_candidates) > 1:
                    second_score = scored_candidates[1][1]
                    if abs(top_score - second_score) < self.ambiguity_margin:
                        # Ambiguous match
                        results[n.node_id] = MatchResult(
                            new_node_order=n.document_order,
                            new_section_number=n.section_number,
                            new_heading=n.heading or "",
                            classification=ChangeClassification.AMBIGUOUS,
                            confidence_score=round(top_score, 2),
                            notes=(
                                f"Ambiguous match between prior nodes {top_candidate.section_number} "
                                f"and {scored_candidates[1][0].section_number} (score delta < {self.ambiguity_margin})."
                            ),
                            is_new_logical_node=True,
                        )
                        continue

                # Defensible match found
                matched_prev_ids.add(top_candidate.node_version_id)
                parent_match = top_candidate.parent_section_number == parent_sec
                if parent_match:
                    is_hash_identical = n.content_hash == top_candidate.content_hash
                    classification = (
                        ChangeClassification.UNCHANGED
                        if is_hash_identical
                        else ChangeClassification.MODIFIED
                    )
                else:
                    classification = ChangeClassification.MOVED

                results[n.node_id] = MatchResult(
                    new_node_order=n.document_order,
                    new_section_number=n.section_number,
                    new_heading=n.heading or "",
                    classification=classification,
                    logical_node_id=top_candidate.logical_node_id,
                    prev_node_version_id=top_candidate.node_version_id,
                    prev_section_number=top_candidate.section_number,
                    confidence_score=round(min(1.0, max(0.5, top_score)), 2),
                    notes="Matched via normalized heading similarity and parent evidence.",
                    is_new_logical_node=False,
                )
                continue

            # Pass 3: No defensible match -> ADDED (brand new conceptual section)
            results[n.node_id] = MatchResult(
                new_node_order=n.document_order,
                new_section_number=n.section_number,
                new_heading=n.heading or "",
                classification=ChangeClassification.ADDED,
                confidence_score=1.0,
                notes="No corresponding section found in previous version; assigned new logical identity.",
                is_new_logical_node=True,
            )

        # Pass 4: Any previous nodes never matched are REMOVED
        removed_nodes = [p for p in prev_nodes if p.node_version_id not in matched_prev_ids]

        return results, removed_nodes
