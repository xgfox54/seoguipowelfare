[CmdletBinding()]
param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot '.venv-package\Scripts\python.exe'
$Spec = Join-Path $ProjectRoot 'welfare_assistant.spec'
$Version = (Get-Content -LiteralPath (Join-Path $ProjectRoot 'VERSION') -Raw).Trim()

if (-not (Test-Path -LiteralPath $Python)) {
    throw '패키징 가상환경이 없습니다. Python 3.12로 .venv-package를 만든 뒤 requirements-build.txt를 설치하세요.'
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'wiki\kb-v120\welfare.db'))) {
    throw '검색 DB가 없습니다. 먼저 welfare_index.py build를 실행하세요.'
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'runtime\llamacpp\llama-server.exe'))) {
    throw 'runtime\llamacpp\llama-server.exe 가 없습니다. llama.cpp Windows 빌드(vulkan-x64)를 runtime\llamacpp 에 풀어 넣으세요.'
}
if (-not (Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'models') -Filter '*.gguf' -ErrorAction SilentlyContinue)) {
    throw 'models\*.gguf 가 없습니다. 기본 모델 gemma4-e2b-it-qat.gguf 를 models 폴더에 넣으세요.'
}

Push-Location $ProjectRoot
try {
    & $Python -m PyInstaller --noconfirm --clean $Spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 빌드에 실패했습니다.' }

    $Stage = Join-Path $ProjectRoot 'dist\welfare_assistant'
    $ExeName = (-join ([char[]](0xBCF5, 0xC9C0, 0xC5C5, 0xBB34, 0xBE44, 0xC11C))) + '.exe'
    $BuiltExe = Join-Path $Stage 'welfare_assistant.exe'
    $Exe = Join-Path $Stage $ExeName
    if (Test-Path -LiteralPath $Exe) { Remove-Item -LiteralPath $Exe -Force }
    Move-Item -LiteralPath $BuiltExe -Destination $Exe -Force

    robocopy (Join-Path $ProjectRoot 'runtime\llamacpp') (Join-Path $Stage 'runtime\llamacpp') /E /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw 'runtime 복사 실패' }
    robocopy (Join-Path $ProjectRoot 'models') (Join-Path $Stage 'models') *.gguf /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw 'models 복사 실패' }
    New-Item -ItemType Directory -Force -Path (Join-Path $Stage 'logs') | Out-Null

    $Item = Get-Item -LiteralPath $Exe
    Write-Host ("Stage completed: {0} ({1:N0} bytes)" -f $Item.FullName, $Item.Length)

    if (-not $SkipInstaller) {
        $Iscc = $env:ISCC_PATH
        if (-not $Iscc) { $Iscc = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' }
        if (-not (Test-Path -LiteralPath $Iscc)) { throw "Inno Setup ISCC.exe 를 찾을 수 없습니다: $Iscc (ISCC_PATH 환경변수로 지정 가능)" }
        & $Iscc "/DAppVersion=$Version" (Join-Path $ProjectRoot 'installer.iss')
        if ($LASTEXITCODE -ne 0) { throw 'Inno Setup 빌드에 실패했습니다.' }
        $Setup = Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'dist') -Filter "*Setup*$Version*.exe" | Select-Object -First 1
        Write-Host ("Installer completed: {0} ({1:N0} bytes)" -f $Setup.FullName, $Setup.Length)
    }
} finally {
    Pop-Location
}
