$app = Join-Path $env:LOCALAPPDATA 'BokjiTalkAI'
& (Join-Path $app '복지업무비서_v1.4.0_E2B.exe')
$t=Get-Date; $ok=$false
do { Start-Sleep -Seconds 2; try { $st = Invoke-RestMethod http://127.0.0.1:8765/api/status -TimeoutSec 2; $ok = $st.ai_ready } catch {} } until ($ok -or ((Get-Date)-$t).TotalSeconds -gt 120)
'v1.4.0 ready ' + $ok + ' version ' + $st.app_version + ' model ' + $st.model
try { Invoke-RestMethod -Method Post http://127.0.0.1:8765/api/shutdown -TimeoutSec 5 | Out-Null; 'shutdown sent' } catch { 'shutdown err ' + $_.Exception.Message }
Start-Sleep -Seconds 4
$p = Get-Process | Where-Object { $_.Path -like "$app*" }; foreach ($x in $p) { [void]$x.CloseMainWindow() }; Start-Sleep -Seconds 5
$p = Get-Process | Where-Object { $_.Path -like "$app*" }; if ($p) { $p | Stop-Process -Force; 'forced' } else { 'closed' }
