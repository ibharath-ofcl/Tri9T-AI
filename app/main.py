"""Minimal FastAPI application for CT-200 Document Intelligence Engine.

Provides /health status and /api/v1/documents/preview endpoints for development
verification and hierarchy inspection.
"""

from typing import Any, Dict
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.schemas.document import DocumentTree
from app.services.pdf_parser import CT200PDFParser

app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="Document Intelligence API for CT-200 Blood Pressure Monitor Manuals",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

parser = CT200PDFParser()

# Whitelisted manual versions mapping strictly to known local paths
# Prevents arbitrary path traversal or filesystem access
MANUAL_VERSIONS = {
    "v1": settings.v1_manual_path,
    "v2": settings.v2_manual_path,
}


@app.get("/health", tags=["System"])
def get_health() -> Dict[str, Any]:
    """Health check endpoint verifying system responsiveness and asset presence."""
    v1_exists = settings.v1_manual_path.exists()
    v2_exists = settings.v2_manual_path.exists()
    all_ready = v1_exists and v2_exists

    return {
        "status": "healthy" if all_ready else "degraded",
        "app_name": settings.app_name,
        "environment": settings.app_env,
        "assets_status": {
            "v1_manual_present": v1_exists,
            "v2_manual_present": v2_exists,
            "data_dir": str(settings.data_dir),
        },
    }


@app.get(
    f"{settings.api_v1_prefix}/documents/preview",
    response_model=DocumentTree,
    tags=["Documents"],
    summary="Preview parsed document hierarchy and diagnostics",
)
def preview_document(
    version: str = Query(
        "v1",
        description="Manual version to parse ('v1' or 'v2')",
        regex="^(v1|v2)$",
    )
) -> DocumentTree:
    """Parse and return full document tree, metadata, hashes, and diagnostics for v1 or v2."""
    if version not in MANUAL_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid version '{version}'. Allowed versions are: {list(MANUAL_VERSIONS.keys())}",
        )

    target_file = MANUAL_VERSIONS[version]
    if not target_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Manual file for version '{version}' not found on server at {target_file.name}",
        )

    try:
        doc_tree = parser.parse(target_file, version_label=version)
        return doc_tree
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse document version '{version}': {str(exc)}",
        )
