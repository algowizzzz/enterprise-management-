#Requires -Version 5.1
<#
.SYNOPSIS
    Set up a Frappe bench on Windows: Postgres, Redis, no WSL, no Docker.

.DESCRIPTION
    Installs the prerequisites via winget, creates the bench, and runs
    `winbench doctor`. Everything it installs is a normal Windows service or a
    normal Python package -- nothing here needs WSL or a Linux container.

    Redis has no official Windows build. Memurai is the supported drop-in and is
    what this script installs; the Redis 5.x Microsoft archive fork also works
    but is long unmaintained.

.PARAMETER BenchPath
    Where to create the bench. Keep it short and off a synced folder
    (OneDrive/Dropbox) -- Frappe's asset tree is deep and file-locking sync
    clients corrupt builds.

.EXAMPLE
    .\bootstrap.ps1 -BenchPath C:\frappe -SiteName win.localhost
#>
param(
    [string]$BenchPath = "C:\frappe",
    [string]$SiteName = "win.localhost",
    [string]$FrappeBranch = "version-15",
    [switch]$SkipPrereqs
)

$ErrorActionPreference = "Stop"

function Write-Step($message) {
    Write-Host ""
    Write-Host "==> $message" -ForegroundColor Cyan
}

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

if ($BenchPath -match '\s') {
    throw "BenchPath must not contain spaces: some of Frappe's node tooling mishandles them."
}

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------
if (-not $SkipPrereqs) {
    Write-Step "Installing prerequisites with winget"

    if (-not (Test-Command winget)) {
        throw "winget not found. Install 'App Installer' from the Microsoft Store, or pass -SkipPrereqs and install the prerequisites yourself."
    }

    $packages = @(
        @{ Id = "Python.Python.3.11";        Check = "python"   },
        @{ Id = "Git.Git";                   Check = "git"      },
        @{ Id = "PostgreSQL.PostgreSQL.16";  Check = "psql"     },
        @{ Id = "Memurai.MemuraiDeveloper";  Check = "memurai"  }
    )

    foreach ($package in $packages) {
        if (Test-Command $package.Check) {
            Write-Host "  already present: $($package.Check)"
            continue
        }
        Write-Host "  installing $($package.Id)"
        winget install --id $package.Id --silent --accept-package-agreements --accept-source-agreements
    }

    # winget updates the machine PATH but not this process's copy.
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")

    # Node and yarn are deliberately absent. Compiling front-end assets is the
    # only step that would need them, and the built output ships in the
    # repository instead (see assets/). The runtime never needs node, and on a
    # locked-down network the npm registry is usually the first thing blocked.
}

# ---------------------------------------------------------------------------
# Redis instances
# ---------------------------------------------------------------------------
# Frappe wants two logically separate Redis instances (cache and queue). A
# single instance on one port works, but flushing the cache would then also drop
# queued jobs, so run two.
Write-Step "Checking Redis on 13000 (cache) and 11000 (queue)"
foreach ($port in 13000, 11000) {
    $connection = Test-NetConnection -ComputerName 127.0.0.1 -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue
    if ($connection) {
        Write-Host "  port $port : listening"
    } else {
        Write-Warning "  port $port : nothing listening. Configure a Memurai instance on this port (see docs/WINDOWS_SETUP.md)."
    }
}

# ---------------------------------------------------------------------------
# Bench
# ---------------------------------------------------------------------------
Write-Step "Creating bench at $BenchPath"

if (-not (Test-Path $BenchPath)) { New-Item -ItemType Directory -Path $BenchPath | Out-Null }

$winbenchSource = Join-Path $PSScriptRoot "..\winbench"
python -m pip install --upgrade pip wheel
python -m pip install -e $winbenchSource

winbench init $BenchPath --frappe-branch $FrappeBranch

Push-Location $BenchPath
try {
    Write-Step "Running winbench doctor"
    winbench doctor

    Write-Step "Creating site $SiteName"
    Write-Host "You will be prompted for the Administrator password and the Postgres superuser password."
    winbench new-site $SiteName

    Write-Step "Building assets"
    winbench build --production

    Write-Host ""
    Write-Host "Done. Start everything with:" -ForegroundColor Green
    Write-Host "    cd $BenchPath"
    Write-Host "    winbench start"
    Write-Host ""
    Write-Host "Then open http://127.0.0.1:8000 and log in as Administrator."
    Write-Host "Add '127.0.0.1 $SiteName' to C:\Windows\System32\drivers\etc\hosts to reach the site by name."
}
finally {
    Pop-Location
}
