from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime
from enum import Enum

class ComplianceType(str, Enum):
    GST = "gst"
    TDS = "tds"
    ROC = "roc"
    CUSTOM = "custom"

class DeadlineStatus(str, Enum):
    UPCOMING = "upcoming"
    OVERDUE = "overdue"
    COMPLETED = "completed"
    PENDING = "pending"

class DeadlineBase(BaseModel):
    type: ComplianceType
    subtype: str
    due_date: date
    description: str
    amount: Optional[float] = None
    penalty_rate: Optional[float] = None
    filing_portal: Optional[str] = None

class DeadlineCreate(DeadlineBase):
    business_id: str

class DeadlineResponse(DeadlineBase):
    id: str
    business_id: str
    status: DeadlineStatus
    created_at: datetime
    completed_at: Optional[datetime]
    
    class Config:
        from_attributes = True

class GSTFilingBase(BaseModel):
    filing_type: str = "GSTR-3B"
    period_month: int = Field(..., ge=1, le=12)
    period_year: int = Field(..., ge=2000, le=2100)
    total_taxable_value: Optional[float] = None
    total_tax_liability: Optional[float] = None
    itc_available: Optional[float] = None
    itc_claimed: Optional[float] = None
    payment_made: Optional[float] = None

class GSTFilingCreate(GSTFilingBase):
    business_id: str

class GSTFilingResponse(GSTFilingBase):
    id: str
    business_id: str
    due_date: date
    filed_on: Optional[datetime]
    status: str = "pending"
    reconciliation_status: str = "pending"
    challan_number: Optional[str] = None
    
    class Config:
        from_attributes = True

class DashboardMetrics(BaseModel):
    upcoming_deadlines: int
    compliance_health: float  # Percentage
    penalty_risk: str  # "low", "medium", "high"
    recent_activities: List[dict]
    quick_stats: dict
    
    class Config:
        from_attributes = True
