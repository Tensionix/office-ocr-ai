@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

title Audion Office OCR AI - Install Portable Real-ESRGAN ncnn-vulkan

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
for %%A in ("%SCRIPT_DIR%\..") do set "ROOT=%%~fA"

set "NO_PAUSE=0"
set "PS_ARGS="
for %%A in (%*) do (
  if /I "%%~A"=="/NOPAUSE" set "NO_PAUSE=1"
  if /I "%%~A"=="--no-pause" set "NO_PAUSE=1"
  if /I not "%%~A"=="/NOPAUSE" if /I not "%%~A"=="--no-pause" set "PS_ARGS=!PS_ARGS! "%%~A""
)

set "PS_EXE="
if exist "%ROOT%\system_core\powershell\pwsh.exe" set "PS_EXE=%ROOT%\system_core\powershell\pwsh.exe"
if not defined PS_EXE (
  where pwsh.exe >nul 2>nul
  if not errorlevel 1 set "PS_EXE=pwsh.exe"
)
if not defined PS_EXE (
  where powershell.exe >nul 2>nul
  if not errorlevel 1 set "PS_EXE=powershell.exe"
)
if not defined PS_EXE goto ERR_POWERSHELL

"%PS_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%\Install-Portable-RealESRGAN.ps1" %PS_ARGS%
set "RC=%errorlevel%"
if not "%NO_PAUSE%"=="1" pause
exit /b %RC%

:ERR_POWERSHELL
echo [ERROR] PowerShell was not found. Install portable PowerShell or enable Windows PowerShell.
if not "%NO_PAUSE%"=="1" pause
exit /b 1
