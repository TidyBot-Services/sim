"""Simplified lease manager for gating robot access.

Single-holder lease with idle timeout and max duration.
Based on the original TidyBot-Services lease pattern, simplified for sim
(no queue/ticket system — returns "busy" if held by someone else).
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from agent_server.config import LeaseConfig


@dataclass
class Lease:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    holder: str = ""
    acquired_at: float = 0.0
    last_command_at: float = 0.0
    expires_at: float = 0.0


class LeaseManager:
    """Single-holder lease with idle timeout and hard duration cap."""

    def __init__(
        self,
        cfg: LeaseConfig,
        on_lease_end: Optional[Callable] = None,
        on_code_stop: Optional[Callable] = None,
    ):
        self._cfg = cfg
        self._on_lease_end = on_lease_end
        self._on_code_stop = on_code_stop
        self._lock = asyncio.Lock()
        self._lease: Optional[Lease] = None
        self._check_task: Optional[asyncio.Task] = None
        self._resetting = False

    async def start(self):
        """Start the background idle-check loop."""
        if self._check_task is None:
            self._check_task = asyncio.create_task(self._check_loop())

    async def stop(self):
        """Cancel the background check loop."""
        if self._check_task is not None:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
            self._check_task = None

    async def acquire(self, holder: str) -> dict:
        """Acquire the lease. Returns lease info or error if busy."""
        async with self._lock:
            if self._resetting:
                return {"ok": False, "error": "scene is resetting"}
            if self._lease is not None:
                if self._lease.holder == holder:
                    # Same holder re-acquiring — extend instead
                    self._lease.last_command_at = time.time()
                    return {"ok": True, "lease": self._lease_dict()}
                return {"ok": False, "error": "busy", "holder": self._lease.holder}

            now = time.time()
            self._lease = Lease(
                holder=holder,
                acquired_at=now,
                last_command_at=now,
                expires_at=now + self._cfg.max_duration_s,
            )
            return {"ok": True, "lease": self._lease_dict()}

    async def release(self, lease_id: str) -> dict:
        """Release the lease. Must provide the correct lease_id."""
        async with self._lock:
            if self._lease is None:
                return {"ok": False, "error": "no active lease"}
            if self._lease.id != lease_id:
                return {"ok": False, "error": "lease_id mismatch"}
            await self._end_lease("released")
            return {"ok": True}

    async def extend(self, lease_id: str) -> dict:
        """Extend the lease idle timer (heartbeat)."""
        async with self._lock:
            if self._lease is None:
                return {"ok": False, "error": "no active lease"}
            if self._lease.id != lease_id:
                return {"ok": False, "error": "lease_id mismatch"}
            self._lease.last_command_at = time.time()
            return {"ok": True, "lease": self._lease_dict()}

    def record_command(self):
        """Record that a command was executed (updates idle timer).

        Non-async, safe to call from sync context via fire-and-forget.
        """
        if self._lease is not None:
            self._lease.last_command_at = time.time()

    async def validate_lease(self, lease_id: str) -> bool:
        """Check if a lease_id matches the current active lease."""
        async with self._lock:
            return self._lease is not None and self._lease.id == lease_id

    def status(self) -> dict:
        """Return current lease status (no lock needed for read)."""
        if self._resetting:
            return {"state": "resetting", "holder": None, "remaining": 0}
        if self._lease is None:
            return {"state": "free", "holder": None, "remaining": 0}
        remaining = max(0, self._lease.expires_at - time.time())
        idle = time.time() - self._lease.last_command_at
        return {
            "state": "held",
            "holder": self._lease.holder,
            "lease_id": self._lease.id,
            "remaining": round(remaining, 1),
            "idle": round(idle, 1),
        }

    def _lease_dict(self) -> dict:
        """Serialise the current lease for API responses."""
        if self._lease is None:
            return {}
        return {
            "id": self._lease.id,
            "holder": self._lease.holder,
            "remaining": round(max(0, self._lease.expires_at - time.time()), 1),
        }

    async def _end_lease(self, reason: str):
        """Clear the lease, stop running code, and optionally reset the scene."""
        holder = self._lease.holder if self._lease else "unknown"
        self._lease = None
        print(f"[lease] Lease ended ({reason}) — holder was '{holder}'")
        # Stop any running code before resetting
        if self._on_code_stop:
            self._on_code_stop(reason)
        if self._cfg.reset_on_release and self._on_lease_end:
            self._resetting = True
            try:
                self._on_lease_end()
            finally:
                self._resetting = False

    async def _check_loop(self):
        """Background loop that checks for idle timeout and max duration."""
        while True:
            await asyncio.sleep(self._cfg.check_interval_s)
            async with self._lock:
                if self._lease is None:
                    continue
                now = time.time()
                idle = now - self._lease.last_command_at
                if idle > self._cfg.idle_timeout_s:
                    await self._end_lease(f"idle timeout ({idle:.0f}s)")
                    continue
                if now > self._lease.expires_at:
                    await self._end_lease("max duration reached")
