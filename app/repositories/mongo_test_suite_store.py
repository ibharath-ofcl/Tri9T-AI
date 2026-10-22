"""MongoDB document-store implementation for generated QA test suites.

Supports:
- MongoDB document persistence for high-throughput distributed setups.
- Unique index enforcement on generation_id and idempotency_key.
- Graceful degradation when MongoDB or pymongo driver is not available.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.repositories.test_suite_store import TestSuiteStore
from app.schemas.qa_test_case import GeneratedTestSuitePayload

logger = logging.getLogger(__name__)


class MongoTestSuiteStore(TestSuiteStore):
    """MongoDB document store using PyMongo."""

    def __init__(
        self,
        mongo_uri: Optional[str] = None,
        database_name: Optional[str] = None,
        collection_name: Optional[str] = None,
    ):
        try:
            import importlib
            self.pymongo = importlib.import_module("pymongo")
        except ImportError:
            raise RuntimeError(
                "pymongo package is not installed. Install pymongo (pip install pymongo) "
                "or configure TEST_SUITE_STORE_TYPE=json."
            )

        uri = mongo_uri or settings.mongo_uri
        db_name = database_name or settings.mongo_database_name
        coll_name = collection_name or settings.mongo_collection_name

        self.client = self.pymongo.MongoClient(uri, serverSelectionTimeoutMS=3000)
        self.db = self.client[db_name]
        self.collection = self.db[coll_name]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """Create unique indexes on generation_id and idempotency_key."""
        self.collection.create_index("generation_id", unique=True)
        self.collection.create_index("idempotency_key", unique=True, sparse=True)
        self.collection.create_index("selection_id")
        self.collection.create_index("document_id")
        self.collection.create_index("source_node_version_ids")

    def save_test_suite(self, suite: GeneratedTestSuitePayload) -> None:
        data = suite.model_dump(mode="json")
        data["_id"] = suite.generation_id
        self.collection.replace_one({"_id": suite.generation_id}, data, upsert=True)

    def get_test_suite(self, generation_id: str) -> Optional[GeneratedTestSuitePayload]:
        doc = self.collection.find_one({"generation_id": generation_id})
        if not doc:
            return None
        doc.pop("_id", None)
        return GeneratedTestSuitePayload.model_validate(doc)

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[GeneratedTestSuitePayload]:
        if not idempotency_key:
            return None
        doc = self.collection.find_one({"idempotency_key": idempotency_key})
        if not doc:
            return None
        doc.pop("_id", None)
        return GeneratedTestSuitePayload.model_validate(doc)

    def list_test_suites(
        self,
        selection_id: Optional[str] = None,
        node_version_id: Optional[str] = None,
        document_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[GeneratedTestSuitePayload]:
        query = {}
        if selection_id:
            query["selection_id"] = selection_id
        if document_id:
            query["document_id"] = document_id
        if node_version_id:
            query["source_node_version_ids"] = node_version_id

        cursor = self.collection.find(query).sort("created_at", -1).limit(limit)
        results = []
        for doc in cursor:
            doc.pop("_id", None)
            results.append(GeneratedTestSuitePayload.model_validate(doc))
        return results

    def delete_test_suite(self, generation_id: str) -> bool:
        res = self.collection.delete_one({"generation_id": generation_id})
        return res.deleted_count > 0
