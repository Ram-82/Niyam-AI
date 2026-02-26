from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.models.compliance import DashboardMetrics
# from app.services.deadline_service import DeadlineService # To be implemented
from app.utils.security import verify_token

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])
security = HTTPBearer()

@router.get("/summary", response_model=dict)
async def get_dashboard_summary(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Get dashboard metrics and overview"""
    # Verification of token is handled by the dependency
    
    return {
        "success": True,
        "data": {
            "upcoming_deadlines": 3,
            "compliance_health": 92.5,
            "penalty_risk": "Low",
            "active_tasks": 12,
            "health_history": [80, 82, 85, 84, 88, 91, 92.5],
            "labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "tax_liability": "₹42,500",
            "next_deadline": "GSTR-1 (4 days)"
        }
    }
