@echo off
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0복지업무비서-종료.ps1"
set "exit_code=%errorlevel%"
if not "%exit_code%"=="0" (
  echo.
  echo 종료 중 오류가 발생했습니다. 위 내용을 확인해 주세요.
  pause
)
exit /b %exit_code%
