from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class ForecastItem(BaseModel):
    stay_date: str
    room_type: str
    demand_forecast: float
    competitor_rate: float | None = None
    recommended_adr: float

class BriefRequest(BaseModel):
    send: bool = False
    to_email: Optional[EmailStr] = None

class ETLRunResponse(BaseModel):
    message: str
