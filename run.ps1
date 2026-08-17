# run.ps1 -- one-command start for the naval RP NPC bot.
#
# On the first run it bootstraps everything; every run after it just starts.
#   .\run.ps1            (or double-click run.bat)
#
# It will, in order:
#   1. create the virtual env + install dependencies (first run only)
#   2. run the Discord setup wizard if .env has no token yet
#   3. start the LM Studio server and load LLM_MODEL
#   4. launch the bot

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"

function Get-EnvValue($name) {
    if (Test-Path ".env") {
        foreach ($line in Get-Content ".env") {
            if ($line -match "^\s*$name\s*=\s*(.+?)\s*$") { return $Matches[1] }
        }
    }
    return ""
}

# 1. First-run bootstrap: virtual env + dependencies.
if (-not (Test-Path $python)) {
    Write-Host "[setup] Creating virtual environment and installing dependencies..." -ForegroundColor Yellow
    python -m venv .venv
    & $python -m pip install -q -r requirements.txt
}

# 2. Need a Discord token; run the wizard if it's missing.
if (-not (Get-EnvValue "DISCORD_TOKEN")) {
    Write-Host "[setup] No Discord token found -- starting the setup wizard..." -ForegroundColor Yellow
    & $python setup.py
    if (-not (Get-EnvValue "DISCORD_TOKEN")) {
        Write-Host "Setup didn't complete. Re-run .\run.ps1 once you have a token." -ForegroundColor Red
        exit 1
    }
}

# 3. Bring up LM Studio (best effort -- the bot falls back to xAI if it's down).
$model = Get-EnvValue "LLM_MODEL"
if (-not $model) { $model = "google/gemma-4-31b" }
try {
    Write-Host "[1/2] Starting LM Studio..." -ForegroundColor Cyan
    lms server start
    # Load the model only if it isn't already loaded -- avoids stacking duplicate
    # instances and exhausting VRAM on repeated launches.
    $loaded = $false
    try {
        if ((lms ps 2>$null | Out-String) -match [regex]::Escape($model)) { $loaded = $true }
    } catch {}
    if ($loaded) {
        Write-Host "      '$model' already loaded." -ForegroundColor DarkGray
    } else {
        Write-Host "      Loading '$model'..." -ForegroundColor Cyan
        lms load $model --gpu max --parallel 4 -c 24000 -y
    }
} catch {
    Write-Host "    LM Studio CLI unavailable; relying on the xAI fallback (if set)." -ForegroundColor DarkYellow
}

# 4. Launch.
Write-Host "[2/2] Launching the crew (Ctrl+C to stop)..." -ForegroundColor Green
& $python bot.py
