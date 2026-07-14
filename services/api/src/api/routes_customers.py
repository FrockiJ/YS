from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import SessionLocal
from ..models.customer import Customer
from ..schemas.customer import CustomerCreate, CustomerRead, CustomerUpdate


router = APIRouter()


async def get_db():
    async with SessionLocal() as db:
        yield db


@router.get("/customers", response_model=List[CustomerRead])
async def list_customers(
    name: Optional[str] = None,
    email: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    filters = []
    if name:
        filters.append(Customer.name.ilike(f"%{name}%"))
    if email:
        filters.append(Customer.email.ilike(f"%{email}%"))

    query = select(Customer)
    if filters:
        query = query.where(*filters)
    result = await db.execute(query.order_by(Customer.created_at.desc()))
    return result.scalars().all()


@router.post("/customers", response_model=CustomerRead, status_code=201)
async def create_customer(payload: CustomerCreate, db: AsyncSession = Depends(get_db)):
    customer = Customer(**payload.model_dump(exclude_unset=True))
    db.add(customer)
    try:
        await db.commit()
        await db.refresh(customer)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create customer") from exc
    return customer


@router.get("/customers/{customer_id}", response_model=CustomerRead)
async def get_customer(customer_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalars().first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.patch("/customers/{customer_id}", response_model=CustomerRead)
async def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalars().first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(customer, key, value)
    try:
        await db.commit()
        await db.refresh(customer)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update customer") from exc
    return customer
