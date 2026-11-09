from __future__ import annotations

import builtins
import contextlib
import io
from typing import Annotated, Any

import NemAll_Python_AllplanSettings as AllplanSettings
import NemAll_Python_BaseElements as AllplanBaseEle
import NemAll_Python_BaseElements as AllplanBaseElements
import NemAll_Python_BasisElements as AllplanBasisElements
import NemAll_Python_Geometry as AllplanGeo
import NemAll_Python_IFW_Input as AllplanIFW

from .const import DEFAULT_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS, allowed_builtin_names
from .guard import SandboxGuard, SandboxTimeoutError, compile_guarded
from .validator import SandboxValidator


SandboxRequest = Annotated[dict[str, Any], "Incoming execute_python request"]
SandboxResult = Annotated[dict[str, Any], "JSON-safe execution result"]


class SandboxExecutor:
    """Run sandbox code"""

    def __init__(
        self,
        coord_input: AllplanIFW.CoordinateInput,
        validator: SandboxValidator | None = None,
    ) -> None:
        self.coord_input = coord_input
        self.validator = validator or SandboxValidator()

    def execute(self, request: SandboxRequest) -> SandboxResult:
        if not isinstance(request, dict):
            raise Exception("Request body must be a JSON object.")

        code = request.get("code")
        result_expression = request.get("result_expression")

        if not isinstance(code, str) or not code.strip():
            raise Exception("'code' must be a non-empty string.")

        if result_expression is not None and not isinstance(result_expression, str):
            raise Exception("'result_expression' must be a string when provided.")

        timeout_seconds = request.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS
        ):
            raise Exception(
                f"'timeout_seconds' must be a number greater than 0 and at most {MAX_TIMEOUT_SECONDS:g}."
            )

        compiled_code = compile_guarded(self.validator.validate_exec(code), "exec")
        compiled_result = (
            compile_guarded(self.validator.validate_eval(result_expression), "eval")
            if result_expression
            else None
        )

        modules = {
            "AllplanGeo": AllplanGeo,
            "AllplanIFW": AllplanIFW,
            "AllplanSettings": AllplanSettings,
            "AllplanBaseElements": AllplanBaseElements,
            "AllplanBasisElements": AllplanBasisElements,
            "AllplanBaseEle": AllplanBaseEle,
        }
        exec_scope = {
            "__builtins__": self.safe_builtins(),
            "coord_input": self.coord_input,
            **modules,
        }
        stdout_buffer = io.StringIO()
        SandboxGuard(modules.values(), exec_scope, float(timeout_seconds)).install()

        try:
            with contextlib.redirect_stdout(stdout_buffer):
                exec(compiled_code, exec_scope, exec_scope)

                if compiled_result is not None:
                    result_value = eval(compiled_result, exec_scope, exec_scope)
                else:
                    result_value = exec_scope.get("result")
        except SandboxTimeoutError as error:
            return {
                "ok": False,
                "timed_out": True,
                "error": str(error),
                "stdout": stdout_buffer.getvalue(),
            }

        return {
            "ok": True,
            "stdout": stdout_buffer.getvalue(),
            "result": self.make_json_safe(result_value),
        }

    def safe_builtins(self) -> dict[str, Any]:
        return {
            name: getattr(builtins, name)
            for name in allowed_builtin_names
        }

    def make_json_safe(self, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value

        if isinstance(value, list):
            return [self.make_json_safe(item) for item in value]

        if isinstance(value, tuple):
            return [self.make_json_safe(item) for item in value]

        if isinstance(value, dict):
            return {
                str(key): self.make_json_safe(item)
                for key, item in value.items()
            }

        return repr(value)
