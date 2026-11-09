"""Runtime guard.

Static checks only see names written in the source. The validated code is
therefore rewritten so that values are checked where they are *used*, whatever
channel brought them in (attribute, subscript, iteration, with, call result):

- attribute reads   obj.name         -> _sandbox_getattr_(obj, "name")
- calls             f(a, k=b)        -> _sandbox_call_(f, a, k=b)   (callee and arguments)
- subscripts        obj[k]           -> _sandbox_check_(obj)[k]
- iteration         for x in obj     -> for x in _sandbox_check_(obj)   (also comprehensions,
                    a, b = obj          unpacking, with, f-string values)
- attribute writes  obj.name = v     -> _sandbox_setattr_target_(obj, "name").name = v
                    obj.name += v    -> _sandbox_augattr_(obj, "name", "+=", v)

A value is refused (SandboxGuard.is_forbidden_value) when it is a frame, code
object or traceback, a module other than the exposed ones, a Python function the
sandbox did not define, a C function bound to a forbidden object (os.system,
io.open, builtins.eval), or a class / instance from a module other than
builtins, Boost.Python and NemAll_Python_* (file objects, Popen, os.environ...).

Writes only reach properties: modules, classes and shared objects such as
coord_input are used by trusted code (this bridge, the PythonParts framework),
monkeypatching them would make trusted code call sandbox code later.
"""

from __future__ import annotations

import ast
import operator
import types
from collections.abc import Iterable
from typing import Any, Callable

from .validator import SandboxMode, SandboxValidationError, is_blocked_attribute_name


# Start with '_' so sandbox code can neither reference nor shadow them.
GUARD_GETATTR_NAME = "_sandbox_getattr_"
GUARD_SETATTR_TARGET_NAME = "_sandbox_setattr_target_"
GUARD_AUGATTR_NAME = "_sandbox_augattr_"
GUARD_CALL_NAME = "_sandbox_call_"
GUARD_CHECK_NAME = "_sandbox_check_"

# No attribute of these may be read (gi_frame, f_back, tb_frame, ...).
introspection_types: tuple[type, ...] = (
    types.FrameType,
    types.CodeType,
    types.TracebackType,
    types.GeneratorType,
    types.CoroutineType,
    types.AsyncGeneratorType,
)

# Never usable as values. Generators are fine as values (list(x for x in ...)).
forbidden_value_types: tuple[type, ...] = (
    types.FrameType,
    types.CodeType,
    types.TracebackType,
)

# Classes whose instances and class objects may be used.
allowed_class_modules = frozenset({"builtins", "Boost.Python"})
allowed_class_module_prefix = "NemAll_Python"

inplace_operators: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.iadd,
    ast.BitAnd: operator.iand,
    ast.BitOr: operator.ior,
    ast.BitXor: operator.ixor,
    ast.Div: operator.itruediv,
    ast.FloorDiv: operator.ifloordiv,
    ast.LShift: operator.ilshift,
    ast.MatMult: operator.imatmul,
    ast.Mod: operator.imod,
    ast.Mult: operator.imul,
    ast.Pow: operator.ipow,
    ast.RShift: operator.irshift,
    ast.Sub: operator.isub,
}
inplace_operators_by_name = {op.__name__: func for op, func in inplace_operators.items()}


class SandboxGuard:
    """Check values where sandbox code uses them"""

    def __init__(
        self,
        allowed_modules: Iterable[types.ModuleType],
        sandbox_globals: dict[str, Any],
    ) -> None:
        self.allowed_modules = frozenset(allowed_modules)
        # Functions defined by the sandbox code share its globals.
        self.sandbox_globals = sandbox_globals
        self.safe_builtin_ids = frozenset(id(value) for value in sandbox_globals["__builtins__"].values())

    def install(self) -> None:
        """Expose the guard functions to the rewritten code"""

        self.sandbox_globals.update(
            {
                GUARD_GETATTR_NAME: self.getattr,
                GUARD_SETATTR_TARGET_NAME: self.setattr_target,
                GUARD_AUGATTR_NAME: self.augattr,
                GUARD_CALL_NAME: self.call,
                GUARD_CHECK_NAME: self.check,
            }
        )

    # Policy

    def is_forbidden_value(self, value: Any) -> bool:
        if isinstance(value, forbidden_value_types):
            return True

        if isinstance(value, types.ModuleType):
            return value not in self.allowed_modules

        if isinstance(value, BaseException) or (
            isinstance(value, type) and issubclass(value, BaseException)
        ):
            return False

        if isinstance(value, types.BuiltinFunctionType):
            # print, len, ... are bound to the builtins module but explicitly allowed
            if id(value) in self.safe_builtin_ids:
                return False
            owner = value.__self__
            return owner is not None and self.is_forbidden_value(owner)

        if isinstance(value, types.FunctionType):
            # Defined by the sandbox code, or Python helpers of the Allplan API
            return value.__globals__ is not self.sandbox_globals and not is_allplan_module(
                value.__module__
            )

        if isinstance(value, types.MethodType):
            return self.is_forbidden_value(value.__func__) or self.is_forbidden_value(value.__self__)

        return not self.is_allowed_class(value if isinstance(value, type) else type(value))

    @staticmethod
    def is_allowed_class(cls: type) -> bool:
        module = getattr(cls, "__module__", None)
        if module in allowed_class_modules or is_allplan_module(module):
            return True
        # Classes created by Boost.Python (Allplan API) have the Boost.Python.class metaclass.
        return type(cls).__module__ == "Boost.Python"

    def check(self, value: Any) -> Any:
        if self.is_forbidden_value(value):
            raise SandboxValidationError(
                f"{describe(value)} objects are not allowed in execute_python."
            )
        return value

    # Rewritten operations

    def getattr(self, obj: Any, name: str) -> Any:
        if is_blocked_attribute_name(name):
            raise SandboxValidationError(f"attribute '{name}' is not allowed in execute_python.")

        if isinstance(obj, introspection_types):
            raise SandboxValidationError(
                f"attributes of {type(obj).__name__} objects are not allowed in execute_python."
            )
        self.check(obj)

        value = getattr(obj, name)

        if self.is_forbidden_value(value):
            raise SandboxValidationError(
                f"attribute '{name}' leads to a {describe(value)} object, "
                "which is not allowed in execute_python."
            )
        return value

    def call(self, func: Any, /, *args: Any, **kwargs: Any) -> Any:
        if self.is_forbidden_value(func):
            raise SandboxValidationError(
                f"calling this {describe(func)} object is not allowed in execute_python."
            )
        # Higher-order builtins (map, sorted(key=...)) call their arguments.
        for value in (*args, *kwargs.values()):
            self.check(value)
        return self.check(func(*args, **kwargs))

    def setattr_target(self, obj: Any, name: str) -> Any:
        """Return obj if `obj.name = ...` / `del obj.name` is allowed"""

        if is_blocked_attribute_name(name):
            raise SandboxValidationError(f"attribute '{name}' is not allowed in execute_python.")

        if isinstance(obj, (types.ModuleType, type, *introspection_types)):
            raise SandboxValidationError(
                f"setting or deleting attributes of {type(obj).__name__} objects "
                "is not allowed in execute_python."
            )
        self.check(obj)

        # Data descriptor (property) on the type: goes through the API setter and
        # can not shadow a method or plant a new attribute.
        descriptor = getattr(type(obj), name, None)
        if not hasattr(type(descriptor), "__set__"):
            raise SandboxValidationError(
                f"attribute '{name}' can not be set in execute_python: "
                "only properties of objects are writable."
            )
        return obj

    def augattr(self, obj: Any, name: str, op_name: str, value: Any) -> None:
        """obj.name <op>= value, with the read guarded too"""

        target = self.setattr_target(obj, name)
        current = self.getattr(target, name)
        setattr(target, name, inplace_operators_by_name[op_name](current, self.check(value)))


class GuardTransformer(ast.NodeTransformer):
    """Rewrite validated code so that every use of a value goes through the guard"""

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        self.generic_visit(node)

        if isinstance(node.ctx, ast.Load):
            return ast.copy_location(guard_call(GUARD_GETATTR_NAME, node.value, node.attr), node)

        # Store / Del keep their shape (valid in tuple unpacking, for, with):
        node.value = ast.copy_location(
            guard_call(GUARD_SETATTR_TARGET_NAME, node.value, node.attr), node.value
        )
        return node

    def visit_AugAssign(self, node: ast.AugAssign) -> ast.AST:
        if not isinstance(node.target, ast.Attribute):
            return self.generic_visit(node)

        call = ast.Call(
            func=ast.Name(id=GUARD_AUGATTR_NAME, ctx=ast.Load()),
            args=[
                self.visit(node.target.value),
                ast.Constant(value=node.target.attr),
                ast.Constant(value=type(node.op).__name__),
                self.visit(node.value),
            ],
            keywords=[],
        )
        return ast.copy_location(ast.Expr(value=call), node)

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        call = ast.Call(
            func=ast.Name(id=GUARD_CALL_NAME, ctx=ast.Load()),
            args=[node.func, *node.args],
            keywords=node.keywords,
        )
        return ast.copy_location(call, node)

    def visit_Subscript(self, node: ast.Subscript) -> ast.AST:
        self.generic_visit(node)
        node.value = checked(node.value)
        return node

    def visit_For(self, node: ast.For) -> ast.AST:
        self.generic_visit(node)
        node.iter = checked(node.iter)
        return node

    def visit_comprehension(self, node: ast.comprehension) -> ast.AST:
        self.generic_visit(node)
        node.iter = checked(node.iter)
        return node

    def visit_With(self, node: ast.With) -> ast.AST:
        self.generic_visit(node)
        for item in node.items:
            item.context_expr = checked(item.context_expr)
        return node

    def visit_Assign(self, node: ast.Assign) -> ast.AST:
        self.generic_visit(node)
        if any(isinstance(target, (ast.Tuple, ast.List)) for target in node.targets):
            node.value = checked(node.value)
        return node

    def visit_FormattedValue(self, node: ast.FormattedValue) -> ast.AST:
        self.generic_visit(node)
        node.value = checked(node.value)
        return node


def is_allplan_module(module_name: object) -> bool:
    return isinstance(module_name, str) and module_name.startswith(allowed_class_module_prefix)


def describe(value: Any) -> str:
    """Type and module, so a refused Allplan type is easy to report"""

    cls = type(value)
    return f"{getattr(cls, '__module__', '?')}.{cls.__qualname__}"


def guard_call(guard_name: str, obj: ast.expr, attr: str) -> ast.Call:
    return ast.Call(
        func=ast.Name(id=guard_name, ctx=ast.Load()),
        args=[obj, ast.Constant(value=attr)],
        keywords=[],
    )


def checked(expr: ast.expr) -> ast.expr:
    call = ast.Call(func=ast.Name(id=GUARD_CHECK_NAME, ctx=ast.Load()), args=[expr], keywords=[])
    return ast.copy_location(call, expr)


def compile_guarded(tree: ast.AST, mode: SandboxMode) -> types.CodeType:
    """Compile a validated tree with every value use guarded"""

    guarded_tree = ast.fix_missing_locations(GuardTransformer().visit(tree))
    return compile(guarded_tree, "<sandbox>", mode)
