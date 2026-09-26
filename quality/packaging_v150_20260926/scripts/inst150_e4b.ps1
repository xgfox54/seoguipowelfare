$w='C:\Users\xgfox\Documents\Codex\2026-09-24\new-chat-2\work'
$app=Join-Path $env:LOCALAPPDATA 'BokjiTalkAI_E4B'
$setup='D:\BokjiTalk_upgrade_test\v1.5.0_E4B_zip\BokjiTalkAI_Setup_v1.5.0_E4B.exe'
"before: dir=" + (Test-Path $app)
if (Test-Path $app) { 'E4B folder already exists, stop'; exit 1 }
$t=Get-Date
$p = Start-Process -FilePath $setup -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',"/LOG=$w\inst150_E4B.log" -Wait -PassThru
"install exit=$($p.ExitCode) sec=" + [int]((Get-Date)-$t).TotalSeconds
"exes: " + ((Get-ChildItem $app -Filter '*.exe' | Select-Object -ExpandProperty Name) -join ', ')
"VERSION: " + (Get-Content "$app\_internal\VERSION")
"models: " + ((Get-ChildItem "$app\models" | ForEach-Object { "$($_.Name) $($_.Length)" }) -join ', ')
"db sha: " + (Get-FileHash "$app\_internal\wiki\kb-v120\welfare.db").Hash
Get-ChildItem HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall | ForEach-Object { $x=Get-ItemProperty $_.PSPath; if ($x.DisplayName -match '복지톡') { "uninst: $($_.PSChildName) | $($x.DisplayName) | $($x.DisplayVersion) | $($x.InstallLocation)" } }
$sh=New-Object -ComObject WScript.Shell; $l=@(); $l += Get-ChildItem ([Environment]::GetFolderPath('Desktop')) -Filter '*.lnk'; $l += Get-ChildItem "$env:APPDATA\Microsoft\Windows\Start Menu\Programs" -Recurse -Filter '*.lnk'
foreach ($f in $l) { $tg=$sh.CreateShortcut($f.FullName).TargetPath; if ($tg -match 'BokjiTalk') { "lnk: $($f.Name) -> $tg" } }

