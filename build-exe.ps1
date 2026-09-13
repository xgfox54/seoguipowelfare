[CmdletBinding()]
param(
    [ValidateSet('E2B', 'E4B')]
    [string]$ModelVariant = 'E2B',
    [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot '.venv-package\Scripts\python.exe'
$Spec = Join-Path $ProjectRoot 'welfare_assistant.spec'
$Version = (Get-Content -LiteralPath (Join-Path $ProjectRoot 'VERSION') -Raw).Trim()
$ModelFilename = if ($ModelVariant -eq 'E4B') { 'gemma4-e4b.gguf' } else { 'gemma4-e2b-it-qat.gguf' }

if (-not (Test-Path -LiteralPath $Python)) {
    throw '패키징 가상환경이 없습니다. Python 3.12로 .venv-package를 만든 뒤 requirements-build.txt를 설치하세요.'
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'wiki\kb-v120\welfare.db'))) {
    throw '검색 DB가 없습니다. 먼저 welfare_index.py build를 실행하세요.'
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'runtime\llamacpp\llama-server.exe'))) {
    throw 'runtime\llamacpp\llama-server.exe 가 없습니다. llama.cpp Windows 빌드(vulkan-x64)를 runtime\llamacpp 에 풀어 넣으세요.'
}
$ModelSourcePath = Join-Path $ProjectRoot "models\$ModelFilename"
if (-not (Test-Path -LiteralPath $ModelSourcePath)) {
    throw "models\$ModelFilename 가 없습니다. $ModelVariant 빌드에 필요한 GGUF 파일을 models 폴더에 넣으세요."
}

Push-Location $ProjectRoot
try {
    & $Python -m PyInstaller --noconfirm --clean $Spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 빌드에 실패했습니다.' }

    $Stage = Join-Path $ProjectRoot 'dist\welfare_assistant'
    $ExeBaseName = (-join ([char[]](0xBCF5, 0xC9C0, 0xC5C5, 0xBB34, 0xBE44, 0xC11C)))
    $ExeName = "${ExeBaseName}_v${Version}_${ModelVariant}.exe"
    $BuiltExe = Join-Path $Stage 'welfare_assistant.exe'
    $Exe = Join-Path $Stage $ExeName
    if (Test-Path -LiteralPath $Exe) { Remove-Item -LiteralPath $Exe -Force }
    Move-Item -LiteralPath $BuiltExe -Destination $Exe -Force

    robocopy (Join-Path $ProjectRoot 'runtime\llamacpp') (Join-Path $Stage 'runtime\llamacpp') /E /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw 'runtime 복사 실패' }
    New-Item -ItemType Directory -Force -Path (Join-Path $Stage 'models') | Out-Null
    Copy-Item -LiteralPath $ModelSourcePath -Destination (Join-Path $Stage "models\$ModelFilename") -Force
    if ($LASTEXITCODE -ge 8) { throw 'models 복사 실패' }
    New-Item -ItemType Directory -Force -Path (Join-Path $Stage 'logs') | Out-Null

    $Item = Get-Item -LiteralPath $Exe
    Write-Host ("Stage completed: {0} ({1:N0} bytes)" -f $Item.FullName, $Item.Length)

    if (-not $SkipInstaller) {
        $Iscc = $env:ISCC_PATH
        if (-not $Iscc) {
            $IsccCandidates = @(
                'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
                'C:\Program Files\Inno Setup 6\ISCC.exe',
                (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
            )
            $Iscc = $IsccCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        }
        if (-not $Iscc) {
            $IsccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
            if ($IsccCommand) { $Iscc = $IsccCommand.Source }
        }
        if (-not (Test-Path -LiteralPath $Iscc)) { throw "Inno Setup ISCC.exe 를 찾을 수 없습니다: $Iscc (ISCC_PATH 환경변수로 지정 가능)" }
        & $Iscc "/DAppVersion=$Version" "/DModelVariant=$ModelVariant" "/DExeFileName=$ExeName" (Join-Path $ProjectRoot 'installer.iss')
        if ($LASTEXITCODE -ne 0) { throw 'Inno Setup 빌드에 실패했습니다.' }
        $SetupBase = "BokjiTalkAI_Setup_v${Version}_${ModelVariant}"
        $Setup = Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'dist') -Filter "${SetupBase}.exe" | Select-Object -First 1
        Write-Host ("Installer completed: {0} ({1:N0} bytes)" -f $Setup.FullName, $Setup.Length)
        if ($ModelVariant -eq 'E4B') {
            $ZipPath = Join-Path $ProjectRoot "dist\${SetupBase}.zip"
            if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
            $Parts = Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'dist') -File | Where-Object {
                $_.BaseName -eq $SetupBase -or $_.Name -like "${SetupBase}-*.bin"
            }
            if (-not $Parts) { throw 'E4B 설치 패키지 분할 파일을 찾을 수 없습니다.' }
            Compress-Archive -LiteralPath $Parts.FullName -DestinationPath $ZipPath -CompressionLevel Optimal -Force
            $Zip = Get-Item -LiteralPath $ZipPath
            Write-Host ("E4B ZIP completed: {0} ({1:N0} bytes)" -f $Zip.FullName, $Zip.Length)
        }
    }
} finally {
    Pop-Location
}
