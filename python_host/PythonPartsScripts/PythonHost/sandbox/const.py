from __future__ import annotations

from typing import Annotated


BuiltinName = Annotated[str, "Sandbox builtin name"]
AttributeName = Annotated[str, "Sandbox attribute name"]

# Attributes that reach interpreter internals (generator/coroutine frames, frame
# globals, tracebacks), or that read attributes without going through the guard
# (str.format / format_map: "{0.gi_frame}".format(gen)).
blocked_attribute_names: frozenset[AttributeName] = frozenset(
    {
        "ag_await",
        "ag_code",
        "ag_frame",
        "cr_await",
        "cr_code",
        "cr_frame",
        "cr_origin",
        "f_back",
        "f_builtins",
        "f_code",
        "f_generator",
        "f_globals",
        "f_locals",
        "f_trace",
        "format",
        "format_map",
        "gi_code",
        "gi_frame",
        "gi_yieldfrom",
        "mro",
        "tb_frame",
        "tb_next",
    }
)

blocked_builtin_names: frozenset[BuiltinName] = frozenset(
    {
        "__import__",
        "breakpoint",
        "compile",
        "delattr",
        "dir",
        "eval",
        "exec",
        "getattr",
        "globals",
        "hasattr",
        "input",
        "locals",
        "open",
        "setattr",
        "vars",
    }
)

allowed_builtin_names: frozenset[BuiltinName] = frozenset(
    {
        "abs",
        "all",
        "any",
        "bool",
        "dict",
        "enumerate",
        "Exception",
        "filter",
        "float",
        "int",
        "isinstance",
        "len",
        "list",
        "map",
        "max",
        "min",
        "print",
        "range",
        "repr",
        "reversed",
        "round",
        "set",
        "sorted",
        "str",
        "sum",
        "tuple",
        "ValueError",
        "zip",
    }
)
