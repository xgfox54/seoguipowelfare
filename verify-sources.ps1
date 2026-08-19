[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Source = Join-Path $ProjectRoot 'source-md'
$Downloads = Join-Path $HOME 'Downloads'
$ExpectedCount = 38
$ExpectedBytes = 61234862

function Get-FileMap([string]$Root) {
    $map = @{}
    foreach ($file in @(Get-ChildItem -LiteralPath $Root -File -Filter '*.md')) {
        $map[$file.Name] = [pscustomobject]@{
            Length = $file.Length
            Hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    return $map
}

if (-not (Test-Path -LiteralPath $Source)) { throw "Project source directory not found: $Source" }
$sourceMap = Get-FileMap $Source
$candidateDirs = @(Get-ChildItem -LiteralPath $Downloads -Directory -ErrorAction Stop | Where-Object {
    $files = @(Get-ChildItem -LiteralPath $_.FullName -File -Filter '*.md' -ErrorAction SilentlyContinue)
    $files.Count -eq $ExpectedCount -and (($files | Measure-Object -Property Length -Sum).Sum -eq $ExpectedBytes)
})
if ($candidateDirs.Count -ne 1) {
    throw "Could not uniquely identify the original 38-file source directory under $Downloads."
}
$Original = $candidateDirs[0].FullName
$originalMap = Get-FileMap $Original
$errors = [System.Collections.Generic.List[string]]::new()

foreach ($name in $sourceMap.Keys) {
    if (-not $originalMap.ContainsKey($name)) {
        $errors.Add("Missing from original: $name")
        continue
    }
    if ($sourceMap[$name].Length -ne $originalMap[$name].Length -or $sourceMap[$name].Hash -ne $originalMap[$name].Hash) {
        $errors.Add("Content mismatch: $name")
    }
}
foreach ($name in $originalMap.Keys) {
    if (-not $sourceMap.ContainsKey($name)) { $errors.Add("Missing from project copy: $name") }
}

Write-Host ("Original files: {0}" -f $originalMap.Count)
Write-Host ("Project copies: {0}" -f $sourceMap.Count)
Write-Host ("Project bytes: {0}" -f (($sourceMap.Values | Measure-Object -Property Length -Sum).Sum))
Write-Host ("Original directory: {0}" -f $Original)
if ($errors.Count -gt 0) {
    $errors | ForEach-Object { Write-Error $_ }
    exit 1
}
Write-Host 'Source integrity verified: all files match by size and SHA-256.'
