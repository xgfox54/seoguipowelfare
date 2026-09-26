$app=Join-Path $env:LOCALAPPDATA 'BokjiTalkAI_E4B'
$procs = Get-Process | Where-Object { $_.Path -like "$app*" }
"app procs before close: " + @($procs).Count
foreach ($x in $procs) { [void]$x.CloseMainWindow() }
Start-Sleep -Seconds 8
"after window close: app procs=" + @(Get-Process | Where-Object { $_.Path -like "$app*" }).Count + " llama=" + @(Get-Process | Where-Object { $_.ProcessName -match 'llama' }).Count
"log question text hits: " + @(Select-String -Path "$app\logs\*.log" -Pattern '긴급복지 생계지원 4인|소득기준' -Encoding UTF8).Count
$t=Get-Date
$u = Start-Process -FilePath "$app\unins000.exe" -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -Wait -PassThru
Start-Sleep -Seconds 8
"uninstall exit=$($u.ExitCode) sec=" + [int]((Get-Date)-$t).TotalSeconds
"after uninstall: dir=" + (Test-Path $app)
if (Test-Path $app) { Get-ChildItem $app -Recurse | Select-Object -First 20 -ExpandProperty FullName }
"uninst keys (all 복지톡): " + @(Get-ChildItem HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall | Where-Object { (Get-ItemProperty $_.PSPath).DisplayName -match '복지톡' }).Count
"desktop lnk: " + (Test-Path ([IO.Path]::Combine([Environment]::GetFolderPath('Desktop'),'복지톡AI 복지업무비서 E4B.lnk')))
"startmenu dir: " + (Test-Path "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\복지톡AI 복지업무비서 E4B")

