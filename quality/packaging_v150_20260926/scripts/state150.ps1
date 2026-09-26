$a="$env:LOCALAPPDATA\BokjiTalkAI"
'--root'; Get-ChildItem $a | Select-Object Name,Length | Format-Table -AutoSize | Out-String -Width 200
'--exe'; (Get-ChildItem $a -Filter '복지업무비서_v*.exe').Name
'--version'; Get-Content "$a\_internal\VERSION"
'--db'; (Get-FileHash "$a\_internal\wiki\kb-v120\welfare.db").Hash
'--uninst'; Get-ChildItem HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall | ForEach-Object { $p=Get-ItemProperty $_.PSPath; if ($p.DisplayName -match '복지톡') { "$($_.PSChildName) | $($p.DisplayName) | $($p.DisplayVersion) | $($p.InstallLocation)" } }
'--lnk'; $sh=New-Object -ComObject WScript.Shell
$l = @(); $l += Get-ChildItem ([Environment]::GetFolderPath('Desktop')) -Filter '*.lnk' ; $l += Get-ChildItem "$env:APPDATA\Microsoft\Windows\Start Menu\Programs" -Recurse -Filter '*.lnk'
foreach ($f in $l) { $t=$sh.CreateShortcut($f.FullName).TargetPath; if ($t -match 'BokjiTalk|복지') { "$($f.FullName) -> $t" } }
'--internal old files'; Get-ChildItem "$a\_internal" -Recurse -File | Where-Object { $_.LastWriteTime -lt (Get-Date '2026-09-26 17:00') -and $_.FullName -notmatch 'welfare.db' } | Measure-Object | Select-Object Count | Out-String

