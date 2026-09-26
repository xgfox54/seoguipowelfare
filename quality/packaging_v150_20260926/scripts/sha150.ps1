$ErrorActionPreference='Stop'
$d='C:\Users\xgfox\Documents\Codex\seoguipowelfare-v1.5.0\dist'
$out='C:\Users\xgfox\Documents\Codex\2026-09-24\new-chat-2\work\sha150_raw.txt'
$files = @()
$files += Get-ChildItem $d -File | Where-Object { $_.Name -like 'BokjiTalkAI_Setup_v1.5.0_*' }
$files += Get-ChildItem "$d\BokjiTalkAI_v1.5.0_E2B","$d\BokjiTalkAI_v1.5.0_E4B" -File -Filter '*.exe' -ErrorAction SilentlyContinue
$lines = foreach ($f in $files) { $h = (Get-FileHash -Algorithm SHA256 -LiteralPath $f.FullName).Hash.ToLower(); "$h|$($f.Length)|$($f.FullName)" }
$lines | Set-Content -Encoding UTF8 $out
'DONE' | Set-Content "$out.done"

