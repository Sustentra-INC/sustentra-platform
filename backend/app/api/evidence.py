from fastapi import APIRouter

router = APIRouter(prefix="/v1", tags=["evidence"])


@router.get("/engagements/{engagement_id}/evidence")
def list_evidence(engagement_id: str) -> dict[str, list[dict[str, str]]]:
    return {
        "engagement_id": engagement_id,
        "items": [
            {
                "evidence_id": "ev_demo_001",
                "document_id": "doc_demo_001",
                "evidence_type": "utility_bill",
                "review_status": "in_review"
            }
        ]
    }


@router.get("/evidence/{evidence_id}")
def get_evidence(evidence_id: str) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "engagement_id": "eng_demo_001",
        "document_id": "doc_demo_001",
        "evidence_type": "utility_bill",
        "review_status": "in_review",
        "fields": []
    }


@router.get("/engagements/{engagement_id}/approved-evidence")
def list_approved_evidence(engagement_id: str) -> dict[str, list[dict[str, object]]]:
    return {
        "engagement_id": engagement_id,
        "items": [
            {
                "evidence_id": "ev_demo_001",
                "document_id": "doc_demo_001",
                "evidence_type": "utility_bill",
                "review_status": "approved",
                "fields": []
            }
        ]
    }
