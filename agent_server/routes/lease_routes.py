"""Lease API endpoints — pure lease management (acquire/release/extend/status)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/lease", tags=["lease"])

# Will be set by server.py at startup
_lease_manager = None


def set_lease_manager(manager):
    global _lease_manager
    _lease_manager = manager


def _mgr():
    if _lease_manager is None:
        raise HTTPException(status_code=503, detail="Lease manager not initialised")
    return _lease_manager


class AcquireRequest(BaseModel):
    holder: str


class LeaseIdRequest(BaseModel):
    lease_id: str


@router.post("/acquire")
async def acquire(req: AcquireRequest):
    result = await _mgr().acquire(req.holder)
    return result


@router.post("/release")
async def release(req: LeaseIdRequest):
    result = await _mgr().release(req.lease_id)
    return result


@router.post("/extend")
async def extend(req: LeaseIdRequest):
    result = await _mgr().extend(req.lease_id)
    return result


@router.get("/status")
async def status():
    return _mgr().status()
