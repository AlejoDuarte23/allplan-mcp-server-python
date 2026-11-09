"""Runtime attribute guard.

Static checks only see names written in the source. Every attribute access is
therefore routed through AttributeGuard at runtime:

- reads become `_sandbox_getattr_(obj, "name")`, which also checks the type of
  the object and of the value, so introspection objects (frames, code,
  tracebacks, generator internals) and foreign modules can not be reached
  whatever the attribute is called;
- writes and deletes become `_sandbox_setattr_target_(obj, "name").name = ...`,
  which only lets properties of objects through. Modules, classes and shared
  instances such as coord_input are used by trusted code (this bridge, the
  PythonParts framework): monkeypatching them would make trusted code call
  sandbox code later.
"""

from __future__ import annotations

import ast
import types
from collections.abc import Iterable
from typing import Any

from .validator import SandboxMode, SandboxValidationError, is_blocked_attribute_name


# Start with '_' so sandbox code can neither reference nor shadow them.
GUARD_GETATTR_NAME = "_sandbox_getattr_"
GUARD_SETATTR_TARGET_NAME = "_sandbox_setattr_target_"

introspection_types: tuple[type, ...] = (
    types.FrameType,
    types.CodeType,
    types.TracebackType,
    types.GeneratorType,
    types.CoroutineType,
    types.AsyncGeneratorType,
)


class AttributeGuard:
    """Check attribute reads at runtime"""

    def __init__(self, allowed_modules: Iterable[types.ModuleType]) -> None:
        self.allowed_modules = frozenset(allowed_modules)

    def getattr(self, obj: Any, name: str) -> Any:
        if is_blocked_attribute_name(name):
            raise SandboxValidationError(f"attribute '{name}' is not allowed in execute_python.")

        if isinstance(obj, introspection_types):
            raise SandboxValidationError(
                f"attributes of {type(obj).__name__} objects are not allowed in execute_python."
            )

        value = getattr(obj, name)

        if self.is_forbidden_value(value):
            raise SandboxValidationError(
                f"attribute '{name}' leads to a {type(value).__name__} object, "
                "which is not allowed in execute_python."
            )
        return value

    def setattr_target(self, obj: Any, name: str) -> Any:
        """Return obj if `obj.name = ...` / `del obj.name` is allowed"""

        if is_blocked_attribute_name(name):
            raise SandboxValidationError(f"attribute '{name}' is not allowed in execute_python.")

        if isinstance(obj, (types.ModuleType, type, *introspection_types)):
            raise SandboxValidationError(
                f"setting or deleting attributes of {type(obj).__name__} objects "
                "is not allowed in execute_python."
            )

        # Data descriptor (property) on the type: goes through the API setter and
        # can not shadow a method or plant a new attribute.
        descriptor = getattr(type(obj), name, None)
        if not hasattr(type(descriptor), "__set__"):
            raise SandboxValidationError(
                f"attribute '{name}' can not be set in execute_python: "
                "only properties of objects are writable."
            )
        return obj

    def is_forbidden_value(self, value: Any) -> bool:
        if isinstance(value, introspection_types):
            return True

        # e.g. a module that imported os, or os itself
        if isinstance(value, types.ModuleType):
            return value not in self.allowed_modules

        # C functions of a foreign module re-exported somewhere (os.system, io.open, ...)
        if isinstance(value, types.BuiltinFunctionType):
            owner = getattr(value, "__self__", None)
            return isinstance(owner, types.ModuleType) and owner not in self.allowed_modules

        return False


class AttributeGuardTransformer(ast.NodeTransformer):
    """Route attribute reads, writes and deletes through the guard"""

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        self.generic_visit(node)

        if isinstance(node.ctx, ast.Load):
            # obj.name -> _sandbox_getattr_(obj, "name")
            return ast.copy_location(guard_call(GUARD_GETATTR_NAME, node.value, node.attr), node)

        # Store / Del keep their shape (valid in tuple unpacking, for, with, +=):
        # obj.name = v -> _sandbox_setattr_target_(obj, "name").name = v
        node.value = ast.copy_location(
            guard_call(GUARD_SETATTR_TARGET_NAME, node.value, node.attr), node.value
        )
        return node


def guard_call(guard_name: str, obj: ast.expr, attr: str) -> ast.Call:
    return ast.Call(
        func=ast.Name(id=guard_name, ctx=ast.Load()),
        args=[obj, ast.Constant(value=attr)],
        keywords=[],
    )


def compile_guarded(tree: ast.AST, mode: SandboxMode) -> types.CodeType:
    """Compile a validated tree with guarded attribute reads"""

    guarded_tree = ast.fix_missing_locations(AttributeGuardTransformer().visit(tree))
    return compile(guarded_tree, "<sandbox>", mode)
