Set-Location 'C:\Users\xgfox\Documents\Codex\seoguipowelfare-v1.5.0'
$env:PYTHONDONTWRITEBYTECODE='1'
& powershell -NoProfile -ExecutionPolicy Bypass -File 'C:\Users\xgfox\Documents\Codex\seoguipowelfare-v1.5.0\build-exe.ps1' -ModelVariant E2B *> 'C:\Users\xgfox\Documents\Codex\2026-09-24\new-chat-2\work\build150_e2b.log'
"EXIT=$LASTEXITCODE" | Out-File 'C:\Users\xgfox\Documents\Codex\2026-09-24\new-chat-2\work\build150_e2b.exit'
if (Test-Path 'C:\Users\xgfox\Documents\Codex\seoguipowelfare-v1.5.0\dist\welfare_assistant') { Move-Item -LiteralPath 'C:\Users\xgfox\Documents\Codex\seoguipowelfare-v1.5.0\dist\welfare_assistant' -Destination 'C:\Users\xgfox\Documents\Codex\seoguipowelfare-v1.5.0\dist\BokjiTalkAI_v1.5.0_E2B' }
& powershell -NoProfile -ExecutionPolicy Bypass -File 'C:\Users\xgfox\Documents\Codex\seoguipowelfare-v1.5.0\build-exe.ps1' -ModelVariant E4B *> 'C:\Users\xgfox\Documents\Codex\2026-09-24\new-chat-2\work\build150_e4b.log'
"EXIT=$LASTEXITCODE" | Out-File 'C:\Users\xgfox\Documents\Codex\2026-09-24\new-chat-2\work\build150_e4b.exit'
if (Test-Path 'C:\Users\xgfox\Documents\Codex\seoguipowelfare-v1.5.0\dist\welfare_assistant') { Move-Item -LiteralPath 'C:\Users\xgfox\Documents\Codex\seoguipowelfare-v1.5.0\dist\welfare_assistant' -Destination 'C:\Users\xgfox\Documents\Codex\seoguipowelfare-v1.5.0\dist\BokjiTalkAI_v1.5.0_E4B' }
"DONE" | Out-File 'C:\Users\xgfox\Documents\Codex\2026-09-24\new-chat-2\work\build150.done'
