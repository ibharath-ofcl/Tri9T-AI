"""Abstract document-store interface for persisting and querying generated QA test suites."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional

from app.schemas.qa_test_case import GeneratedTestSuitePayload


class TestSuiteStore(ABC):
    """Abstract repository for persisting and querying generated test-suite documents."""

    @abstractmethod
    def save_test_suite(self, suite: GeneratedTestSuitePayload) -> None:
        """Persist a validated test-suite document atomically."""
        pass

    @abstractmethod
    def get_test_suite(self, generation_id: str) -> Optional[GeneratedTestSuitePayload]:
        """Retrieve a generated test suite by unique generation ID."""
        pass

    @abstractmethod
    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[GeneratedTestSuitePayload]:
        """Fetch previously generated test suite matching idempotency key."""
        pass

    @abstractmethod
    def list_test_suites(
        self,
        selection_id: Optional[str] = None,
        node_version_id: Optional[str] = None,
        document_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[GeneratedTestSuitePayload]:
        """List test suites filtered by selection, source node snapshot, or document."""
        pass

    @abstractmethod
    def delete_test_suite(self, generation_id: str) -> bool:
        """Delete a generated test suite document by generation ID."""
        pass


def get_test_suite_store(custom_store: Optional[TestSuiteStore] = None) -> TestSuiteStore:
    """Factory creating configured document store instance."""
    if custom_store is not None:
        return custom_store

    from app.core.config import settings

    store_type = settings.test_suite_store_type.lower().strip()
    if store_type == "mongo":
        try:
            from app.repositories.mongo_test_suite_store import MongoTestSuiteStore
            return MongoTestSuiteStore()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to initialize MongoTestSuiteStore (%s), falling back to JsonTestSuiteStore.", e)
            from app.repositories.json_test_suite_store import JsonTestSuiteStore
            return JsonTestSuiteStore()
    else:
        from app.repositories.json_test_suite_store import JsonTestSuiteStore
        return JsonTestSuiteStore()
