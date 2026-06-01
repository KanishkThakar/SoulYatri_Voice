# =============================================================================
# SoulYatri Speech - Start LiveKit Server
# =============================================================================
# Starts the LiveKit server via Docker for local development.
# Usage: .\scripts\start_livekit.ps1
# =============================================================================

Write-Host ""
Write-Host "Starting LiveKit Server..." -ForegroundColor Cyan

# Start docker-compose services
docker-compose up -d livekit redis

Write-Host ""
Write-Host "Waiting for LiveKit to be ready..." -ForegroundColor Yellow

# Wait for health check
$maxRetries = 10
$retryCount = 0

while ($retryCount -lt $maxRetries) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:7880" -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200 -or $response.StatusCode -eq 404) {
            Write-Host ""
            Write-Host "[OK] LiveKit Server is ready!" -ForegroundColor Green
            Write-Host ""
            Write-Host "Connection Info:" -ForegroundColor Yellow
            Write-Host "  URL:        ws://localhost:7880" -ForegroundColor White
            Write-Host "  API Key:    devkey" -ForegroundColor White
            Write-Host "  API Secret: secret" -ForegroundColor White
            Write-Host "  Redis:      localhost:6379" -ForegroundColor White
            Write-Host ""
            exit 0
        }
    } catch {
        # Server not ready yet
    }

    $retryCount++
    Write-Host "  Attempt $retryCount/$maxRetries - waiting..." -ForegroundColor Gray
    Start-Sleep -Seconds 2
}

Write-Host ""
Write-Host "[X] LiveKit failed to start. Check Docker logs:" -ForegroundColor Red
Write-Host "  docker-compose logs livekit" -ForegroundColor White
Write-Host ""
