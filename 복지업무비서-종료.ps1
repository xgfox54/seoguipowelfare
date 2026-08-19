[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $ProjectRoot '.openkb\web-server.pid'

if (-not (Test-Path -LiteralPath $PidFile)) {
    Write-Host '실행 중인 복지업무 비서 웹 서버가 없습니다.'
    exit 0
}

$ServerId = [int](Get-Content -LiteralPath $PidFile -Raw).Trim()
$Process = Get-Process -Id $ServerId -ErrorAction SilentlyContinue
if ($null -eq $Process) {
    Remove-Item -LiteralPath $PidFile -Force
    Write-Host '웹 서버는 이미 종료되어 있습니다.'
    exit 0
}

$Connection = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue |
    Where-Object OwningProcess -eq $ServerId |
    Select-Object -First 1
$HealthResponse = $null
try {
    $HealthResponse = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/status' -TimeoutSec 1
} catch {
    $HealthResponse = $null
}
$IsWelfareServer = (
    $null -ne $HealthResponse -and
    $null -ne $HealthResponse.status -and
    $null -ne $HealthResponse.model -and
    $null -ne $HealthResponse.source_documents -and
    $null -ne $HealthResponse.search_sections
)
if ($null -eq $Connection -or $Process.ProcessName -notmatch '^pythonw?$' -or -not $IsWelfareServer) {
    throw '기록된 프로세스가 복지업무 비서 서버와 일치하지 않아 종료하지 않았습니다.'
}

Stop-Process -Id $ServerId
Remove-Item -LiteralPath $PidFile -Force
Write-Host '개인용 복지업무 비서 웹 서버를 종료했습니다.'
