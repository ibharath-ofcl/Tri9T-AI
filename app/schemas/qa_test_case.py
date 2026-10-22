"""Strict Pydantic schemas for LLM-generated medical-device QA test cases and provenance.

Enforces:
- Required assignment field names: TestCaseId, Title, Prerequisites, Steps,
  ExpectedResult, PassFailCriteria, StandardRef.
- Non-empty validation on strings and collections.
- Cryptographic source provenance tracking (node_version_id, content_hash).
- Duplicate detection across generated suites.
- Serialization and API representation matching assignment contracts.
"""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.api import DetectedValueDeltaSchema


class TestCaseType(str, Enum):
    """Category of verification intent."""
    NOMINAL = "nominal"
    BOUNDARY = "boundary"
    NEGATIVE = "negative"
    FAULT_INJECTION = "fault_injection"
    TIMING = "timing"


class ClaimCategory(str, Enum):
    """Grounding audit classification for generated test case claims."""
    SOURCE_SUPPORTED = "SOURCE_SUPPORTED"
    DERIVED_WITH_EXPLANATION = "DERIVED_WITH_EXPLANATION"
    PROPOSED_SETUP = "PROPOSED_SETUP"
    UNSUPPORTED = "UNSUPPORTED"
    AMBIGUOUS = "AMBIGUOUS"


class AuditedClaim(BaseModel):
    """An individual assertion or requirement extracted from a generated test case."""
    claim_text: str = Field(..., description="The specific assertion, threshold, or setup step")
    field_name: str = Field(..., description="Field containing the claim (e.g. ExpectedResult, PassFailCriteria)")
    category: ClaimCategory = Field(..., description="Source support classification")
    evidence: Optional[str] = Field(None, description="Supporting excerpt from the manual or derivation rationale")
    explanation: str = Field(..., description="Audit determination details")
    requires_human_review: bool = Field(default=False, description="Whether claim requires engineering verification")


class TestCaseGroundingAudit(BaseModel):
    """Deterministic source-grounding audit result for an individual test case."""
    test_case_id: str
    overall_grounding_status: str = Field(..., description="GROUNDED, PROPOSED_SETUP_PRESENT, UNSUPPORTED_CLAIMS, or REQUIRES_REVIEW")
    claims_count: int
    source_supported_count: int
    derived_count: int
    proposed_setup_count: int
    unsupported_count: int
    ambiguous_count: int
    human_review_required: bool
    audited_claims: List[AuditedClaim] = Field(default_factory=list)
    findings: List[str] = Field(default_factory=list)


class SuiteGroundingSummary(BaseModel):
    """Aggregated source-grounding audit summary across an entire generated suite."""
    total_claims_audited: int
    source_supported_claims: int
    derived_claims: int
    proposed_setup_claims: int
    unsupported_claims: int
    ambiguous_claims: int
    human_review_required: bool
    case_grounding_reports: List[TestCaseGroundingAudit] = Field(default_factory=list)


class TestCaseProvenance(BaseModel):
    """Cryptographic provenance linking a test case to an immutable source snapshot."""
    selection_id: Optional[str] = Field(None, description="Parent selection UUID if generated from selection")
    source_node_version_id: str = Field(..., description="Exact immutable NodeVersion UUID")
    source_content_hash: str = Field(..., description="SHA-256 hash of source content at generation time")
    source_logical_node_id: str = Field(..., description="Cross-version logical node identity")
    source_document_version_id: str = Field(..., description="Document version UUID (e.g. v1)")
    source_document_version_label: str = Field(..., description="Version label ('v1')")
    section_number: Optional[str] = Field(None, description="Section numbering (e.g. '2.1.1.1')")
    heading: str = Field(..., description="Section heading")
    page_start: int = Field(..., description="Start page in manual")
    page_end: int = Field(..., description="End page in manual")


class TestCaseSchema(BaseModel):
    """Individual structured QA test case adhering to assignment contract."""
    TestCaseId: str = Field(..., description="Unique stable test case identifier")
    Title: str = Field(..., min_length=5, description="Concise description of verification intent")
    Prerequisites: List[str] = Field(..., min_length=1, description="Required device states and environmental setup")
    Steps: List[str] = Field(..., min_length=1, description="Ordered actionable execution steps")
    ExpectedResult: str = Field(..., min_length=5, description="Observable expected device behavior")
    PassFailCriteria: str = Field(..., min_length=5, description="Definitive criteria for verdict determination")
    StandardRef: str = Field(..., min_length=1, description="Source manual reference or documented standard")

    # Additional traceability metadata
    TestType: str = Field(default="nominal", description="Test category: nominal, boundary, negative, fault_injection, timing")
    CoverageTags: List[str] = Field(default_factory=list, description="Descriptive classification tags")
    HumanReviewRequired: bool = Field(default=False, description="Flag indicating human QA review is required")
    ValidationWarnings: List[str] = Field(default_factory=list, description="Non-fatal warnings or grounded ambiguities")
    Provenance: Optional[TestCaseProvenance] = Field(None, description="Exact source provenance snapshot binding")
    GroundingAudit: Optional[TestCaseGroundingAudit] = Field(None, description="Deterministic source grounding verification")

    @field_validator("TestCaseId", "Title", "ExpectedResult", "PassFailCriteria", "StandardRef")
    @classmethod
    def check_non_empty_strings(cls, v: str, info) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError(f"Field '{info.field_name}' must not be empty or whitespace.")
        return trimmed

    @field_validator("Prerequisites", "Steps")
    @classmethod
    def check_non_empty_items(cls, items: List[str], info) -> List[str]:
        if not items:
            raise ValueError(f"Field '{info.field_name}' must contain at least one item.")
        cleaned = [item.strip() for item in items if item.strip()]
        if not cleaned:
            raise ValueError(f"Field '{info.field_name}' cannot consist solely of empty strings.")
        return cleaned


class GeneratedTestSuitePayload(BaseModel):
    """Complete document-store record for an LLM generation run."""
    model_config = {"protected_namespaces": ()}

    generation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    selection_id: Optional[str] = None
    document_id: str
    document_version_id: str
    document_version_label: str
    requested_count: int = Field(..., ge=3, le=5)
    generated_count: int
    provider_name: str
    model_name: str
    prompt_template_version: str = "v1.0"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    idempotency_key: Optional[str] = None
    request_fingerprint: str
    validation_status: str = "VALIDATED"  # "VALIDATED" | "FAILED"
    human_review_required: bool = False
    warnings: List[str] = Field(default_factory=list)
    test_cases: List[TestCaseSchema]
    source_node_version_ids: List[str] = Field(default_factory=list)
    source_content_hashes: Dict[str, str] = Field(default_factory=dict)
    grounding_summary: Optional[SuiteGroundingSummary] = Field(None, description="Deterministic source grounding audit across all test cases")

    @model_validator(mode="after")
    def validate_test_cases_integrity(self) -> GeneratedTestSuitePayload:
        """Validate test case counts and ensure no duplicate IDs or titles exist."""
        cases = self.test_cases
        if len(cases) != self.requested_count:
            # Allow minor tolerance if within 3..5
            if not (3 <= len(cases) <= 5):
                raise ValueError(
                    f"Generated test case count ({len(cases)}) does not match requested range (3 to 5)."
                )

        # Check duplicate TestCaseIds
        seen_ids = set()
        for c in cases:
            if c.TestCaseId in seen_ids:
                raise ValueError(f"Duplicate TestCaseId '{c.TestCaseId}' detected in generated test suite.")
            seen_ids.add(c.TestCaseId)

        # Check duplicate normalized titles
        seen_titles = set()
        for c in cases:
            norm_title = " ".join(c.Title.lower().split())
            if norm_title in seen_titles:
                raise ValueError(f"Substantially duplicate test case Title '{c.Title}' detected in suite.")
            seen_titles.add(norm_title)

        return self


# ---------------------------------------------------------------------------
# API Request and Response Models
# ---------------------------------------------------------------------------

class GenerateTestSuiteRequest(BaseModel):
    """API request payload for generating QA test cases."""
    count: int = Field(default=4, ge=3, le=5, description="Number of test cases to generate (3 to 5)")
    idempotency_key: Optional[str] = Field(None, max_length=128, description="Client-supplied idempotency key")
    test_type_focus: Optional[str] = Field(None, description="Optional focus filter (e.g. 'safety', 'boundary')")


class TestSuiteSummaryItem(BaseModel):
    """Lightweight test suite summary for listing endpoints."""
    model_config = {"protected_namespaces": ()}

    generation_id: str
    selection_id: Optional[str] = None
    document_id: str
    document_version_label: str
    requested_count: int
    generated_count: int
    provider_name: str
    model_name: str
    created_at: datetime
    idempotency_key: Optional[str] = None
    validation_status: str
    human_review_required: bool


class TestCaseStalenessReport(BaseModel):
    """Staleness evaluation for an individual generated QA test case against target version."""
    test_case_id: str
    title: str
    source_section_number: Optional[str] = None
    source_heading: str
    source_node_version_id: str
    original_content_hash: str
    target_content_hash: Optional[str] = None
    status: str  # "CURRENT" | "STALE" | "SOURCE_REMOVED" | "SOURCE_MOVED" | "AMBIGUOUS" | "UNAVAILABLE"
    classification: str  # "NO_CHANGE" | "NUMERIC_CHANGE" | "TIMING_CHANGE" | etc.
    deltas: List[DetectedValueDeltaSchema] = Field(default_factory=list)
    explanation: str
    human_review_required: bool


class TestSuiteStalenessResponse(BaseModel):
    """Aggregated staleness report for a complete test suite against a newer document version."""
    generation_id: str
    selection_id: Optional[str] = None
    pinned_version_label: str
    target_version_label: str
    aggregate_status: str  # "CURRENT" | "REVIEW_REQUIRED" | "IMPACTED" | "AMBIGUOUS"
    summary: Dict[str, int]
    human_review_required: bool
    disclaimer: str
    test_case_assessments: List[TestCaseStalenessReport] = Field(default_factory=list)


class DocumentTestSuiteImpactResponse(BaseModel):
    """Document-wide impact analysis across all generated test suites for a revision."""
    document_id: str
    from_version: str
    to_version: str
    total_test_suites_evaluated: int
    impacted_test_suites_count: int
    current_test_suites_count: int
    human_review_required: bool
    disclaimer: str
    affected_suites: List[TestSuiteStalenessResponse] = Field(default_factory=list)
    unaffected_suites: List[TestSuiteStalenessResponse] = Field(default_factory=list)
