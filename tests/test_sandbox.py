"""Sandbox tests, runnable without Allplan: python -m unittest discover -s tests"""

from __future__ import annotations

import builtins
import os
import sys
import types
import unittest
from pathlib import Path


ALLPLAN_MODULES = (
    "NemAll_Python_AllplanSettings",
    "NemAll_Python_BaseElements",
    "NemAll_Python_BasisElements",
    "NemAll_Python_Geometry",
    "NemAll_Python_IFW_Input",
)


class Point3D:
    """Stand-in for an Allplan API class: Boost.Python exposes fields as properties"""

    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> None:
        self._coords = [x, y, z]

    X = property(lambda self: self._coords[0], lambda self, v: self._coords.__setitem__(0, v))
    Y = property(lambda self: self._coords[1], lambda self, v: self._coords.__setitem__(1, v))

    def Length(self) -> float:
        return sum(c * c for c in self._coords) ** 0.5


for module_name in ALLPLAN_MODULES:
    sys.modules.setdefault(module_name, types.ModuleType(module_name))
geometry_module = sys.modules["NemAll_Python_Geometry"]
geometry_module.Point3D = Point3D

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_host" / "PythonPartsScripts" / "PythonHost"))

from unittest import mock  # noqa: E402

from sandbox import SandboxExecutor, SandboxValidationError  # noqa: E402


class CoordInput:
    def GetInputViewDocument(self) -> str:
        return "document"


def run(code: str, result_expression: str | None = None) -> dict:
    request = {"code": code}
    if result_expression is not None:
        request["result_expression"] = result_expression
    return SandboxExecutor(CoordInput()).execute(request)


class AllowedCodeTest(unittest.TestCase):
    def test_result_variable(self) -> None:
        self.assertEqual(run("result = sum(range(5))")["result"], 10)

    def test_result_expression_and_stdout(self) -> None:
        response = run("x = 2\nprint('hello')", result_expression="x * 21")
        self.assertEqual(response["result"], 42)
        self.assertEqual(response["stdout"], "hello\n")

    def test_functions_comprehensions_and_exceptions(self) -> None:
        code = (
            "def area(w, h):\n"
            "    return w * h\n"
            "squares = [area(n, n) for n in range(4)]\n"
            "try:\n"
            "    1 / 0\n"
            "except Exception as error:\n"
            "    message = str(error)\n"
            "result = {'squares': squares, 'message': message, 'gen': list(n for n in range(3))}\n"
        )
        self.assertEqual(
            run(code)["result"],
            {"squares": [0, 1, 4, 9], "message": "division by zero", "gen": [0, 1, 2]},
        )

    def test_attributes_and_methods(self) -> None:
        code = (
            "p = AllplanGeo.Point3D(1, 2, 3)\n"
            "p.X += 10\n"
            "q = AllplanGeo.Point3D()\n"
            "q.X, q.Y = 3, 4\n"
            "names = []\n"
            "names.append(', '.join(['a', 'b']).upper())\n"
            "result = [p.X, p.Y, q.Length(), names, f'{3.14159:.2f}', coord_input.GetInputViewDocument()]\n"
        )
        self.assertEqual(run(code)["result"], [11, 2, 5.0, ["A, B"], "3.14", "document"])


class EscapeTest(unittest.TestCase):
    def assert_blocked(self, code: str, result_expression: str | None = None) -> None:
        with self.assertRaises(SandboxValidationError):
            run(code, result_expression)

    def test_generator_frame_escape(self) -> None:
        # Reached the executor module globals, then builtins.eval / __import__.
        self.assert_blocked(
            "g = None\n"
            "g = (g.gi_frame.f_back.f_back.f_globals for x in [1])\n"
            "result = list(g)[0]['builtins'].eval('1')\n"
        )

    def test_generator_attributes_blocked_at_runtime(self) -> None:
        self.assert_blocked("g = (x for x in [1])\nresult = g.send")

    def test_str_format_traversal(self) -> None:
        self.assert_blocked("g = (x for x in [1])\nresult = '{0.gi_frame}'.format(g)")
        self.assert_blocked("result = str.format('{0}', 1)")
        self.assert_blocked("result = '{x}'.format_map({'x': 1})")

    def test_fstring_attribute(self) -> None:
        self.assert_blocked("g = (x for x in [1])\nresult = f'{g.gi_frame}'")

    def test_match_class_pattern(self) -> None:
        self.assert_blocked(
            "g = (x for x in [1])\n"
            "match g:\n"
            "    case object(gi_frame=frame):\n"
            "        result = frame\n"
        )

    def test_dunder_and_mro(self) -> None:
        self.assert_blocked("result = ().__class__")
        self.assert_blocked("result = Exception.mro()")

    def test_guard_cannot_be_named_or_shadowed(self) -> None:
        self.assert_blocked("result = _sandbox_getattr_")
        self.assert_blocked("def f(_sandbox_getattr_=None):\n    return 1\n")
        self.assert_blocked("try:\n    pass\nexcept Exception as _sandbox_getattr_:\n    pass\n")

    def test_imports_and_dangerous_builtins(self) -> None:
        self.assert_blocked("import os")
        self.assert_blocked("result = eval('1')")
        self.assert_blocked("result = getattr(1, 'real')")
        self.assert_blocked("result = 1", result_expression="__import__('os')")

    def test_augmented_assignment_on_blocked_attribute(self) -> None:
        self.assert_blocked("g = (x for x in [1])\ng.gi_frame += 1")

    def test_runtime_guard_alone_stops_frame_escape(self) -> None:
        # Defense in depth: without the static name list, types are still checked.
        with mock.patch("sandbox.validator.blocked_attribute_names", frozenset()):
            self.assert_blocked(
                "g = None\n"
                "g = (g.gi_frame.f_back.f_globals for x in [1])\n"
                "result = list(g)\n"
            )


class MonkeypatchTest(unittest.TestCase):
    """Shared objects must not be rewired to call sandbox code later"""

    def test_shared_objects_are_read_only(self) -> None:
        for code in (
            "AllplanGeo.Point3D = print",
            "del AllplanGeo.Point3D",
            "AllplanGeo.Point3D.Length = print",
            "coord_input.GetInputViewDocument = print",
            "coord_input.planted = 1",
            "coord_input.planted, x = 1, 2",
            "for coord_input.planted in [1]:\n    pass",
            "def f():\n    return 1\nf.planted = 1",
        ):
            with self.subTest(code=code), self.assertRaises(SandboxValidationError):
                run(code)
        self.assertIs(geometry_module.Point3D, Point3D)
        self.assertFalse(hasattr(CoordInput, "planted"))


class LeakyModuleTest(unittest.TestCase):
    """An exposed module that happens to hold OS-level objects"""

    def setUp(self) -> None:
        geometry_module.os = os
        geometry_module.getcwd = os.getcwd
        geometry_module.leaked_open = builtins.open

    def tearDown(self) -> None:
        for name in ("os", "getcwd", "leaked_open"):
            delattr(geometry_module, name)

    def test_foreign_module_and_functions_blocked(self) -> None:
        for code in (
            "result = AllplanGeo.os.getcwd()",
            "result = AllplanGeo.getcwd()",
            "result = AllplanGeo.leaked_open('x.txt', 'w')",
        ):
            with self.subTest(code=code), self.assertRaises(SandboxValidationError):
                run(code)


if __name__ == "__main__":
    unittest.main()
