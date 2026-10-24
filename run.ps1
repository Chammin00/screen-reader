# Kindle Voice Narrator PowerShell Launcher
Set-Location -Path $PSScriptRoot

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  Launching Kindle Voice Narrator & AI Study Companion" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan

$env:PYTHONIOENCODING = "utf-8"

# 1. Prefer user profile virtual environment (fully permitted by Device Guard / WDAC)
$localVenvPython = Join-Path $env:USERPROFILE ".antigravity_venvs\screen_reader\Scripts\python.exe"
if (Test-Path $localVenvPython) {
    Write-Host "Using authorized local environment: $localVenvPython" -ForegroundColor DarkGray
    & $localVenvPython (Join-Path $PSScriptRoot "main.py")
    exit $LASTEXITCODE
}

# 2. Check project virtual environment directly
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    Write-Host "Using project environment: .venv" -ForegroundColor DarkGray
    & $venvPython (Join-Path $PSScriptRoot "main.py")
    exit $LASTEXITCODE
}

# 3. Look for uv package runner
$uvCandidates = @(
    "$env:USERPROFILE\.local\bin\uv.exe",
    "$env:USERPROFILE\.cargo\bin\uv.exe",
    "$env:LOCALAPPDATA\Programs\uv\uv.exe"
)

$uvPath = $null
foreach ($cand in $uvCandidates) {
    if (Test-Path $cand) {
        $uvPath = $cand
        break
    }
}

if (-not $uvPath) {
    $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($uvCmd) {
        $uvPath = $uvCmd.Source
    }
}

if ($uvPath) {
    Write-Host "Using package runner: $uvPath" -ForegroundColor DarkGray
    & $uvPath run python (Join-Path $PSScriptRoot "main.py")
    exit $LASTEXITCODE
}

# 3. Fallback to system python
Write-Host "Running with system python..." -ForegroundColor DarkGray
python (Join-Path $PSScriptRoot "main.py")

if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
    Write-Host "`n[Error] Application exited with code $LASTEXITCODE" -ForegroundColor Red
    Read-Host "Press Enter to exit..."
}
