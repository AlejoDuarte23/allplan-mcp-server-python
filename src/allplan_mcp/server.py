"""MCP server exposing the Allplan Python host."""

from __future__ import annotations

import argparse
import os
from typing import Annotated, Any

from fastmcp import FastMCP

from allplan_mcp.allplan_client import AllplanHostClient
from allplan_mcp.skills import SkillsManager


DEFAULT_ALLPLAN_HOST_URL = "http://127.0.0.1:5679"
DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 8888
DEFAULT_MCP_PATH = "/mcp"
DEFAULT_MCP_TRANSPORT = "http"
# Mirrors python_host/.../sandbox/const.py
DEFAULT_EXEC_TIMEOUT_SECONDS = 20.0
MAX_EXEC_TIMEOUT_SECONDS = 300.0
EXEC_HTTP_TIMEOUT_MARGIN_SECONDS = 15.0

mcp = FastMCP("Allplan MCP Server")
skills_manager = SkillsManager()


def _allplan_client(min_timeout: float = 0.0) -> AllplanHostClient:
    return AllplanHostClient(
        base_url=os.getenv("ALLPLAN_HOST_URL", DEFAULT_ALLPLAN_HOST_URL),
        timeout=max(float(os.getenv("ALLPLAN_HOST_TIMEOUT", "30")), min_timeout),
    )


@mcp.resource(
    "allplan://skills",
    name="allplan-skills",
    title="ALLPLAN skills index",
    description="Index of bundled ALLPLAN skills and sample scripts",
    mime_type="text/markdown",
)
def allplan_skills_index() -> str:
    """Read the skills index"""

    return skills_manager.index_text()


@mcp.resource(
    "allplan://skills/{skill_name}",
    name="allplan-skill",
    title="ALLPLAN skill",
    description="Read one bundled ALLPLAN skill",
    mime_type="text/markdown",
)
def allplan_skill(skill_name: Annotated[str, "Skill folder name"]) -> str:
    """Read one skill"""

    return skills_manager.skill_text(skill_name)


@mcp.resource(
    "allplan://skills/{skill_name}/assets/{asset_name}",
    name="allplan-skill-asset",
    title="ALLPLAN skill asset",
    description="Read one bundled ALLPLAN asset note",
    mime_type="text/markdown",
)
def allplan_skill_asset(
    skill_name: Annotated[str, "Skill folder name"],
    asset_name: Annotated[str, "Asset file name"],
) -> str:
    """Read one asset"""

    return skills_manager.asset_text(skill_name, asset_name)


@mcp.resource(
    "allplan://skills/{skill_name}/scripts/{script_name}",
    name="allplan-skill-script",
    title="ALLPLAN skill script",
    description="Read one bundled ALLPLAN sample script",
    mime_type="text/x-python",
)
def allplan_skill_script(
    skill_name: Annotated[str, "Skill folder name"],
    script_name: Annotated[str, "Script file name"],
) -> str:
    """Read one sample script"""

    return skills_manager.script_text(skill_name, script_name)


@mcp.tool
def allplan_health() -> dict[str, Any]:
    """Check that the Allplan Python host is reachable."""

    response = _allplan_client().post("/get-allplan-version")
    return {
        "ok": True,
        "allplan_version": response.get("version"),
        "allplan_host_url": os.getenv("ALLPLAN_HOST_URL", DEFAULT_ALLPLAN_HOST_URL),
    }


@mcp.tool
def get_allplan_version() -> str:
    """Get the version of the running Allplan instance."""

    response = _allplan_client().post("/get-allplan-version")
    return str(response["version"])


@mcp.tool
def get_all_object_names() -> list[str]:
    """Get display names for all elements in the current Allplan document."""

    response = _allplan_client().post("/get-all-object-names")
    names = response.get("names", [])
    if not isinstance(names, list):
        raise ValueError(f"Unexpected Allplan response for names: {response!r}")

    return [str(name) for name in names]


@mcp.tool
def create_cube(size: float) -> dict[str, Any]:
    """Create a cube in the current Allplan document."""

    if size <= 0:
        raise ValueError("size must be greater than zero.")

    _allplan_client().post(
        "/create-box",
        {
            "length": size,
            "width": size,
            "height": size,
        },
    )
    return {
        "created": True,
        "type": "cube",
        "dimensions": {
            "length": size,
            "width": size,
            "height": size,
        },
    }


@mcp.tool
def create_box(length: float, width: float, height: float) -> dict[str, Any]:
    """Create a cuboid in the current Allplan document."""

    if length <= 0 or width <= 0 or height <= 0:
        raise ValueError("length, width, and height must be greater than zero.")

    _allplan_client().post(
        "/create-box",
        {
            "length": length,
            "width": width,
            "height": height,
        },
    )
    return {
        "created": True,
        "type": "cuboid",
        "dimensions": {
            "length": length,
            "width": width,
            "height": height,
        },
    }


@mcp.tool
def execute_python(
    code: str,
    result_expression: str | None = None,
    timeout_seconds: float = DEFAULT_EXEC_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Execute sandboxed Python inside the running Allplan (UI thread).

    Time limit: timeout_seconds (default 20, max 300), checked at every loop
    iteration and call. When exceeded the response is
    {"ok": false, "timed_out": true, "error": ..., "stdout": ...}; changes made
    before the interruption stay in the document. Allplan is frozen while the
    code runs, so prefer short, bounded scripts.

    Available names: AllplanGeo, AllplanIFW, AllplanSettings, AllplanBaseElements
    (alias AllplanBaseEle), AllplanBasisElements, coord_input, and a small set of
    builtins (len, range, print, sorted, sum, min, max, list, dict, str, ...).
    Return data by assigning `result` (JSON-safe values; other objects come back as
    repr) or by passing `result_expression`; print() output is returned as stdout.

    Not allowed: import, class, async, yield, match, global, decorators; names or
    attributes starting with '_'; str.format / format_map (use f-strings); eval,
    exec, getattr, open. Attribute writes only work on properties (point.X = 5),
    not on modules, classes or coord_input. Objects from outside the Allplan API
    are refused wherever they are used.
    """

    if not code.strip():
        raise ValueError("code must be a non-empty string.")
    if not 0 < timeout_seconds <= MAX_EXEC_TIMEOUT_SECONDS:
        raise ValueError(f"timeout_seconds must be in ]0, {MAX_EXEC_TIMEOUT_SECONDS:g}].")

    payload: dict[str, Any] = {"code": code, "timeout_seconds": timeout_seconds}
    if result_expression is not None:
        payload["result_expression"] = result_expression

    # Allplan answers once the sandbox has stopped: wait longer than its limit.
    client = _allplan_client(min_timeout=timeout_seconds + EXEC_HTTP_TIMEOUT_MARGIN_SECONDS)
    return client.post("/execute-python", payload)


def main() -> None:
    parser = argparse.ArgumentParser(prog="allplan-mcp", description=__doc__)
    parser.add_argument(
        "--transport",
        choices=("http", "stdio"),
        default=os.getenv("MCP_TRANSPORT", DEFAULT_MCP_TRANSPORT),
        help="stdio for Claude Desktop / Claude Code, http for Streamable HTTP clients.",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        # stdout carries the MCP protocol: no banner.
        mcp.run(transport="stdio", show_banner=False)
        return

    host = os.getenv("MCP_HOST", DEFAULT_MCP_HOST)
    port = int(os.getenv("MCP_PORT", str(DEFAULT_MCP_PORT)))
    path = os.getenv("MCP_PATH", DEFAULT_MCP_PATH)

    mcp.run(transport="http", host=host, port=port, path=path)


if __name__ == "__main__":
    main()
