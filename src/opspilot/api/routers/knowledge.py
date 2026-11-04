"""Authenticated knowledge-base search endpoint."""

from fastapi import APIRouter, Depends, HTTPException

from opspilot.api.dependencies import get_services
from opspilot.api.schemas import KnowledgeSearchRequest
from opspilot.api.security import require_api_key
from opspilot.api.services import APIServices

router = APIRouter(
    prefix="/v1/kb",
    tags=["knowledge"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/search")
def search_knowledge(
    body: KnowledgeSearchRequest,
    services: APIServices = Depends(get_services),
) -> dict[str, object]:
    """Search verified passages and return stable document/section citations."""
    filters = {
        key: value
        for key, value in {
            "service": body.service,
            "fault_type": body.fault_type.value if body.fault_type else None,
        }.items()
        if value is not None
    }
    try:
        chunks = services.retriever().search(body.query, k=body.k, filters=filters)
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Knowledge index is unavailable") from exc
    return {
        "query": body.query,
        "results": [
            {
                "doc_id": chunk.doc_id,
                "section": chunk.section,
                "score": chunk.score,
                "text": chunk.text,
                "citation": chunk.citation.model_dump(mode="json"),
            }
            for chunk in chunks
        ],
    }
