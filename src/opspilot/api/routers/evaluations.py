"""Latest locally generated evaluation reports."""

from fastapi import APIRouter, Depends

from opspilot.api.dependencies import get_services
from opspilot.api.security import require_api_key
from opspilot.api.services import APIServices

router = APIRouter(
    prefix="/v1/evals",
    tags=["evaluation"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/latest")
def latest_evaluations(services: APIServices = Depends(get_services)) -> dict[str, object]:
    """Expose bounded excerpts from the latest local Markdown/CSV/JSON reports."""
    return services.latest_eval_reports()
