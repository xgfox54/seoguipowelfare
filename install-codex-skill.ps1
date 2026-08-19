[CmdletBinding()]
param(
    [switch]$UseCopy
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Skill = Join-Path $ProjectRoot 'output\skills\welfare-work-assistant'
$CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
$Dest = Join-Path $CodexHome 'skills\welfare-work-assistant'

if (-not (Test-Path -LiteralPath (Join-Path $Skill 'SKILL.md'))) {
    throw "Generated Skill not found: $Skill. Run .\setup-openkb.ps1 first."
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Dest) | Out-Null
if (Test-Path -LiteralPath $Dest) {
    Write-Host "Existing destination found; leaving it unchanged: $Dest"
    exit 0
}

if ($UseCopy) {
    Copy-Item -Recurse -Force -LiteralPath $Skill -Destination $Dest
    Write-Host "Copied Skill to $Dest"
} else {
    try {
        New-Item -ItemType SymbolicLink -Path $Dest -Target $Skill | Out-Null
        Write-Host "Linked Skill at $Dest"
    } catch {
        Write-Warning 'Symbolic link creation was unavailable; use -UseCopy to install a copied Skill.'
        throw
    }
}
