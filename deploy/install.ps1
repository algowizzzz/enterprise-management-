<#
.SYNOPSIS
    Install Consilium on Windows from an offline bundle.

.DESCRIPTION
    The counterpart to install.sh. Everything needed is inside the bundle; if
    any step here reaches the network, that is a defect — report it rather than
    opening a firewall hole, because the same step will fail on a stricter host.

    Prerequisites, which this checks and does not install:
      - Python 3.10 or newer, on PATH, with the venv module
      - PostgreSQL 13 or newer, reachable, with either a superuser login or a
        database and owner role provisioned in advance (see -NoSetupDb)
      - A Redis-compatible service reachable on the configured port

    No administrator rights are needed beyond what the prerequisites required.
    Assets are copied rather than linked, so Developer Mode is not required.

.EXAMPLE
    .\install\install.ps1 -Target C:\consilium -Site consilium.local
#>
[CmdletBinding()]
param(
    [string] $Target          = "C:\consilium",
    [string] $Site            = "consilium.local",
    [string] $DbHost          = "127.0.0.1",
    [int]    $DbPort          = 5432,
    [string] $DbName          = "consilium",
    [string] $DbRootUser      = "postgres",
    [string] $DbRootPassword  = "",
    [string] $DbPassword      = "",
    [string] $AdminPassword   = "",
    [string] $RedisUrl        = "redis://127.0.0.1:6379",
    [switch] $NoSetupDb,
    [switch] $SkipVerify
)

$ErrorActionPreference = "Stop"
$BundleRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)

function Write-Step { param($Message) Write-Host "`n==> $Message" -ForegroundColor Cyan }
function Fail { param($Message) Write-Host "FAILED: $Message" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------- prerequisites
Write-Step "Checking prerequisites"

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { Fail "python is not on PATH" }

$version = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
$ok = & python -c "import sys; print(1 if sys.version_info >= (3,10) else 0)"
if ($ok -ne "1") { Fail "Python 3.10 or newer is required; found $version" }
Write-Host "  Python $version"

& python -c "import venv" 2>$null
if ($LASTEXITCODE -ne 0) { Fail "the Python venv module is missing" }

# Corporate machines frequently redirect the user profile to OneDrive, and a
# database or site directory inside a syncing folder corrupts in ways that are
# painful to diagnose. Catch it here rather than in three weeks.
if ($Target -match "OneDrive|Dropbox|Google Drive") {
    Fail "the install target is inside a syncing folder ($Target). Choose a local path such as C:\consilium."
}
if ($Target -match "[^\x20-\x7E]") {
    Fail "the install target contains non-ASCII characters, which some tooling mishandles"
}

Write-Step "Checking services"
try {
    $test = Test-NetConnection -ComputerName $DbHost -Port $DbPort -InformationLevel Quiet -WarningAction SilentlyContinue
    if (-not $test) { Fail "nothing is listening on ${DbHost}:${DbPort}. Is PostgreSQL running?" }
    Write-Host "  PostgreSQL port open at ${DbHost}:${DbPort}"
} catch { Fail "could not reach ${DbHost}:${DbPort}" }

$redisUri = [System.Uri] $RedisUrl
$redisTest = Test-NetConnection -ComputerName $redisUri.Host -Port $redisUri.Port -InformationLevel Quiet -WarningAction SilentlyContinue
if (-not $redisTest) { Fail "nothing is listening on $($redisUri.Host):$($redisUri.Port). Is the Redis service running?" }
Write-Host "  Redis port open at $($redisUri.Host):$($redisUri.Port)"

# -------------------------------------------------------------------- bundle
if (-not $SkipVerify) {
    Write-Step "Verifying the bundle"
    $sumsPath = Join-Path $BundleRoot "SHA256SUMS"
    if (-not (Test-Path $sumsPath)) { Fail "no SHA256SUMS in the bundle" }
    $bad = @()
    foreach ($line in Get-Content $sumsPath) {
        if (-not $line.Trim()) { continue }
        $expected, $relative = $line -split "  ", 2
        $file = Join-Path $BundleRoot $relative
        if (-not (Test-Path $file)) { $bad += "$relative is missing"; continue }
        $actual = (Get-FileHash -Algorithm SHA256 $file).Hash.ToLower()
        if ($actual -ne $expected.ToLower()) { $bad += "$relative does not match" }
    }
    if ($bad.Count) {
        Fail "the bundle does not match its checksums:`n  $($bad[0..([Math]::Min(4,$bad.Count-1))] -join "`n  ")"
    }
    Write-Host "  every file matches its recorded checksum"
}

$wheelhouse = Join-Path $BundleRoot "wheelhouse"
if (-not (Test-Path $wheelhouse)) { Fail "no wheelhouse in the bundle" }
Write-Host "  $((Get-ChildItem $wheelhouse -Filter *.whl).Count) wheels available"

# --------------------------------------------------------------- environment
Write-Step "Creating the Python environment at $Target"
New-Item -ItemType Directory -Force -Path $Target | Out-Null
& python -m venv (Join-Path $Target "env")
$py = Join-Path $Target "env\Scripts\python.exe"

# --no-index is the point of the exercise: pip must not reach out.
& $py -m pip install --quiet --no-index --find-links $wheelhouse --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { Fail "could not install packaging tools from the bundle" }
& $py -m pip install --quiet --no-index --find-links $wheelhouse frappe consilium
if ($LASTEXITCODE -ne 0) { Fail "could not install the application from the bundle" }
Write-Host "  installed from local files only"

# -------------------------------------------------------------------- layout
Write-Step "Laying out the site directory"
New-Item -ItemType Directory -Force -Path (Join-Path $Target "sites"), (Join-Path $Target "logs"), (Join-Path $Target "apps") | Out-Null

@"
{
  "db_type": "postgres",
  "db_host": "$DbHost",
  "db_port": $DbPort,
  "redis_cache": "$RedisUrl",
  "redis_queue": "$RedisUrl",
  "redis_socketio": "$RedisUrl",
  "socketio_port": 9000,
  "webserver_port": 8000,
  "developer_mode": 0
}
"@ | Set-Content -Encoding utf8 (Join-Path $Target "sites\common_site_config.json")

"frappe`nconsilium" | Set-Content -Encoding ascii (Join-Path $Target "sites\apps.txt")

# ------------------------------------------------------------------ the site
Write-Step "Creating the site"
$env:FRAPPE_BENCH_ROOT = $Target
Push-Location (Join-Path $Target "sites")

$siteArgs = @("new-site", $Site, "--db-type", "postgres", "--db-host", $DbHost,
              "--db-port", $DbPort, "--db-name", $DbName)
if ($DbPassword)    { $siteArgs += @("--db-password", $DbPassword) }
if ($AdminPassword) { $siteArgs += @("--admin-password", $AdminPassword) }
if ($NoSetupDb) {
    # The database and its owner role already exist and we hold no superuser
    # login, so the framework must not try to create them.
    $siteArgs += "--no-setup-db"
} else {
    $siteArgs += @("--db-root-username", $DbRootUser, "--db-root-password", $DbRootPassword)
}

& $py -m frappe.utils.bench_helper frappe @siteArgs 2>&1 | Where-Object { $_ -notmatch "Updating DocTypes" }
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "site creation failed" }

Write-Step "Installing the application"
& $py -m frappe.utils.bench_helper frappe --site $Site install-app consilium 2>&1 | Where-Object { $_ -notmatch "Updating DocTypes" }
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "could not install the application into the site" }
Pop-Location

# -------------------------------------------------------------------- assets
Write-Step "Installing front-end assets"
$assetBundle = Get-ChildItem (Join-Path $BundleRoot "assets") -Filter "frappe-assets-*.tar.gz" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($assetBundle) {
    # Copied rather than linked: a link needs a privilege this installer may not
    # hold, and a copy needs none. The health check detects a copy going stale.
    & $py -m winbench.cli assets --import $assetBundle.FullName --copy
    Write-Host "  unpacked $($assetBundle.Name)"
} else {
    Write-Host "  no prebuilt asset bundle found; the interface will not render correctly" -ForegroundColor Yellow
}

# ----------------------------------------------------------------- reference
Write-Step "Loading reference data"
Push-Location (Join-Path $Target "sites")
& $py (Join-Path $BundleRoot "install\seed.py") --site $Site
Pop-Location

# --------------------------------------------------------------------- check
Write-Step "Checking the installation"
Push-Location (Join-Path $Target "sites")
& $py (Join-Path $BundleRoot "install\healthcheck.py") --site $Site
$healthy = $LASTEXITCODE -eq 0
Pop-Location
if (-not $healthy) { Fail "the installation is not healthy — see the failures above" }

Write-Step "Done"
@"

  Installed at : $Target
  Site         : $Site

  Start it with:

    cd $Target
    `$env:FRAPPE_BENCH_ROOT = "$Target"
    $py -m winbench.cli serve --port 8000

  Then open http://localhost:8000 and sign in as Administrator.

"@ | Write-Host
