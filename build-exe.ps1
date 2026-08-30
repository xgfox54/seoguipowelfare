[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot '.venv-package\Scripts\python.exe'
$Spec = Join-Path $ProjectRoot '복지업무비서.spec'

if (-not (Test-Path -LiteralPath $Python)) {
    throw '패키징 가상환경이 없습니다. Python 3.12로 .venv-package를 만든 뒤 requirements-build.txt를 설치하세요.'
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'wiki\kb-v120\welfare.db'))) {
    throw '검색 DB가 없습니다. 먼저 welfare_index.py build를 실행하세요.'
}

Push-Location $ProjectRoot
try {
    & $Python -m PyInstaller --noconfirm --clean $Spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 빌드에 실패했습니다.' }
} finally {
    Pop-Location
}

$Exe = Join-Path $ProjectRoot 'dist\복지업무비서.exe'
if (-not (Test-Path -LiteralPath $Exe)) {
    throw "EXE 결과물을 찾을 수 없습니다: $Exe"
}
$Item = Get-Item -LiteralPath $Exe
Write-Host ("Build completed: {0} ({1:N0} bytes)" -f $Item.FullName, $Item.Length)
