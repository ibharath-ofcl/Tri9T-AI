"""LLM Provider abstraction layer supporting OpenAI-compatible endpoints and deterministic mock provider."""

from __future__ import annotations
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

import httpx

from app.core.config import Settings, settings as default_settings

logger = logging.getLogger(__name__)


class LLMProviderError(Exception):
    """Base exception for LLM provider errors."""
    pass


class LLMConfigurationError(LLMProviderError):
    """Raised when required credentials or settings are missing."""
    pass


class LLMTransientError(LLMProviderError):
    """Raised for transient HTTP errors (5xx, 429, timeouts) eligible for bounded retry."""
    pass


class BaseLLMProvider(ABC):
    """Abstract interface for LLM chat completion providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider (e.g. 'openai', 'mock')."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Name of the model (e.g. 'gpt-4o-mini', 'mock-ct200-qa')."""
        pass

    @abstractmethod
    def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 2500,
    ) -> str:
        """Execute chat completion and return raw response text."""
        pass


class OpenAICompatibleProvider(BaseLLMProvider):
    """Production provider for OpenAI-compatible chat completion APIs."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
    ):
        if not api_key or not api_key.strip():
            raise LLMConfigurationError("LLM_API_KEY is required for OpenAICompatibleProvider.")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self._model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 2500,
    ) -> str:
        """Call OpenAI-compatible chat completion endpoint with bounded retries."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        attempts = 0
        last_error = None

        while attempts < self.max_retries:
            attempts += 1
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    resp = client.post(url, headers=headers, json=payload)

                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if not choices:
                        raise LLMProviderError("Empty choices returned from LLM provider.")
                    content = choices[0].get("message", {}).get("content", "")
                    return content

                # Classify HTTP error
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_error = LLMTransientError(
                        f"Transient provider error (HTTP {resp.status_code}). Attempt {attempts}/{self.max_retries}."
                    )
                    time.sleep(0.5 * (2 ** (attempts - 1)))  # Exponential backoff
                    continue
                elif resp.status_code == 401:
                    raise LLMConfigurationError("Authentication failed: invalid LLM_API_KEY.")
                else:
                    raise LLMProviderError(f"Provider request failed (HTTP {resp.status_code}): {resp.text[:200]}")

            except (httpx.TimeoutException, httpx.NetworkError) as net_err:
                last_error = LLMTransientError(f"Network timeout or connection error: {str(net_err)}")
                time.sleep(0.5 * (2 ** (attempts - 1)))
                continue

        raise last_error or LLMProviderError(f"Provider call failed after {self.max_retries} attempts.")


class MockLLMProvider(BaseLLMProvider):
    """Deterministic, grounded mock provider for local verification and repeatable test suites.

    Produces realistic CT-200 medical device QA test cases without external network calls.
    Can be configured to inject simulated failures (e.g. malformed JSON on attempt 1) for retry testing.
    """

    def __init__(
        self,
        model: str = "mock-ct200-qa-v1",
        custom_responses: Optional[List[str]] = None,
        failure_generator: Optional[Callable[[int], Optional[str]]] = None,
    ):
        self._model = model
        self.custom_responses = custom_responses or []
        self.failure_generator = failure_generator
        self.invocation_count = 0

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return self._model

    def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 2500,
    ) -> str:
        self.invocation_count += 1

        # Check if failure generator is active
        if self.failure_generator:
            custom_fail = self.failure_generator(self.invocation_count)
            if custom_fail is not None:
                return custom_fail

        # Return custom queued response if present
        if self.custom_responses:
            idx = min(self.invocation_count - 1, len(self.custom_responses) - 1)
            return self.custom_responses[idx]

        # Extract requested count from messages
        user_msg = messages[-1]["content"] if messages else ""
        target_count = 4
        for c in (3, 4, 5):
            if f"exactly {c}" in user_msg.lower() or f"{c} test cases" in user_msg.lower() or f"{c} distinct" in user_msg.lower():
                target_count = c
                break

        # Inspect source context in user prompt to generate strictly grounded cases
        is_battery = "battery" in user_msg.lower() or "2.1.1.1" in user_msg
        is_cuff = "cuff" in user_msg.lower() or "3.2" in user_msg
        is_error = "error" in user_msg.lower() or "4.2" in user_msg or "deflate" in user_msg.lower()

        test_cases = []

        if is_battery:
            test_cases.append({
                "TestCaseId": "TC-BAT-001",
                "Title": "Verify Battery Low-Charge Threshold Icon Display",
                "Prerequisites": [
                    "CardioTrack CT-200 unit with four fresh AA alkaline batteries",
                    "[PROPOSED SETUP] Programmable DC power supply attached to battery terminals to simulate voltage drop"
                ],
                "Steps": [
                    "1. Connect the programmable DC power supply to the battery terminal.",
                    "2. Lower the supply voltage until the remaining capacity drops below 15%.",
                    "3. Observe the LCD display screen for the battery status indicator icon."
                ],
                "ExpectedResult": "The device displays a low-battery icon once remaining capacity falls below 15%.",
                "PassFailCriteria": "PASS if low-battery icon appears once remaining capacity falls below 15%; FAIL if icon does not appear.",
                "StandardRef": "CT-200 Manual Section 2.1.1.1 Battery Life Under Typical Use; no external standard specified in manual",
                "TestType": "boundary",
                "CoverageTags": ["battery", "p0_safety", "threshold"],
                "HumanReviewRequired": False,
            })
            test_cases.append({
                "TestCaseId": "TC-BAT-002",
                "Title": "Verify Battery Measurement Cycle Rating Degradation",
                "Prerequisites": [
                    "CardioTrack CT-200 unit with four fresh AA alkaline batteries",
                    "[PROPOSED SETUP] Automated cycling endurance fixture simulating 3 measurements per day"
                ],
                "Steps": [
                    "1. Subject the CT-200 monitor to continuous cycling of 3 measurements per day.",
                    "2. Record battery discharge curves up to 300 cycles.",
                    "3. Verify unit operates without battery replacement warning up to 300 measurement cycles."
                ],
                "ExpectedResult": "Four AA alkaline batteries provide approximately 300 measurement cycles under typical use (three measurements per day) before requiring replacement.",
                "PassFailCriteria": "PASS if device completes approximately 300 measurement cycles before battery replacement warning; FAIL if exhausted significantly earlier.",
                "StandardRef": "CT-200 Manual Section 2.1.1.1 Battery Life Under Typical Use; no external standard specified in manual",
                "TestType": "nominal",
                "CoverageTags": ["battery", "endurance", "rating"],
                "HumanReviewRequired": False,
            })

        if is_cuff or not is_battery:
            test_cases.append({
                "TestCaseId": "TC-CUFF-001",
                "Title": "Verify Incremental Cuff Inflation Step Size and Maximum Limit",
                "Prerequisites": [
                    "CardioTrack CT-200 unit and standard adult cuff",
                    "[PROPOSED SETUP] Calibrated digital manometer connected inline to cuff bladder",
                    "[PROPOSED SETUP] Rigid artificial limb test fixture without pulse signal to trigger re-inflation steps"
                ],
                "Steps": [
                    "1. Attach cuff to artificial limb fixture and connect manometer inline.",
                    "2. Initiate blood pressure measurement.",
                    "3. In the absence of detected pulse at initial 180 mmHg target, measure the step increment size for subsequent inflation.",
                    "4. Observe maximum cutoff pressure before abort."
                ],
                "ExpectedResult": "If the user's pulse is not detected by 180 mmHg, the device inflates in 40 mmHg increments up to a maximum of 299 mmHg before aborting with an error.",
                "PassFailCriteria": "PASS if device inflates in 40 mmHg increments up to a maximum of 299 mmHg before aborting; FAIL if increment differs from 40 mmHg or maximum exceeds 299 mmHg.",
                "StandardRef": "CT-200 Manual Section 3.2 Cuff Inflation Sequence; no external standard specified in manual",
                "TestType": "boundary",
                "CoverageTags": ["cuff", "pressure", "step_increment"],
                "HumanReviewRequired": False,
            })

        if is_error or len(test_cases) < target_count:
            test_cases.append({
                "TestCaseId": "TC-ERR-001",
                "Title": "Verify Overpressure Condition E3 Auto-Deflation Timing",
                "Prerequisites": [
                    "CardioTrack CT-200 blood pressure monitor",
                    "[PROPOSED SETUP] Pneumatic test bench with fast-action overpressure valve",
                    "[PROPOSED SETUP] Calibrated digital pressure transducer and oscilloscope"
                ],
                "Steps": [
                    "1. Connect the CT-200 pneumatic port to the test bench.",
                    "2. Induce an artificial overpressure condition exceeding normal operational limits.",
                    "3. Trigger timing capture upon overpressure detection.",
                    "4. Measure the elapsed duration until auto-deflation completes."
                ],
                "ExpectedResult": "Upon detecting overpressure condition, the device auto-deflates within 2 seconds and displays error code E3.",
                "PassFailCriteria": "PASS if cuff auto-deflates within 2 seconds and error code E3 is displayed on LCD; FAIL otherwise.",
                "StandardRef": "CT-200 Manual Section 4.2 Error Codes (Table 4.1); no external standard specified in manual",
                "TestType": "timing",
                "CoverageTags": ["error_handling", "safety", "auto_deflation", "timing"],
                "HumanReviewRequired": False,
            })

        # Ensure we match the exact target count
        while len(test_cases) < target_count:
            num = len(test_cases) + 1
            test_cases.append({
                "TestCaseId": f"TC-GEN-00{num}",
                "Title": f"Verify Adult Arm Circumference Range Operational Eligibility {num}",
                "Prerequisites": [
                    "CardioTrack CT-200 blood pressure monitor and cuff",
                    "[PROPOSED SETUP] Calibrated cylindrical arm circumference test forms within 22–42 cm"
                ],
                "Steps": [
                    "1. Fit cuff onto arm form calibrated to 22 cm circumference and execute measurement.",
                    "2. Fit cuff onto arm form calibrated to 42 cm circumference and execute measurement.",
                    "3. Verify device status indicator confirms ready state."
                ],
                "ExpectedResult": "The CT-200 is intended to non-invasively measure blood pressure in adults with an arm circumference of 22–42 cm.",
                "PassFailCriteria": "PASS if cuff accommodates adult arm circumference range of 22–42 cm and operates normally; FAIL otherwise.",
                "StandardRef": "CT-200 Manual Section 1.1 Intended Use; no external standard specified in manual",
                "TestType": "nominal",
                "CoverageTags": ["general", "nominal"],
                "HumanReviewRequired": False,
            })

        return json.dumps({"test_cases": test_cases[:target_count]})


def get_llm_provider(config: Optional[Settings] = None) -> BaseLLMProvider:
    """Factory creating configured LLM provider instance."""
    cfg = config or default_settings
    provider_type = cfg.llm_provider.lower().strip()

    if provider_type == "openai":
        if not cfg.llm_api_key or not cfg.llm_api_key.strip():
            raise LLMConfigurationError(
                "LLM provider is configured as 'openai', but LLM_API_KEY is missing. "
                "Set LLM_API_KEY in your environment/.env or set LLM_PROVIDER=mock for local test/demo mode."
            )
        return OpenAICompatibleProvider(
            api_key=cfg.llm_api_key,
            base_url=cfg.llm_api_base_url,
            model=cfg.llm_model,
            timeout_seconds=cfg.llm_timeout_seconds,
            max_retries=cfg.llm_max_retries,
        )
    elif provider_type == "mock":
        return MockLLMProvider(model=cfg.llm_model)
    else:
        raise LLMConfigurationError(
            f"Unsupported LLM_PROVIDER '{cfg.llm_provider}'. Supported: 'openai', 'mock'."
        )
