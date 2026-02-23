"""Code execution API endpoints.

Same API shape as the original TidyBot-Services code executor:
  POST /api/code/execute   — submit code (lease required)
  POST /api/code/validate  — validate only (no lease needed)
  POST /api/code/stop      — stop running code (lease required)
  GET  /api/code/status    — live stdout/stderr with offset polling
  GET  /api/code/result    — last completed execution result
"""

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from typing import Optional

from agent_server.code_executor import CodeExecutor, CodeValidationError

router = APIRouter(prefix="/api/code", tags=["code"])

# Set by server.py at startup
_code_executor: Optional[CodeExecutor] = None
_lease_manager = None


def set_code_executor(executor: CodeExecutor):
    global _code_executor
    _code_executor = executor


def set_lease_manager(manager):
    global _lease_manager
    _lease_manager = manager


def _executor() -> CodeExecutor:
    if _code_executor is None:
        raise HTTPException(status_code=503, detail="Code executor not initialised")
    return _code_executor


async def _require_lease(lease_id: Optional[str]) -> str:
    """Validate X-Lease-Id header against the active lease."""
    if not lease_id:
        raise HTTPException(status_code=401, detail="X-Lease-Id header required")
    if _lease_manager is None:
        raise HTTPException(status_code=503, detail="Lease manager not initialised")
    if not await _lease_manager.validate_lease(lease_id):
        raise HTTPException(status_code=403, detail="Invalid or expired lease")
    return lease_id


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ExecuteRequest(BaseModel):
    code: str
    timeout: float = 300


class ValidateRequest(BaseModel):
    code: str


class StopRequest(BaseModel):
    reason: str = "user requested"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/execute")
async def execute_code(
    req: ExecuteRequest,
    x_lease_id: Optional[str] = Header(None),
):
    """Submit Python code for execution. Requires active lease."""
    await _require_lease(x_lease_id)
    executor = _executor()

    try:
        execution_id = executor.execute(req.code, timeout=req.timeout)
    except CodeValidationError as e:
        return {"ok": False, "error": f"Validation failed: {e}"}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    return {"ok": True, "execution_id": execution_id}


@router.post("/validate")
async def validate_code(req: ValidateRequest):
    """Validate code without executing. No lease required."""
    executor = _executor()
    try:
        executor.validator.validate(req.code)
    except CodeValidationError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


@router.post("/stop")
async def stop_code(
    req: StopRequest = StopRequest(),
    x_lease_id: Optional[str] = Header(None),
):
    """Stop running code. Requires active lease."""
    await _require_lease(x_lease_id)
    executor = _executor()
    stopped = executor.stop(reason=req.reason)
    return {"ok": stopped}


@router.get("/status")
async def code_status(
    stdout_offset: int = 0,
    stderr_offset: int = 0,
):
    """Live execution status with incremental output."""
    executor = _executor()
    return executor.status_incremental(stdout_offset, stderr_offset)


@router.get("/result")
async def code_result():
    """Last completed execution result."""
    executor = _executor()
    r = executor.result()
    if r is None:
        return {"ok": False, "error": "No execution result available"}
    return {"ok": True, **r}


@router.get("/history")
async def code_history():
    """Execution history (most recent first)."""
    executor = _executor()
    return {"ok": True, "history": executor.history()}
