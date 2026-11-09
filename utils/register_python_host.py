"""Copy the StartPythonHost PythonPart into the Allplan user (USR) folder.

Layout, as for the official PythonParts examples:

    <Usr>\\Library\\PythonParts\\StartPythonHost.pyp      -> Library > Private > PythonParts
    <Usr>\\PythonPartsScripts\\PythonHost\\...             (whole package, incl. sandbox/)
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


DEFAULT_ALLPLAN_VERSION = "2026"
PYP_RELATIVE = Path("Library") / "PythonParts" / "StartPythonHost.pyp"
SCRIPTS_RELATIVE = Path("PythonPartsScripts") / "PythonHost"
# Where earlier versions of this script put the .pyp (not shown in the Library palette).
LEGACY_PYP_RELATIVE = Path("PythonParts") / "PythonHost" / "StartPythonHost.pyp"


def documents_dir() -> Path:
    """Real 'Documents' folder, following OneDrive / GPO redirection on Windows."""
    if sys.platform == "win32":
        import ctypes

        buffer = ctypes.create_unicode_buffer(260)
        csidl_personal = 5
        if ctypes.windll.shell32.SHGetFolderPathW(None, csidl_personal, None, 0, buffer) == 0:
            return Path(buffer.value)
    return Path.home() / "Documents"


def default_allplan_local(version: str) -> Path:
    return documents_dir() / "Nemetschek" / "Allplan" / version / "Usr" / "Local"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Register the Allplan MCP bridge PythonPart.")
    parser.add_argument("--allplan-version", default=DEFAULT_ALLPLAN_VERSION)
    parser.add_argument(
        "--allplan-local",
        type=Path,
        default=None,
        help="Allplan USR folder (Allmenu > Service > Windows Explorer > My own CAD documents).",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_root = Path(__file__).resolve().parent.parent / "python_host"
    usr = args.allplan_local or default_allplan_local(args.allplan_version)

    if not usr.is_dir():
        print(
            f"ERROR: Allplan USR folder not found: {usr}\n"
            "Start Allplan once, or find the folder via Allmenu > Service > "
            "Windows Explorer > My own CAD documents, then pass it with --allplan-local.",
            file=sys.stderr,
        )
        return 1

    source_pyp = source_root / PYP_RELATIVE
    source_scripts = source_root / SCRIPTS_RELATIVE
    target_pyp = usr / PYP_RELATIVE
    target_scripts = usr / SCRIPTS_RELATIVE
    legacy_pyp = usr / LEGACY_PYP_RELATIVE

    print(f"Allplan USR folder : {usr}")
    print(f"PythonPart         : {target_pyp}")
    print(f"Scripts            : {target_scripts}")

    if args.dry_run:
        print("Dry run: nothing copied.")
        return 0

    target_pyp.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_pyp, target_pyp)

    # Replace the whole package so files removed from the repo do not linger.
    if target_scripts.exists():
        shutil.rmtree(target_scripts)
    shutil.copytree(
        source_scripts,
        target_scripts,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    if legacy_pyp.exists():
        legacy_pyp.unlink()
        if not any(legacy_pyp.parent.iterdir()):
            legacy_pyp.parent.rmdir()
        print(f"Removed legacy copy: {legacy_pyp}")

    print("Done. In Allplan: Library > Private > PythonParts > StartPythonHost (ESC stops it).")
    print("If StartPythonHost already ran in this Allplan session, restart Allplan to reload it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
