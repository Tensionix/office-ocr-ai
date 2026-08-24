@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

set "PS_EXE="
set "PS1_FILE=%~dpn0.ps1"
set "NO_PAUSE=0"

:ARG_LOOP
if "%~1"=="" goto ARGS_DONE
if /I "%~1"=="/NOPAUSE" set "NO_PAUSE=1" & shift & goto ARG_LOOP
if /I "%~1"=="--no-pause" set "NO_PAUSE=1" & shift & goto ARG_LOOP
if /I "%~1"=="/?" goto usage
if /I "%~1"=="-h" goto usage
if /I "%~1"=="--help" goto usage
shift
goto ARG_LOOP
:ARGS_DONE

if exist "%~dp0..\system_core\powershell\pwsh.exe" set "PS_EXE=%~dp0..\system_core\powershell\pwsh.exe"
if not defined PS_EXE where pwsh.exe >nul 2>nul && set "PS_EXE=pwsh.exe"
if not defined PS_EXE where powershell.exe >nul 2>nul && set "PS_EXE=powershell.exe"

if not defined PS_EXE (
    echo [ERROR] PowerShell was not found.
    echo [INFO] Expected portable path:
    echo %~dp0..\system_core\powershell\pwsh.exe
    if not "%NO_PAUSE%"=="1" pause
    exit /b 1
)

"%PS_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%PS1_FILE%"
set "RC=%errorlevel%"

echo.
if "%RC%"=="0" (
    echo [OK] Build_Portable_Env.ps1 finished successfully.
) else (
    echo [ERROR] Build_Portable_Env.ps1 finished with exit code %RC%.
)

if not "%NO_PAUSE%"=="1" pause
exit /b %RC%

:usage
echo Usage:
echo   Build_Portable_Env.cmd [/NOPAUSE]
echo.
echo Options:
echo   /NOPAUSE, --no-pause    Return immediately after the PowerShell build exits.
exit /b 0
