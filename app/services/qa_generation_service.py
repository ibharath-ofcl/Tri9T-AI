"""Orchestration service for grounded medical-device QA test-case generation, validation retries, and staleness auditing."""

from __future__ import annotations
import hashlib
import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.config import Settings, settings as default_settings
from app.db.models import NodeVersion, Selection
from app.prompts.qa_generation import (
    PROMPT_TEMPLATE_VERSION,
    SYSTEM_INSTRUCTION,
    build_retry_prompt,
    build_user_prompt,
)
from app.repositories.document_repository import DocumentRepository
from app.repositories.test_suite_store import TestSuiteStore, get_test_suite_store
from app.schemas.api import DetectedValueDeltaSchema
from app.schemas.qa_test_case import (
    DocumentTestSuiteImpactResponse,
    GeneratedTestSuitePayload,
    TestCaseProvenance,
    TestCaseSchema,
    TestCaseStalenessReport,
    TestSuiteStalenessResponse,
)
from app.services.grounding_auditor import GroundingAuditor
from app.services.llm_provider import BaseLLMProvider, get_llm_provider
from app.services.staleness_classifier import (
    SAFETY_DISCLAIMER,
    NodeStalenessStatus,
    StalenessCategory,
    StalenessClassifier,
)

logger = logging.getLogger(__name__)


class IdempotencyConflictError(Exception):
    """Raised when an idempotency key is reused with differing request parameters."""
    pass


class GenerationValidationError(Exception):
    """Raised when LLM output repeatedly fails strict schema validation."""
    pass


class QAGenerationService:
    """Service orchestrating grounded QA generation, validation retries, persistence, and staleness."""

    def __init__(
        self,
        repository: Optional[DocumentRepository] = None,
        store: Optional[TestSuiteStore] = None,
        provider: Optional[BaseLLMProvider] = None,
        classifier: Optional[StalenessClassifier] = None,
        grounding_auditor: Optional[GroundingAuditor] = None,
        max_attempts: int = 3,
    ):
        self.repository = repository or DocumentRepository()
        self.store = store or get_test_suite_store()
        self._provider = provider
        self.classifier = classifier or StalenessClassifier()
        self.grounding_auditor = grounding_auditor or GroundingAuditor()
        self.max_attempts = max_attempts

    @property
    def provider(self) -> BaseLLMProvider:
        if self._provider is None:
            self._provider = get_llm_provider()
        return self._provider

    @provider.setter
    def provider(self, val: BaseLLMProvider) -> None:
        self._provider = val

    @staticmethod
    def compute_request_fingerprint(
        source_hashes: Dict[str, str],
        requested_count: int,
        prompt_version: str,
        provider_name: str,
        model_name: str,
        focus_topic: Optional[str] = None,
    ) -> str:
        """Generate deterministic cryptographic fingerprint for duplicate detection."""
        sorted_hashes = sorted(f"{k}:{v}" for k, v in source_hashes.items())
        combined = f"{';'.join(sorted_hashes)}|{requested_count}|{prompt_version}|{provider_name}|{model_name}|{focus_topic or ''}"
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()

    def _resolve_source_nodes(
        self,
        db: Session,
        selection_id: Optional[str] = None,
        node_version_id: Optional[str] = None,
    ) -> Tuple[List[NodeVersion], str, str, str, Optional[str]]:
        """Resolve exact immutable source node snapshots and document metadata.

        Returns: (source_nodes, document_id, document_version_id, document_version_label, selection_id)
        """
        if selection_id:
            sel = self.repository.get_selection(db, selection_id)
            if not sel:
                raise ValueError(f"Selection with ID '{selection_id}' not found.")
            source_nodes = [sn.node_version for sn in sel.selection_nodes if sn.node_version]
            if not source_nodes:
                raise ValueError(f"Selection '{selection_id}' contains no node versions.")
            doc_id = sel.document_id
            ver_id = sel.document_version_id
            ver_label = sel.document_version.version_label if sel.document_version else "v1"
            return source_nodes, doc_id, ver_id, ver_label, sel.id

        elif node_version_id:
            nv = self.repository.get_node_version(db, node_version_id)
            if not nv:
                raise ValueError(f"NodeVersion with ID '{node_version_id}' not found.")
            doc_id = nv.document_version.document_id
            ver_id = nv.document_version_id
            ver_label = nv.document_version.version_label if nv.document_version else "v1"
            return [nv], doc_id, ver_id, ver_label, None

        else:
            raise ValueError("Must provide either 'selection_id' or 'node_version_id'.")

    def _format_node_dicts(self, nodes: List[NodeVersion]) -> List[Dict[str, Any]]:
        """Extract structured representation including parsed tables."""
        formatted = []
        for n in nodes:
            tables = []
            if n.source_metadata_json:
                try:
                    meta = json.loads(n.source_metadata_json)
                    tables = meta.get("tables", [])
                except Exception:
                    pass

            formatted.append({
                "node_version_id": n.id,
                "logical_node_id": n.logical_node_id,
                "section_number": n.section_number,
                "heading": n.heading,
                "page_start": n.page_start,
                "page_end": n.page_end,
                "content_hash": n.content_hash,
                "body_text": n.body_text,
                "tables": tables,
            })
        return formatted

    def _bind_provenance(
        self,
        test_case: TestCaseSchema,
        source_nodes: List[NodeVersion],
        selection_id: Optional[str],
        doc_version_id: str,
        doc_version_label: str,
    ) -> TestCaseSchema:
        """Bind exact cryptographic provenance snapshot to test case."""
        # Determine best matching node based on section number or heading citation in StandardRef/Title
        best_node = source_nodes[0]
        if len(source_nodes) > 1:
            ref_text = f"{test_case.StandardRef} {test_case.Title} {test_case.ExpectedResult}".lower()
            for n in source_nodes:
                sec_match = n.section_number and n.section_number.lower() in ref_text
                head_match = n.heading and n.heading.lower() in ref_text
                if sec_match or head_match:
                    best_node = n
                    break

        test_case.Provenance = TestCaseProvenance(
            selection_id=selection_id,
            source_node_version_id=best_node.id,
            source_content_hash=best_node.content_hash,
            source_logical_node_id=best_node.logical_node_id,
            source_document_version_id=doc_version_id,
            source_document_version_label=doc_version_label,
            section_number=best_node.section_number,
            heading=best_node.heading,
            page_start=best_node.page_start,
            page_end=best_node.page_end,
        )
        return test_case

    def generate_test_suite(
        self,
        db: Session,
        selection_id: Optional[str] = None,
        node_version_id: Optional[str] = None,
        requested_count: int = 4,
        idempotency_key: Optional[str] = None,
        focus_topic: Optional[str] = None,
    ) -> GeneratedTestSuitePayload:
        """Generate, strictly validate, and persist structured QA test cases from source snapshots."""
        if not (3 <= requested_count <= 5):
            raise ValueError(f"Requested test case count ({requested_count}) must be between 3 and 5.")

        # 1. Resolve source nodes and document metadata
        source_nodes, doc_id, ver_id, ver_label, sel_id = self._resolve_source_nodes(
            db, selection_id=selection_id, node_version_id=node_version_id
        )

        source_hashes = {n.id: n.content_hash for n in source_nodes}
        source_node_ids = [n.id for n in source_nodes]

        # 2. Check duplicate submission & idempotency
        fingerprint = self.compute_request_fingerprint(
            source_hashes=source_hashes,
            requested_count=requested_count,
            prompt_version=PROMPT_TEMPLATE_VERSION,
            provider_name=self.provider.provider_name,
            model_name=self.provider.model_name,
            focus_topic=focus_topic,
        )

        if idempotency_key:
            existing = self.store.get_by_idempotency_key(idempotency_key)
            if existing:
                if existing.request_fingerprint == fingerprint:
                    logger.info("Idempotent replay for key '%s'", idempotency_key)
                    return existing
                else:
                    raise IdempotencyConflictError(
                        f"Idempotency key '{idempotency_key}' was previously used with different generation parameters."
                    )

        # 3. Construct user prompt
        formatted_node_data = self._format_node_dicts(source_nodes)
        user_prompt = build_user_prompt(
            document_title="CardioTrack CT-200 Technical Manual",
            version_label=ver_label,
            source_nodes=formatted_node_data,
            requested_count=requested_count,
            focus_topic=focus_topic,
        )

        messages = [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": user_prompt},
        ]

        # 4. Bounded validation retry loop (Max 3 total model attempts)
        validated_cases: List[TestCaseSchema] = []
        last_error_msg = ""
        raw_output = ""

        for attempt in range(1, self.max_attempts + 1):
            try:
                raw_output = self.provider.generate(messages)
                parsed = json.loads(raw_output)

                if not isinstance(parsed, dict) or "test_cases" not in parsed:
                    raise ValueError("JSON response must be an object containing a 'test_cases' array.")

                raw_cases = parsed.get("test_cases", [])
                if not isinstance(raw_cases, list):
                    raise ValueError("'test_cases' must be an array of test case objects.")

                if len(raw_cases) != requested_count:
                    raise ValueError(f"Generated {len(raw_cases)} test cases, expected exactly {requested_count}.")

                # Validate individual test cases against Pydantic schema
                current_cases = []
                seen_ids = set()
                seen_titles = set()

                for c_idx, raw_case in enumerate(raw_cases):
                    tc = TestCaseSchema.model_validate(raw_case)

                    # Deduplication checks
                    if tc.TestCaseId in seen_ids:
                        raise ValueError(f"Duplicate TestCaseId '{tc.TestCaseId}' found in generated output.")
                    seen_ids.add(tc.TestCaseId)

                    norm_t = " ".join(tc.Title.lower().split())
                    if norm_t in seen_titles:
                        raise ValueError(f"Duplicate test title '{tc.Title}' found in output.")
                    seen_titles.add(norm_t)

                    # Bind exact cryptographic provenance
                    tc_bound = self._bind_provenance(
                        test_case=tc,
                        source_nodes=source_nodes,
                        selection_id=sel_id,
                        doc_version_id=ver_id,
                        doc_version_label=ver_label,
                    )
                    current_cases.append(tc_bound)

                # Validation succeeded!
                validated_cases = current_cases
                break

            except Exception as exc:
                last_error_msg = str(exc)
                logger.warning(
                    "QA generation attempt %d/%d failed validation: %s",
                    attempt,
                    self.max_attempts,
                    last_error_msg,
                )

                if attempt < self.max_attempts:
                    retry_msg = build_retry_prompt(last_error_msg, raw_output)
                    messages.append({"role": "assistant", "content": raw_output})
                    messages.append({"role": "user", "content": retry_msg})

        if not validated_cases:
            raise GenerationValidationError(
                f"QA test case generation failed after {self.max_attempts} attempts. Last validation error: {last_error_msg}"
            )

        # 5. Build and persist test suite document
        generation_id = str(uuid.uuid4())
        suite_payload = GeneratedTestSuitePayload(
            generation_id=generation_id,
            selection_id=sel_id,
            document_id=doc_id,
            document_version_id=ver_id,
            document_version_label=ver_label,
            requested_count=requested_count,
            generated_count=len(validated_cases),
            provider_name=self.provider.provider_name,
            model_name=self.provider.model_name,
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            validation_status="VALIDATED",
            human_review_required=any(tc.HumanReviewRequired for tc in validated_cases),
            warnings=[],
            test_cases=validated_cases,
            source_node_version_ids=source_node_ids,
            source_content_hashes=source_hashes,
        )

        # 5. Execute deterministic source-grounding audit
        self.grounding_auditor.audit_suite(suite_payload, source_nodes)

        # 6. Atomic persistence in document store with fail-safe error handling
        try:
            self.store.save_test_suite(suite_payload)
        except Exception as store_err:
            logger.error("Failed to persist generated test suite %s in document store: %s", generation_id, store_err)
            raise RuntimeError(f"Document store persistence failed: {str(store_err)}") from store_err

        return suite_payload

    def evaluate_test_suite_staleness(
        self,
        db: Session,
        generation_id: str,
        target_version_label: str = "v2",
    ) -> TestSuiteStalenessResponse:
        """Evaluate a persisted test suite against target document revision using Stage 4 lineage and classifier."""
        suite = self.store.get_test_suite(generation_id)
        if not suite:
            raise ValueError(f"Generated test suite with ID '{generation_id}' not found.")

        # Verify target document version exists
        target_ver = self.repository.get_version_by_label(
            db, document_id=suite.document_id, version_label=target_version_label
        )
        if not target_ver:
            raise ValueError(
                f"Target version '{target_version_label}' does not exist for document '{suite.document_id}'."
            )

        case_assessments: List[TestCaseStalenessReport] = []

        for tc in suite.test_cases:
            prov = tc.Provenance
            if not prov:
                case_assessments.append(
                    TestCaseStalenessReport(
                        test_case_id=tc.TestCaseId,
                        title=tc.Title,
                        source_heading="Unknown",
                        source_node_version_id="",
                        original_content_hash="",
                        status="UNAVAILABLE",
                        classification="UNCLASSIFIED",
                        explanation="Test case has no provenance metadata attached.",
                        human_review_required=True,
                    )
                )
                continue

            source_nv = self.repository.get_node_version(db, prov.source_node_version_id)
            target_nv = self.repository.get_node_version_by_logical_and_version(
                db, logical_node_id=prov.source_logical_node_id, version_label=target_version_label
            )

            if not source_nv:
                case_assessments.append(
                    TestCaseStalenessReport(
                        test_case_id=tc.TestCaseId,
                        title=tc.Title,
                        source_section_number=prov.section_number,
                        source_heading=prov.heading,
                        source_node_version_id=prov.source_node_version_id,
                        original_content_hash=prov.source_content_hash,
                        status="UNAVAILABLE",
                        classification="UNCLASSIFIED",
                        explanation="Original source NodeVersion record missing in relational store.",
                        human_review_required=True,
                    )
                )
                continue

            # Classify using existing Stage 4 classifier
            assessment = self.classifier.classify_node(
                nv_from=source_nv,
                nv_to=target_nv,
                from_label=prov.source_document_version_label,
                to_label=target_version_label,
            )

            # Map to test case staleness status
            if assessment.status == NodeStalenessStatus.CURRENT:
                tc_status = "CURRENT"
                expl = "Source requirements and parameters are identical. Test case remains fully valid."
                review_req = False
            elif assessment.status == NodeStalenessStatus.REMOVED:
                tc_status = "SOURCE_REMOVED"
                expl = "Supporting section was removed in target version. Test case is obsolete."
                review_req = True
            elif assessment.status == NodeStalenessStatus.MOVED:
                tc_status = "SOURCE_MOVED"
                expl = "Supporting section was relocated in document structure. Verify section references."
                review_req = True
            elif assessment.status == NodeStalenessStatus.AMBIGUOUS:
                tc_status = "AMBIGUOUS"
                expl = "Source section lineage is ambiguous. Human engineering review required."
                review_req = True
            else:
                tc_status = "STALE"
                deltas_summary = "; ".join(d.explanation for d in assessment.deltas) if assessment.deltas else "Text modified"
                expl = f"Source requirements changed: {deltas_summary}. Test case prerequisites/expectations must be re-evaluated."
                review_req = True

            delta_schemas = [
                DetectedValueDeltaSchema(
                    delta_type=d.delta_type,
                    old_value=d.old_value,
                    new_value=d.new_value,
                    unit=d.unit,
                    context=d.context,
                    explanation=d.explanation,
                )
                for d in assessment.deltas
            ]

            case_assessments.append(
                TestCaseStalenessReport(
                    test_case_id=tc.TestCaseId,
                    title=tc.Title,
                    source_section_number=prov.section_number,
                    source_heading=prov.heading,
                    source_node_version_id=prov.source_node_version_id,
                    original_content_hash=prov.source_content_hash,
                    target_content_hash=target_nv.content_hash if target_nv else None,
                    status=tc_status,
                    classification=assessment.classification.value,
                    deltas=delta_schemas,
                    explanation=expl,
                    human_review_required=review_req,
                )
            )

        # Aggregate suite health
        counts = {
            "total": len(case_assessments),
            "current": sum(1 for c in case_assessments if c.status == "CURRENT"),
            "stale": sum(1 for c in case_assessments if c.status == "STALE"),
            "source_removed": sum(1 for c in case_assessments if c.status == "SOURCE_REMOVED"),
            "source_moved": sum(1 for c in case_assessments if c.status == "SOURCE_MOVED"),
            "ambiguous": sum(1 for c in case_assessments if c.status == "AMBIGUOUS"),
        }

        has_impact = counts["stale"] > 0 or counts["source_removed"] > 0
        has_ambiguous = counts["ambiguous"] > 0
        has_review = counts["source_moved"] > 0

        if has_ambiguous:
            agg_status = "AMBIGUOUS"
        elif has_impact:
            agg_status = "IMPACTED"
        elif has_review:
            agg_status = "REVIEW_REQUIRED"
        else:
            agg_status = "CURRENT"

        return TestSuiteStalenessResponse(
            generation_id=suite.generation_id,
            selection_id=suite.selection_id,
            pinned_version_label=suite.document_version_label,
            target_version_label=target_version_label,
            aggregate_status=agg_status,
            summary=counts,
            human_review_required=(agg_status != "CURRENT"),
            disclaimer=SAFETY_DISCLAIMER,
            test_case_assessments=case_assessments,
        )

    def analyze_document_test_suite_impact(
        self,
        db: Session,
        document_id: str,
        from_version_label: str = "v1",
        to_version_label: str = "v2",
    ) -> DocumentTestSuiteImpactResponse:
        """Evaluate revision impact across all persisted test suites generated for from_version."""
        all_suites = self.store.list_test_suites(document_id=document_id)
        from_suites = [s for s in all_suites if s.document_version_label == from_version_label]

        affected: List[TestSuiteStalenessResponse] = []
        unaffected: List[TestSuiteStalenessResponse] = []

        for s in from_suites:
            eval_resp = self.evaluate_test_suite_staleness(
                db=db,
                generation_id=s.generation_id,
                target_version_label=to_version_label,
            )
            if eval_resp.aggregate_status == "CURRENT":
                unaffected.append(eval_resp)
            else:
                affected.append(eval_resp)

        return DocumentTestSuiteImpactResponse(
            document_id=document_id,
            from_version=from_version_label,
            to_version=to_version_label,
            total_test_suites_evaluated=len(from_suites),
            impacted_test_suites_count=len(affected),
            current_test_suites_count=len(unaffected),
            human_review_required=len(affected) > 0,
            disclaimer=SAFETY_DISCLAIMER,
            affected_suites=affected,
            unaffected_suites=unaffected,
        )
