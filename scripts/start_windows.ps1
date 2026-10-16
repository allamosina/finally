# Start FinAlly in Docker (Windows PowerShell). Idempotent.
# Usage: .\scripts\start_windows.ps1 [-Build] [-NoOpen]
param([switch]$Build, [switch]$NoOpen)
$ErrorActionPreference = 'Stop'

$Image = 'finally'
$Name = 'finally'
$Port = 8000
$Url = "http://localhost:$Port"
$Timeout = 90

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Error 'docker not found. Install Docker first.'; exit 1 }
docker info *> $null
if ($LASTEXITCODE -ne 0) { Write-Error 'Docker daemon is not running.'; exit 1 }

New-Item -ItemType Directory -Force -Path (Join-Path $Root 'db') | Out-Null

docker image inspect $Image *> $null
$HaveImage = ($LASTEXITCODE -eq 0)
if ($Build -or -not $HaveImage) {
    Write-Host "Building image '$Image'..."
    docker build -t $Image .
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

$EnvArgs = @()
if (Test-Path (Join-Path $Root '.env')) {
    $EnvArgs = @('--env-file', '.env')
} else {
    Write-Warning ".env not found; copy .env.example to .env. Chat will report 'LLM not configured' unless LLM_MOCK=true."
}

docker container inspect $Name *> $null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Replacing existing container '$Name'..."
    docker rm -f $Name *> $null
}

Write-Host "Starting container '$Name'..."
$DbMount = "$(Join-Path $Root 'db'):/app/db"
docker run -d --rm --name $Name -v $DbMount -p "${Port}:8000" @EnvArgs $Image *> $null
if ($LASTEXITCODE -ne 0) { Write-Error 'docker run failed.'; exit 1 }

Write-Host "Waiting for $Url/api/health (up to ${Timeout}s)..."
$Deadline = (Get-Date).AddSeconds($Timeout)
$Healthy = $false
while ((Get-Date) -lt $Deadline) {
    docker container inspect $Name *> $null
    if ($LASTEXITCODE -ne 0) { Write-Error "Container exited before becoming healthy. Check: docker logs $Name"; exit 1 }
    try {
        $r = Invoke-RestMethod -Uri "$Url/api/health" -TimeoutSec 2
        if ($r.status -eq 'ok') { $Healthy = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
}
if (-not $Healthy) {
    Write-Error 'Timed out waiting for health.'
    docker logs --tail 50 $Name
    exit 1
}

Write-Host "FinAlly is running at $Url"
if (-not $NoOpen) { Start-Process $Url }
