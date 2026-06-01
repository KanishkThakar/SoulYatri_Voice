# =============================================================================
# SoulYatri Speech - Roadmap Test Runner (Windows PowerShell)
# =============================================================================
# Runs the speech-native-voice-roadmap package test suite locally in a single,
# non-watch run and surfaces a non-zero exit code on failure (for CI / callers).
#
# What it does:
#   - Resolves the workspace root relative to this script's own location
#     ($PSScriptRoot -> parent dir), so it works from any current directory.
#   - Pushes to the workspace root, runs the roadmap tests, then pops back.
#   - Executes `python -m pytest roadmap/tests` with the Hypothesis "roadmap"
#     profile (max_examples=100, registered in roadmap/tests/conftest.py).
#   - Propagates pytest's exit code as this script's exit code.
#   - Forwards any extra pass-through arguments to pytest.
#
# Usage:
#   .\scripts\run_roadmap_tests.ps1
#   .\scripts\run_roadmap_tests.ps1 -k duplex            # extra pytest flags
#   .\scripts\run_roadmap_tests.ps1 -- -x --maxfail=1    # forward raw flags
#
# Non-Windows equivalent (bash/zsh), run from the workspace root:
#   python -m pytest roadmap/tests -q --hypothesis-profile roadmap
# =============================================================================

[CmdletBinding()]
param(
    # Any remaining arguments are forwarded verbatim to pytest.
    [Parameter(ValueFromRemainingArguments = $true)]
    $PytestArgs
)

# Resolve the workspace root: this script lives in <root>\scripts, so the
# parent of $PSScriptRoot is the workspace root.
$workspaceRoot = Split-Path -Parent $PSScriptRoot

Write-Host ""
Write-Host "Running roadmap test suite (roadmap/tests)..." -ForegroundColor Cyan
Write-Host "  Workspace root: $workspaceRoot" -ForegroundColor Gray
Write-Host ""

Push-Location $workspaceRoot
try {
    # Single-run (non-watch) pytest over roadmap/tests using the Hypothesis
    # "roadmap" profile (>=100 examples). Forward any extra caller arguments.
    python -m pytest roadmap/tests -q --hypothesis-profile roadmap @PytestArgs
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($exitCode -eq 0) {
    Write-Host ""
    Write-Host "[OK] Roadmap tests passed." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "[X] Roadmap tests failed (exit code $exitCode)." -ForegroundColor Red
}

# Propagate pytest's exit code so CI / callers can detect failure.
exit $exitCode
