# Stop and remove the FinAlly container. Never touches db\. Idempotent.
$ErrorActionPreference = 'Stop'
$Name = 'finally'
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Error 'docker not found.'; exit 1 }
docker container inspect $Name *> $null
if ($LASTEXITCODE -eq 0) {
    docker rm -f $Name *> $null
    Write-Host "Stopped and removed container '$Name'. Data in db\ is untouched."
} else {
    Write-Host "Container '$Name' is not running."
}
