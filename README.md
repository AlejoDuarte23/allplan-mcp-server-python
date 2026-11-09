# Allplan MCP Server

FastMCP server that exposes the local Allplan Python host as MCP tools.

The existing Allplan PythonPart starts a small local HTTP host at `127.0.0.1:5679`.
This package adds a FastMCP server in front of it, so agents can call MCP tools
over Streamable HTTP at `/mcp`.

## Install (Windows, one line)

Open PowerShell (or cmd) on the machine where Allplan is installed:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/viorizz/AllPlan_MCP/main/install.ps1 | iex"
```

From a clone or an extracted ZIP, double-click `install.cmd` instead.

The installer (`install.ps1`) is idempotent; re-run it to update. It:

1. installs [uv](https://docs.astral.sh/uv/) if missing (uv also fetches a Python for the server),
2. downloads this repo to `%LOCALAPPDATA%\AllplanMCP\app` (or uses the clone it runs from),
3. runs `uv sync`,
4. copies the PythonPart into the Allplan USR folder (default
   `Documents\Nemetschek\Allplan\2026\Usr\Local`):
   - `Library\PythonParts\StartPythonHost.pyp`
   - `PythonPartsScripts\PythonHost\` (with the `sandbox` package)
5. adds an `allplan` stdio server to Claude Desktop
   (`%APPDATA%\Claude\claude_desktop_config.json`, a `.bak` is kept) and, if the
   `claude` CLI is installed, to Claude Code (user scope).

Options, as parameters of `install.ps1` or environment variables with the one-liner:

| Parameter           | Environment variable | Default                       |
| ------------------- | -------------------- | ----------------------------- |
| `-AllplanVersion`   | `ALLPLAN_VERSION`    | `2026`                        |
| `-AllplanUsr`       | `ALLPLAN_USR`        | `Documents\Nemetschek\Allplan\<version>\Usr\Local` |
| `-Ref`              | `ALLPLAN_MCP_REF`    | `main`                        |
| `-InstallDir`       | `ALLPLAN_MCP_DIR`    | `%LOCALAPPDATA%\AllplanMCP`   |
| `-SkipClaudeConfig` |                      | off                           |

If your USR folder is elsewhere, find it in Allplan via
Allmenu > Service > Windows Explorer > My own CAD documents.

Then:

1. Restart Claude Desktop (tray icon > Quit, then reopen).
2. In Allplan: Library > Private > PythonParts > `StartPythonHost`. Keep it
   running while Claude works; ESC stops it.

## Manual setup

```bash
uv sync
utils\register_python_host.cmd            # --allplan-version 2025, --allplan-local <USR folder>
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "allplan": {
      "command": "C:\\path\\to\\AllPlan_MCP\\.venv\\Scripts\\allplan-mcp.exe",
      "args": ["--transport", "stdio"]
    }
  }
}
```

Claude Code:

```bash
claude mcp add --scope user allplan -- C:\path\to\AllPlan_MCP\.venv\Scripts\allplan-mcp.exe --transport stdio
```

## Run as an HTTP server

```bash
uv run allplan-mcp                       # --transport http (default), or --transport stdio
```

By default this starts the MCP server at:

```text
http://127.0.0.1:8888/mcp
```

Useful environment variables:

```bash
ALLPLAN_HOST_URL=http://127.0.0.1:5679
MCP_TRANSPORT=http
MCP_HOST=127.0.0.1
MCP_PORT=8888
MCP_PATH=/mcp
```

## Tools

- `allplan_health`: checks whether the Allplan host is reachable.
- `get_allplan_version`: returns the running Allplan version.
- `get_all_object_names`: returns display names for elements in the current document.
- `create_cube`: creates a cube in the current document.
- `create_box`: creates a rectangular cuboid in the current document.
- `execute_python`: executes sandboxed Python inside the running Allplan host

## Skill resources

Bundled skills are also exposed through MCP resources so clients can discover and read
them through the protocol.

Simple folder layout:

```text
src/allplan_mcp/allplan_skills/
  api-reference/
    SKILL.md
    assets/
    scripts/
  geometry/
    SKILL.md
    assets/
    scripts/
  rebar/
    SKILL.md
    assets/
    scripts/
  utilities/
    SKILL.md
    assets/
    scripts/
```

Resource URIs:

- `allplan://skills`
- `allplan://skills/api-reference`
- `allplan://skills/geometry`
- `allplan://skills/rebar`
- `allplan://skills/utilities`
- `allplan://skills/{skill_name}/assets/{asset_name}`
- `allplan://skills/{skill_name}/scripts/{script_name}`

The scripts are simple templates. They are meant to guide generated code and do not
depend on cross imports between skill folders.

## Notes

- [POST execution exploration](docs/post-execution-exploration.md)

## Sandboxed exec

The bridge exposes a sandboxed Python execution path for local experiments.

- The raw Allplan bridge accepts `POST /execute-python`
- The external MCP server exposes `execute_python(...)`
- The endpoint remains bound to `127.0.0.1`

Goal: sandboxed code can use the exposed Allplan API (`AllplanGeo`, `AllplanIFW`,
`AllplanSettings`, `AllplanBaseElements` / `AllplanBaseEle`,
`AllplanBasisElements`, `coord_input`) but cannot reach the operating system
or the rest of the interpreter.

Layers (`python_host/PythonPartsScripts/PythonHost/sandbox/`):

1. Static checks (`validator.py`): no `import`, `global`, `class`, `async`,
   `yield`, `match`; no name, parameter or attribute starting with `_`; no
   introspection attributes (`gi_frame`, `f_globals`, `tb_frame`, `mro`, ...);
   no `str.format` / `format_map` (they read attributes unchecked, use f-strings);
   no `eval`, `exec`, `getattr`, `open`, ...
2. Runtime guard (`guard.py`), same principle as RestrictedPython: the code is
   rewritten so that every attribute access goes through `AttributeGuard`.
   - Reads: refused on and to frames, code objects, tracebacks, generators and
     coroutines, to modules other than the exposed ones, and to C functions of
     other modules (`os.system`, `io.open`), whatever the attribute is called.
   - Writes and `del`: only properties of objects (`point.X = 5`). Modules,
     classes and shared objects such as `coord_input` cannot be monkeypatched,
     so trusted code (this bridge, the PythonParts framework) never ends up
     calling sandbox code.
3. Builtins: only a small allowlist (`len`, `range`, `print`, `sorted`, ...).

Regression tests, including known escapes, run without Allplan:

```bash
python -m unittest discover -s tests
```

Limits, by design:

- The Allplan API itself is powerful: sandboxed code can modify or delete
  elements of the open document, like any PythonPart.
- No timeout: the code runs in the Allplan UI thread, an infinite loop or a
  huge allocation freezes Allplan (save your work).
- An in-process Python sandbox has no hard isolation. These layers close the
  known escape techniques, not unknown ones: do not expose `execute_python`
  through ngrok or a shared agent setup, and keep reviewing what Claude runs.

The Allplan host rejects requests carrying an `Origin` header or a `Host` other
than `127.0.0.1:5679` / `localhost:5679`, so web pages cannot drive it
(CSRF / DNS rebinding).
