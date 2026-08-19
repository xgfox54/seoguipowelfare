[CmdletBinding()]
param(
    [switch]$RebuildIndex
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = '1'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot '.venv-openkb\Scripts\python.exe'
$OpenKB = Join-Path $ProjectRoot '.venv-openkb\Scripts\openkb.exe'
$Source = Join-Path $ProjectRoot 'source-md'
$PolicyTemplate = Join-Path $ProjectRoot 'policy\AGENTS.md'
$Policy = Join-Path $ProjectRoot 'wiki\AGENTS.md'

function Invoke-OpenKB {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    if (-not (Test-Path -LiteralPath $OpenKB)) {
        throw "OpenKB is not installed. Run .\setup-openkb.ps1 again after network/package installation is available."
    }
    & $OpenKB @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "OpenKB command failed: openkb $($Arguments -join ' ')"
    }
}

if (-not (Test-Path -LiteralPath $Source)) {
    throw "Source directory not found: $Source"
}

if (-not (Test-Path -LiteralPath $OpenKB)) {
    throw '검증된 OpenKB 실행환경이 없습니다. Python 3.12로 .venv-openkb를 먼저 구성해야 합니다.'
}

if (-not (Test-Path -LiteralPath $PolicyTemplate)) {
    throw "Policy template missing: $PolicyTemplate"
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Policy) | Out-Null
Copy-Item -LiteralPath $PolicyTemplate -Destination $Policy -Force

Push-Location $ProjectRoot
try {
    if ($RebuildIndex -or -not (Test-Path -LiteralPath 'wiki\search\welfare.db')) {
        & $Python 'welfare_index.py' 'build'
        if ($LASTEXITCODE -ne 0) { throw '전체 복지DB 검색색인 구축에 실패했습니다.' }
    }
    Invoke-OpenKB @('status')
    & $Python 'welfare_assistant.py' 'status'
    if ($LASTEXITCODE -ne 0) { throw '복지업무 비서 상태 점검에 실패했습니다.' }
} finally {
    Pop-Location
}

Write-Host 'Setup check completed.'
