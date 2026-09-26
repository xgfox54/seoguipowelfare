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
if (Test-Path $app) { throw 'production install already exists' }
$t=Get-Date; $p = Start-Process -FilePath 'D:\BokjiTalk_upgrade_test\v1.4.0_src\dist\BokjiTalkAI_Setup_v1.4.0_E2B.exe' -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-','/LOG=C:\Users\xgfox\Documents\Codex\2026-09-24\new-chat-2\work\upg_install_v140.log' -Wait -PassThru -WindowStyle Hidden
'v1.4.0 install exit ' + $p.ExitCode + ' ' + [int]((Get-Date)-$t).TotalSeconds + 's'
Show-State 'after v1.4.0 install'
