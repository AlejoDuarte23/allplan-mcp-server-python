<#
.SYNOPSIS
    One-shot installer for the Allplan MCP server (Windows).

.DESCRIPTION
    1. Installs uv if missing (uv also downloads a Python for the MCP server).
    2. Gets the code: this folder when run from a clone, else a GitHub download.
    3. Creates the Python environment (uv sync).
    4. Copies the StartPythonHost PythonPart into the Allplan USR folder.
    5. Registers the server in Claude Desktop, and in Claude Code if installed.

    Re-running it updates everything in place.

    One line (PowerShell or cmd):
        powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/viorizz/AllPlan_MCP/main/install.ps1 | iex"

    Options: parameters, or environment variables when piped through iex.
        -AllplanVersion    ALLPLAN_VERSION    default 2026
        -AllplanUsr        ALLPLAN_USR        Allplan USR folder when not the default
                                              (Allmenu > Service > Windows Explorer > My own CAD documents)
        -Ref               ALLPLAN_MCP_REF    branch or tag to download, default main
        -InstallDir        ALLPLAN_MCP_DIR    default %LOCALAPPDATA%\AllplanMCP
        -SkipClaudeConfig                     do not touch Claude Desktop / Claude Code
#>
param(
    [string]$AllplanVersion = $(if ($env:ALLPLAN_VERSION) { $env:ALLPLAN_VERSION } else { "2026" }),
    [string]$AllplanUsr = $env:ALLPLAN_USR,
    [string]$Ref = $(if ($env:ALLPLAN_MCP_REF) { $env:ALLPLAN_MCP_REF } else { "main" }),
    [string]$InstallDir = $(if ($env:ALLPLAN_MCP_DIR) { $env:ALLPLAN_MCP_DIR } else { Join-Path $env:LOCALAPPDATA "AllplanMCP" }),
    [switch]$SkipClaudeConfig
)

$AllplanMcpRepo = "viorizz/AllPlan_MCP"
$AllplanMcpScriptRoot = $PSScriptRoot  # empty when piped through iex

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Find-Uv {
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($candidate in @("$env:USERPROFILE\.local\bin\uv.exe", "$env:USERPROFILE\.cargo\bin\uv.exe")) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Get-SourceDir {
    if ($AllplanMcpScriptRoot -and (Test-Path (Join-Path $AllplanMcpScriptRoot "pyproject.toml")) `
            -and (Test-Path (Join-Path $AllplanMcpScriptRoot "python_host"))) {
        Write-Step "Using local checkout $AllplanMcpScriptRoot"
        return $AllplanMcpScriptRoot
    }

    $appDir = Join-Path $InstallDir "app"
    $url = "https://github.com/$AllplanMcpRepo/archive/$Ref.zip"
    Write-Step "Downloading $url"

    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    $tmp = Join-Path $InstallDir ("download-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        $zip = Join-Path $tmp "source.zip"
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zip
        Expand-Archive -Path $zip -DestinationPath $tmp
        $extracted = Get-ChildItem -Path $tmp -Directory | Select-Object -First 1

        if (Test-Path $appDir) {
            try {
                Remove-Item $appDir -Recurse -Force
            } catch {
                throw "Cannot replace $appDir (files in use). Quit Claude Desktop (tray icon > Quit) and run the installer again."
            }
        }
        Move-Item -Path $extracted.FullName -Destination $appDir
    } finally {
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
    return $appDir
}

function Install-AllplanMcp {
    $ErrorActionPreference = "Stop"
    $ProgressPreference = "SilentlyContinue"  # Invoke-WebRequest is very slow with the progress bar
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    # 1. uv
    $uv = Find-Uv
    if (-not $uv) {
        Write-Step "Installing uv"
        $shell = (Get-Process -Id $PID).Path
        & $shell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
        $uv = Find-Uv
        if (-not $uv) { throw "uv installation failed. Install it from https://docs.astral.sh/uv/ and re-run." }
    }
    Write-Step "uv: $uv"

    # 2. Source
    $sourceDir = Get-SourceDir

    # 3. Python environment
    Write-Step "Creating the Python environment"
    & $uv sync --directory $sourceDir
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed." }
    $exe = Join-Path $sourceDir ".venv\Scripts\allplan-mcp.exe"
    $python = Join-Path $sourceDir ".venv\Scripts\python.exe"
    if (-not (Test-Path $exe)) { throw "allplan-mcp.exe not found in $sourceDir\.venv." }

    # 4. PythonPart into Allplan
    Write-Step "Installing the StartPythonHost PythonPart for Allplan $AllplanVersion"
    $registerArgs = @((Join-Path $sourceDir "utils\register_python_host.py"), "--allplan-version", $AllplanVersion)
    if ($AllplanUsr) { $registerArgs += @("--allplan-local", $AllplanUsr) }
    & $python @registerArgs
    if ($LASTEXITCODE -ne 0) { throw "PythonPart registration failed (see message above). Re-run with -AllplanUsr <path> or `$env:ALLPLAN_USR." }

    # 5. Claude clients
    if (-not $SkipClaudeConfig) {
        Write-Step "Registering the 'allplan' MCP server in Claude Desktop"
        $configs = @(Join-Path $env:APPDATA "Claude\claude_desktop_config.json")
        # Microsoft Store (MSIX) builds of Claude Desktop read a virtualized AppData.
        $msixDirs = @(Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA "Packages") -Directory -Filter "Claude_*" -ErrorAction SilentlyContinue)
        foreach ($msixDir in $msixDirs) {
            $configs += Join-Path $msixDir.FullName "LocalCache\Roaming\Claude\claude_desktop_config.json"
        }
        # JSON merge done in Python: Windows PowerShell 5.1 mangles some arrays in ConvertTo-Json.
        & $python (Join-Path $sourceDir "utils\configure_claude_desktop.py") --command $exe @configs
        if ($LASTEXITCODE -ne 0) { Write-Warning "Claude Desktop was not configured; see README to add the server by hand." }

        $claudeCli = Get-Command claude.exe, claude.cmd, claude -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($claudeCli) {
            Write-Step "Registering the 'allplan' MCP server in Claude Code (user scope)"
            $ErrorActionPreference = "Continue"
            # Arguments as arrays: a bare -- typed on the command line can be eaten by PowerShell.
            $removeArgs = @("mcp", "remove", "--scope", "user", "allplan")
            $addArgs = @("mcp", "add", "--scope", "user", "allplan", "--", $exe, "--transport", "stdio")
            & $claudeCli.Source @removeArgs *> $null
            & $claudeCli.Source @addArgs
            $ErrorActionPreference = "Stop"
        }
    }

    Write-Host ""
    Write-Host "Done." -ForegroundColor Green
    Write-Host "  1. Restart Claude Desktop (tray icon > Quit, then reopen)."
    Write-Host "  2. In Allplan ${AllplanVersion}: Library > Private > PythonParts > StartPythonHost."
    Write-Host "     Keep it running while Claude works (ESC stops it)."
    Write-Host "  3. Ask Claude: 'Which Allplan version is running?'"
}

Install-AllplanMcp
