from __future__ import annotations

import ast
from typing import Annotated, Literal

from .const import blocked_attribute_names, blocked_builtin_names


SandboxMode = Annotated[Literal["exec", "eval"], "AST parse mode"]
PythonSource = Annotated[str, "Sandbox source text"]


class SandboxValidationError(Exception):
    """Sandbox validation error"""


def is_blocked_attribute_name(name: str) -> bool:
    """Private, dunder and introspection attributes"""

    return name.startswith("_") or name in blocked_attribute_names


def check_identifier(kind: str, name: str | None) -> None:
    """Names starting with '_' are reserved (dunders, the attribute guard)"""

    if name is not None and name.startswith("_"):
        raise SandboxValidationError(f"{kind} '{name}' is not allowed in execute_python.")


class SandboxAstValidator(ast.NodeVisitor):
    """Block unsafe syntax"""

    def visit_Import(self, node: ast.Import) -> None:
        raise SandboxValidationError("import statements are not allowed in execute_python.")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        raise SandboxValidationError("import statements are not allowed in execute_python.")

    def visit_Global(self, node: ast.Global) -> None:
        raise SandboxValidationError("global statements are not allowed in execute_python.")

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        raise SandboxValidationError("nonlocal statements are not allowed in execute_python.")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        raise SandboxValidationError("class definitions are not allowed in execute_python.")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        raise SandboxValidationError("async functions are not allowed in execute_python.")

    def visit_Await(self, node: ast.Await) -> None:
        raise SandboxValidationError("await is not allowed in execute_python.")

    def visit_Yield(self, node: ast.Yield) -> None:
        raise SandboxValidationError("yield is not allowed in execute_python.")

    def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
        raise SandboxValidationError("yield from is not allowed in execute_python.")

    def visit_Match(self, node: ast.Match) -> None:
        # Class patterns read attributes inside the VM, bypassing the guard:
        # case object(gi_frame=frame)
        raise SandboxValidationError("match statements are not allowed in execute_python.")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if is_blocked_attribute_name(node.attr):
            if node.attr in ("format", "format_map"):
                raise SandboxValidationError(
                    f"'{node.attr}' is not allowed in execute_python (it reads attributes "
                    "unchecked); use f-strings instead."
                )
            raise SandboxValidationError(
                f"attribute '{node.attr}' is not allowed in execute_python."
            )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        check_identifier("name", node.id)
        if isinstance(node.ctx, ast.Load) and node.id in blocked_builtin_names:
            raise SandboxValidationError(
                f"builtin '{node.id}' is not allowed in execute_python."
            )
        self.generic_visit(node)

    # Binding sites that are not ast.Name: a parameter named like the guard
    # would shadow it inside the function.
    def visit_arg(self, node: ast.arg) -> None:
        check_identifier("parameter", node.arg)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        check_identifier("function name", node.name)
        if node.decorator_list:
            # The decorator call is implicit, it would bypass the call guard.
            raise SandboxValidationError("decorators are not allowed in execute_python.")
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        check_identifier("exception name", node.name)
        self.generic_visit(node)


class SandboxValidator:
    """Validate sandbox code"""

    def validate_exec(self, source: PythonSource) -> ast.Module:
        return self.validate_python_code(source, "exec")

    def validate_eval(self, source: PythonSource) -> ast.Expression:
        return self.validate_python_code(source, "eval")

    def validate_python_code(self, source: PythonSource, mode: SandboxMode) -> ast.AST:
        try:
            tree = ast.parse(source, filename="<sandbox>", mode=mode)
        except SyntaxError as error:
            raise SandboxValidationError(str(error)) from error

        SandboxAstValidator().visit(tree)
        return tree
