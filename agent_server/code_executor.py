"""Code validation and execution for the sim agent server.

Clients submit Python source code as a string. The code is validated via
AST-based static analysis, then executed in a background thread with
stdout/stderr capture and offset-based polling.

Based on the original TidyBot-Services code_executor pattern.
"""

import ast
import ctypes
import io
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Code Validator
# ---------------------------------------------------------------------------

BLOCKED_MODULES = frozenset({
    "subprocess", "shutil", "signal", "ctypes",
    "multiprocessing", "socket", "http", "urllib",
    "requests", "pathlib", "tempfile",
})

BLOCKED_OS_ATTRS = frozenset({
    "system", "popen", "exec", "execl", "execle", "execlp", "execlpe",
    "execv", "execve", "execvp", "execvpe", "spawn", "spawnl", "spawnle",
    "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
    "kill", "killpg", "remove", "unlink", "rmdir", "removedirs",
    "rename", "renames", "replace",
})

BLOCKED_BUILTINS = frozenset({
    "eval", "exec", "compile", "__import__", "breakpoint",
})


class CodeValidationError(Exception):
    """Raised when submitted code fails validation."""


class CodeValidator:
    """AST-based static analysis to block dangerous code patterns."""

    def validate(self, source: str) -> None:
        """Validate source code. Raises CodeValidationError on failure."""
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            raise CodeValidationError(f"Syntax error: {e}") from e

        for node in ast.walk(tree):
            self._check_imports(node)
            self._check_calls(node)

    def _check_imports(self, node: ast.AST) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in BLOCKED_MODULES:
                    raise CodeValidationError(
                        f"Import of '{alias.name}' is not allowed"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if top in BLOCKED_MODULES:
                    raise CodeValidationError(
                        f"Import from '{node.module}' is not allowed"
                    )

    def _check_calls(self, node: ast.AST) -> None:
        if not isinstance(node, ast.Call):
            return

        func = node.func

        # Block dangerous builtins: eval(), exec(), etc.
        if isinstance(func, ast.Name) and func.id in BLOCKED_BUILTINS:
            raise CodeValidationError(
                f"Call to '{func.id}()' is not allowed"
            )

        # Block os.system(), os.popen(), etc.
        if isinstance(func, ast.Attribute):
            if (
                isinstance(func.value, ast.Name)
                and func.value.id == "os"
                and func.attr in BLOCKED_OS_ATTRS
            ):
                raise CodeValidationError(
                    f"Call to 'os.{func.attr}()' is not allowed"
                )


# ---------------------------------------------------------------------------
# Thread-safe output buffer
# ---------------------------------------------------------------------------

class _OutputBuffer(io.TextIOBase):
    """Thread-safe string buffer that supports offset-based reads."""

    def __init__(self):
        self._lock = threading.Lock()
        self._chunks: list[str] = []
        self._total_len = 0

    def write(self, s: str) -> int:
        if not s:
            return 0
        with self._lock:
            self._chunks.append(s)
            self._total_len += len(s)
        return len(s)

    def flush(self):
        pass

    def get_output(self, offset: int = 0) -> tuple[str, int]:
        """Return (new_text, new_offset) from the given offset."""
        with self._lock:
            full = "".join(self._chunks)
        text = full[offset:]
        return text, len(full)

    def getvalue(self) -> str:
        with self._lock:
            return "".join(self._chunks)


# ---------------------------------------------------------------------------
# Execution result
# ---------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    execution_id: str = ""
    status: str = "idle"           # idle | running | completed | error | stopped
    code: str = ""
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    started_at: float = 0.0
    finished_at: float = 0.0


# ---------------------------------------------------------------------------
# Code Executor
# ---------------------------------------------------------------------------

class CodeExecutor:
    """Execute user-submitted Python code in a background thread.

    Captures stdout/stderr into buffers that support offset-based polling.
    Code can be stopped by raising SystemExit in the worker thread.
    """

    def __init__(self):
        self._validator = CodeValidator()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stdout_buf: Optional[_OutputBuffer] = None
        self._stderr_buf: Optional[_OutputBuffer] = None
        self._execution_id: Optional[str] = None
        self._code: Optional[str] = None
        self._status = "idle"
        self._exit_code: Optional[int] = None
        self._started_at = 0.0
        self._finished_at = 0.0
        self._last_result: Optional[ExecutionResult] = None
        self._history: list[ExecutionResult] = []

    @property
    def validator(self) -> CodeValidator:
        return self._validator

    def execute(self, code: str, timeout: float = 300) -> str:
        """Validate and execute code in a background thread.

        Returns the execution_id. Raises CodeValidationError if
        validation fails, or RuntimeError if code is already running.
        """
        self._validator.validate(code)

        with self._lock:
            if self._status == "running":
                raise RuntimeError("Code is already running")

            self._execution_id = uuid.uuid4().hex[:12]
            self._code = code
            self._stdout_buf = _OutputBuffer()
            self._stderr_buf = _OutputBuffer()
            self._status = "running"
            self._exit_code = None
            self._started_at = time.time()
            self._finished_at = 0.0
            eid = self._execution_id

        self._thread = threading.Thread(
            target=self._run,
            args=(code, eid, timeout),
            daemon=True,
            name=f"code-exec-{eid}",
        )
        self._thread.start()
        return eid

    def stop(self, reason: str = "stopped") -> bool:
        """Stop running code by raising SystemExit in the worker thread."""
        with self._lock:
            if self._status != "running" or self._thread is None:
                return False

        tid = self._thread.ident
        if tid is None:
            return False

        print(f"[code_executor] Stopping execution ({reason})")
        # Raise SystemExit in the target thread
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_ulong(tid),
            ctypes.py_object(SystemExit),
        )
        if res == 0:
            return False  # thread not found
        if res > 1:
            # Something went wrong — clear the exception
            ctypes.pythonapi.PyThreadState_SetAsyncExc(
                ctypes.c_ulong(tid), None
            )
            return False

        # Wait briefly for thread to die
        self._thread.join(timeout=2.0)

        with self._lock:
            if self._status == "running":
                self._status = "stopped"
                self._finished_at = time.time()
                self._save_result()

        return True

    def status(self) -> dict:
        """Current execution status with output offsets."""
        with self._lock:
            stdout_text = ""
            stderr_text = ""
            stdout_offset = 0
            stderr_offset = 0
            if self._stdout_buf:
                stdout_text, stdout_offset = self._stdout_buf.get_output(0)
            if self._stderr_buf:
                stderr_text, stderr_offset = self._stderr_buf.get_output(0)

            return {
                "status": self._status,
                "execution_id": self._execution_id or "",
                "code": self._code or "",
                "stdout": stdout_text,
                "stderr": stderr_text,
                "stdout_offset": stdout_offset,
                "stderr_offset": stderr_offset,
                "exit_code": self._exit_code,
            }

    def status_incremental(self, stdout_offset: int = 0, stderr_offset: int = 0) -> dict:
        """Status with incremental output from given offsets."""
        with self._lock:
            stdout_text = ""
            stderr_text = ""
            new_stdout_offset = stdout_offset
            new_stderr_offset = stderr_offset
            if self._stdout_buf:
                stdout_text, new_stdout_offset = self._stdout_buf.get_output(stdout_offset)
            if self._stderr_buf:
                stderr_text, new_stderr_offset = self._stderr_buf.get_output(stderr_offset)

            return {
                "status": self._status,
                "execution_id": self._execution_id or "",
                "code": self._code or "",
                "stdout": stdout_text,
                "stderr": stderr_text,
                "stdout_offset": new_stdout_offset,
                "stderr_offset": new_stderr_offset,
                "exit_code": self._exit_code,
            }

    def result(self) -> Optional[dict]:
        """Last completed execution result."""
        with self._lock:
            if self._last_result is None:
                return None
            r = self._last_result
            return {
                "execution_id": r.execution_id,
                "status": r.status,
                "stdout": r.stdout,
                "stderr": r.stderr,
                "exit_code": r.exit_code,
                "duration": round(r.finished_at - r.started_at, 2) if r.finished_at else 0,
            }

    def _save_result(self):
        """Snapshot current execution into _last_result. Must hold _lock."""
        self._last_result = ExecutionResult(
            execution_id=self._execution_id or "",
            status=self._status,
            code=self._code or "",
            stdout=self._stdout_buf.getvalue() if self._stdout_buf else "",
            stderr=self._stderr_buf.getvalue() if self._stderr_buf else "",
            exit_code=self._exit_code,
            started_at=self._started_at,
            finished_at=self._finished_at,
        )
        self._history.append(self._last_result)

    def history(self) -> list[dict]:
        """Return execution history (most recent first)."""
        with self._lock:
            return [
                {
                    "execution_id": r.execution_id,
                    "status": r.status,
                    "code": r.code,
                    "stdout": r.stdout,
                    "stderr": r.stderr,
                    "exit_code": r.exit_code,
                    "duration": round(r.finished_at - r.started_at, 2) if r.finished_at else 0,
                }
                for r in reversed(self._history)
            ]

    def _run(self, code: str, execution_id: str, timeout: float):
        """Worker thread: redirect stdout/stderr, exec code, capture result."""
        old_stdout = sys.stdout
        old_stderr = sys.stderr

        with self._lock:
            stdout_buf = self._stdout_buf
            stderr_buf = self._stderr_buf

        # Tee output: write to both the buffer and the original stream
        class _Tee(io.TextIOBase):
            def __init__(self, buf, original):
                self._buf = buf
                self._original = original

            def write(self, s):
                if s:
                    self._buf.write(s)
                    self._original.write(s)
                return len(s) if s else 0

            def flush(self):
                self._original.flush()

        sys.stdout = _Tee(stdout_buf, old_stdout)
        sys.stderr = _Tee(stderr_buf, old_stderr)

        # Set up ZMQ proxy so SDK calls route to the main thread
        from agent_server.zmq_bridge import ZmqRobotProxy
        proxy = ZmqRobotProxy()
        proxy.connect()

        from agent_server.robot_sdk import _runtime as _rt_pkg
        _rt_pkg.set_thread_robot(proxy)
        try:
            from robot_sdk import _runtime as _rt_top
            _rt_top.set_thread_robot(proxy)
        except ImportError:
            _rt_top = None

        try:
            # Set up a timer for timeout
            timer = threading.Timer(timeout, self._timeout_stop, args=(execution_id,))
            timer.daemon = True
            timer.start()

            exec(compile(code, "<submitted>", "exec"), {"__name__": "__main__"})

            timer.cancel()

            with self._lock:
                if self._execution_id == execution_id and self._status == "running":
                    self._status = "completed"
                    self._exit_code = 0
                    self._finished_at = time.time()
                    self._save_result()

        except SystemExit:
            with self._lock:
                if self._execution_id == execution_id:
                    if self._status == "running":
                        self._status = "stopped"
                    self._exit_code = 1
                    self._finished_at = time.time()
                    self._save_result()

        except Exception as e:
            import traceback
            traceback.print_exc()
            with self._lock:
                if self._execution_id == execution_id:
                    self._status = "error"
                    self._exit_code = 1
                    self._finished_at = time.time()
                    self._save_result()

        finally:
            # Tear down ZMQ proxy and clear thread-local overrides
            proxy.close()
            _rt_pkg.clear_thread_robot()
            if _rt_top is not None:
                _rt_top.clear_thread_robot()
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    def _timeout_stop(self, execution_id: str):
        """Called by the timeout timer."""
        with self._lock:
            if self._execution_id != execution_id or self._status != "running":
                return
        self.stop(reason="timeout")
