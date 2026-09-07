[CmdletBinding()]
param(
    [switch]$NoOpen
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot '.venv-openkb\Scripts\python.exe'
$Url = 'http://127.0.0.1:8765/'
$HealthUrl = "${Url}api/status"
$PidFile = Join-Path $ProjectRoot '.openkb\web-server.pid'
$LogDirectory = Join-Path $ProjectRoot '.openkb\web-logs'

if (-not (Test-Path -LiteralPath $Python)) {
    throw '복지업무 비서 실행환경이 없습니다. setup-openkb.ps1을 먼저 실행하세요.'
}

function Test-WelfareServer {
    try {
        $Response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 1
        return $Response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Get-WelfareServerProcessId {
    $Connection = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $Connection) {
        return $null
    }
    return [int]$Connection.OwningProcess
}

$env:PYTHONUTF8 = '1'
$env:WELFARE_LLM_PORT = '18080'
if (-not (Test-WelfareServer)) {
    New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
    $Server = Start-Process `
        -FilePath $Python `
        -ArgumentList 'welfare_web.py' `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDirectory 'server-output.log') `
        -RedirectStandardError (Join-Path $LogDirectory 'server-error.log') `
        -PassThru
    Set-Content -LiteralPath $PidFile -Value $Server.Id -Encoding ascii

    $Ready = $false
    for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
        if ($Server.HasExited) {
            break
        }
        if (Test-WelfareServer) {
            $Ready = $true
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $Ready) {
        throw "로컬 웹 서버를 시작하지 못했습니다. 로그: $LogDirectory"
    }
}

$ListenerId = Get-WelfareServerProcessId
if ($null -eq $ListenerId) {
    throw '로컬 웹 서버 프로세스를 확인하지 못했습니다.'
}
Set-Content -LiteralPath $PidFile -Value $ListenerId -Encoding ascii

if (-not $NoOpen) {
    Start-Process $Url
}
Write-Host "개인용 복지업무 비서가 $Url 에서 실행 중입니다."
