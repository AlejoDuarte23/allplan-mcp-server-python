@echo off
setlocal

set "SCRIPT_DIR=%~dp0"

where uv >nul 2>nul
if %errorlevel%==0 (
    uv run --no-project python "%SCRIPT_DIR%register_python_host.py" %*
) else (
    python "%SCRIPT_DIR%register_python_host.py" %*
)

if errorlevel 1 (
    echo Registration failed.
    exit /b %errorlevel%
)
