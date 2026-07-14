from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CustomerBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    cerp_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    cerp_id: Optional[str] = None
    tags: Optional[List[str]] = None


class CustomerOut(CustomerBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
