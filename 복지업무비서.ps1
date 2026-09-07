[CmdletBinding()]
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$Question,
    [switch]$Status
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot '.venv-openkb\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $Python)) {
    throw '복지업무 비서 실행환경이 없습니다. setup-openkb.ps1을 먼저 실행하세요.'
}

$env:PYTHONUTF8 = '1'
$env:WELFARE_LLM_PORT = '18080'
Push-Location $ProjectRoot
try {
    $ProcessExitCode = 0
    if ($Status) {
        & $Python 'welfare_assistant.py' 'status'
        $ProcessExitCode = $LASTEXITCODE
    } elseif ($Question.Count -gt 0) {
        & $Python 'welfare_assistant.py' 'ask' ($Question -join ' ')
        $ProcessExitCode = $LASTEXITCODE
    } else {
        Write-Host '개인용 복지업무 비서'
        Write-Host '끝내려면 빈 줄에서 Enter를 누르세요.'
        while ($true) {
            $InputQuestion = Read-Host '질문'
            if ([string]::IsNullOrWhiteSpace($InputQuestion)) { break }
            & $Python 'welfare_assistant.py' 'ask' $InputQuestion
            $ProcessExitCode = $LASTEXITCODE
            if ($ProcessExitCode -ne 0) { throw '복지업무 비서 질의에 실패했습니다.' }
            Write-Host ''
        }
    }
    if ($ProcessExitCode -ne 0) { throw '복지업무 비서 실행에 실패했습니다.' }
} finally {
    Pop-Location
}
