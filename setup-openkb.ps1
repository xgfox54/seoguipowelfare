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
$Source = Join-Path $ProjectRoot 'source-md'

if (-not (Test-Path -LiteralPath $Source)) {
    throw "Source directory not found: $Source"
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Python 실행환경이 없습니다. Python 3.12로 .venv-openkb를 먼저 구성하고 requirements.txt를 설치하세요.'
}

Push-Location $ProjectRoot
try {
    & $Python 'welfare_assistant.py' 'init'
    if ($LASTEXITCODE -ne 0) { throw '로컬 복지업무 비서 상태 초기화에 실패했습니다.' }
    if ($RebuildIndex -or -not (Test-Path -LiteralPath 'wiki\kb-v120\welfare.db')) {
        & $Python 'welfare_index.py' 'build'
        if ($LASTEXITCODE -ne 0) { throw '전체 복지DB 검색색인 구축에 실패했습니다.' }
    }
    & $Python 'welfare_assistant.py' 'status'
    if ($LASTEXITCODE -ne 0) { throw '복지업무 비서 상태 점검에 실패했습니다.' }
} finally {
    Pop-Location
}

Write-Host 'Setup check completed.'
