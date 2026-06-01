# =============================================================================
# SoulYatri Speech - Setup Script (Windows PowerShell)
# =============================================================================
# Run this script to set up the development environment.
# Usage: .\scripts\setup.ps1
# =============================================================================

Write-Host ""
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host "  SoulYatri Speech - Setup" -ForegroundColor Cyan
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host ""

# --- Check Python ---
Write-Host "[1/6] Checking Python..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "  [OK] $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "  [X] Python not found. Install Python 3.10+ from https://python.org" -ForegroundColor Red
    exit 1
}

# --- Check Node.js ---
Write-Host "[2/6] Checking Node.js..." -ForegroundColor Yellow
try {
    $nodeVersion = node --version 2>&1
    Write-Host "  [OK] Node.js $nodeVersion" -ForegroundColor Green
} catch {
    Write-Host "  [X] Node.js not found. Install Node.js 18+ from https://nodejs.org" -ForegroundColor Red
    exit 1
}

# --- Check Docker ---
Write-Host "[3/6] Checking Docker..." -ForegroundColor Yellow
try {
    $dockerVersion = docker --version 2>&1
    Write-Host "  [OK] $dockerVersion" -ForegroundColor Green
} catch {
    Write-Host "  [X] Docker not found. Install Docker Desktop from https://docker.com" -ForegroundColor Red
    exit 1
}

# --- Check Ollama ---
Write-Host "[4/6] Checking Ollama..." -ForegroundColor Yellow
try {
    $ollamaVersion = ollama --version 2>&1
    Write-Host "  [OK] Ollama $ollamaVersion" -ForegroundColor Green
} catch {
    Write-Host "  [!] Ollama not found. Install from https://ollama.com" -ForegroundColor Yellow
    Write-Host "      You can install it later, but the LLM pipeline won't work without it." -ForegroundColor Yellow
}

# --- Set up Python virtual environment ---
Write-Host ""
Write-Host "[5/6] Setting up Python environment..." -ForegroundColor Yellow

$venvPath = "server\venv"
if (-not (Test-Path $venvPath)) {
    Write-Host "  Creating virtual environment..." -ForegroundColor Gray
    python -m venv $venvPath
    Write-Host "  [OK] Virtual environment created at $venvPath" -ForegroundColor Green
} else {
    Write-Host "  [OK] Virtual environment already exists" -ForegroundColor Green
}

# Install dependencies (use `python -m pip` so pip can upgrade itself on Windows)
Write-Host "  Installing Python dependencies..." -ForegroundColor Gray
& "$venvPath\Scripts\python.exe" -m pip install --upgrade pip --quiet
& "$venvPath\Scripts\python.exe" -m pip install -r server\requirements.txt --quiet
Write-Host "  [OK] Python dependencies installed" -ForegroundColor Green

# --- Set up Node.js client ---
Write-Host ""
Write-Host "[6/6] Setting up Next.js client..." -ForegroundColor Yellow

if (Test-Path "client\package.json") {
    Push-Location client
    npm install --quiet
    Pop-Location
    Write-Host "  [OK] Node.js dependencies installed" -ForegroundColor Green
} else {
    Write-Host "  [!] Client not found. Run 'npx create-next-app@latest ./client' first" -ForegroundColor Yellow
}

# --- Create .env if not exists ---
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ""
    Write-Host "  [OK] Created .env from .env.example - review and update as needed" -ForegroundColor Green
}

# --- Summary ---
Write-Host ""
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host "  Setup Complete!" -ForegroundColor Cyan
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Pull an Ollama model:    ollama pull qwen3:8b" -ForegroundColor White
Write-Host "  2. Start infrastructure:    docker-compose up -d" -ForegroundColor White
Write-Host "  3. Start Python server:     server\venv\Scripts\activate; python -m server.main" -ForegroundColor White
Write-Host "  4. Start web client:        cd client; npm run dev" -ForegroundColor White
Write-Host "  5. Open browser:            http://localhost:3000" -ForegroundColor White
Write-Host ""
