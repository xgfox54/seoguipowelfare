$a="$env:LOCALAPPDATA\BokjiTalkAI"
$p = Get-Process | Where-Object { $_.Path -like "$a*" -or $_.ProcessName -match 'llama' }
'running before uninstall: ' + (@($p).Count)
$sw=[Diagnostics.Stopwatch]::StartNew()
Start-Process -FilePath "$a\unins000.exe" -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -Wait
Start-Sleep 8
'uninstall sec ' + [math]::Round($sw.Elapsed.TotalSeconds,1)
'folder exists: ' + (Test-Path $a)
if (Test-Path $a) { Get-ChildItem $a -Recurse | Select-Object FullName | Out-String }
'uninst keys: ' + (@(Get-ChildItem HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall | Where-Object { (Get-ItemProperty $_.PSPath).DisplayName -match '복지톡' }).Count)
'desktop lnk: ' + (Test-Path ([IO.Path]::Combine([Environment]::GetFolderPath('Desktop'),'복지톡AI 복지업무비서.lnk')))
'startmenu dir: ' + (Test-Path "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\복지톡AI 복지업무비서")
Get-PSDrive C,D,G -ErrorAction SilentlyContinue | Select-Object Name,@{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}} | Out-String

