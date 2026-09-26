$app = Join-Path $env:LOCALAPPDATA 'BokjiTalkAI'
$key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{7E4B2C1A-9D3F-4A6B-8C5E-2F1D0B9A7E63}_is1'
function Show-State($label) {
  "== $label"
  'app dir: ' + (Test-Path $app)
  if (Test-Path $app) { 'exes: ' + ((Get-ChildItem $app -Filter '*.exe' | Where-Object Name -ne 'unins000.exe' | Select-Object -ExpandProperty Name) -join ', '); 'files: ' + (Get-ChildItem $app -Recurse -File).Count }
  if (Test-Path $key) { $v = Get-ItemProperty $key; 'uninstall: ' + $v.DisplayName + ' | ' + $v.DisplayVersion } else { 'uninstall: none' }
  $desk=[Environment]::GetFolderPath('Desktop'); $l = Get-ChildItem $desk -Filter '*.lnk' | Where-Object Name -like '복지톡AI*'
  foreach ($x in $l) { $sh = (New-Object -ComObject WScript.Shell).CreateShortcut($x.FullName); 'desktop lnk: ' + $x.Name + ' -> ' + (Split-Path $sh.TargetPath -Leaf) }
}
$t=Get-Date; $p = Start-Process -FilePath 'C:\Users\xgfox\Documents\Codex\seoguipowelfare-v1.5.0\dist\BokjiTalkAI_Setup_v1.5.0_E2B.exe' -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-','/LOG=C:\Users\xgfox\Documents\Codex\2026-09-24\new-chat-2\work\upg_install_v150.log' -Wait -PassThru -WindowStyle Hidden
'v1.5.0 upgrade install exit ' + $p.ExitCode + ' ' + [int]((Get-Date)-$t).TotalSeconds + 's'
Show-State 'after v1.5.0 upgrade'
'uninstall entries named 복지톡AI: ' + ((Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall' | ForEach-Object { Get-ItemProperty $_.PSPath } | Where-Object { $_.DisplayName -like '복지톡AI*' }) | Measure-Object).Count
'_internal VERSION: ' + (Get-Content (Join-Path $app '_internal\VERSION'))
'db ' + (Get-FileHash (Join-Path $app '_internal\wiki\kb-v120\welfare.db')).Hash
'exe ' + (Get-FileHash (Join-Path $app '복지업무비서_v1.5.0_E2B.exe')).Hash
$sm = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'; Get-ChildItem $sm -Recurse -Filter '*.lnk' | Where-Object FullName -like '*복지톡AI*' | ForEach-Object { $sh = (New-Object -ComObject WScript.Shell).CreateShortcut($_.FullName); 'start lnk: ' + $_.Name + ' -> ' + (Split-Path $sh.TargetPath -Leaf) }
