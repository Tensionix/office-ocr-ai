@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Audion Office OCR AI - Verify
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
for %%A in ("%SCRIPT_DIR%\..") do set "ROOT=%%~fA"
rem What a release is checked for. The environment: Python and the packages of
rem the engine. The door: it reads the manifest. The window: App\ is not built
rem by a build and travels as it is, so it is checked to be in place and to
rem check itself - its markup, its forms, every field of the manifest of this
rem version. Tesseract is said, not required: without it the local OCR is limited
rem and the rest works. Nothing here needs the .NET SDK.
if not exist "%ROOT%\runtime\python.exe" goto ERR_PYTHON
if not exist "%ROOT%\system_core\doctor.py" goto ERR_DOCTOR
call "%ROOT%\install\Check-CmdEncoding.cmd"
if errorlevel 1 goto ERR_CMD_ENCODING
"%ROOT%\runtime\python.exe" "%ROOT%\system_core\doctor.py" --project-root "%ROOT%"
set "RC=%errorlevel%"
if not "%RC%"=="0" goto DONE_VERIFY
rem The console door must read the manifest: the window draws by what it prints.
echo.
echo [DOOR] Reading the manifest through the console door...
"%ROOT%\runtime\python.exe" -u "%ROOT%\system_core\cli.py" describe >nul
set "RC=%errorlevel%"
if not "%RC%"=="0" goto ERR_DOOR
echo [OK] The door reads the manifest.
echo.
echo [TESSERACT] The local OCR...
if exist "%ROOT%\runtime\tesseract\tesseract.exe" echo [OK] Tesseract is in place: runtime\tesseract
if not exist "%ROOT%\runtime\tesseract\tesseract.exe" echo [WARN] Tesseract is not in place: the local OCR is limited - install\Install-Portable-Tesseract.cmd
echo.
echo [WINDOW] Checking the built window in App\ ...
set "RC=1"
if not exist "%ROOT%\Start.exe" goto ERR_START
"%ROOT%\Start.exe" --self-test
if errorlevel 1 goto ERR_APP
if not exist "%ROOT%\App\AudionPs.exe" goto ERR_APP
set "CHECK_FILE=%TEMP%\office_ocr_self_test_%RANDOM%%RANDOM%.txt"
start "" /wait "%ROOT%\App\AudionOfficeOcrAi.exe" --self-test --to "%CHECK_FILE%"
set "CHECK_RC=%errorlevel%"
if not "%CHECK_RC%"=="0" goto ERR_SELF_CHECK
if not exist "%CHECK_FILE%" goto ERR_SELF_CHECK
"%ROOT%\App\AudionPs.exe" -NoLogo -NoProfile -NonInteractive -Command "$lines = Get-Content -LiteralPath '%CHECK_FILE%'; $ok = @($lines | Where-Object { $_ -match '^ok ' }).Count; Write-Host ('[OK] The window checked itself: ' + $ok + ' checks held.')"
del /f /q "%CHECK_FILE%" "%CHECK_FILE%.sent.json" >nul 2>nul
set "RC=0"
:DONE_VERIFY
if not defined AUDION_NO_PAUSE pause
exit /b %RC%
:ERR_PYTHON
echo [ERROR] runtime\python.exe was not found.
if not defined AUDION_NO_PAUSE pause
exit /b 1
:ERR_DOCTOR
echo [ERROR] doctor.py was not found.
if not defined AUDION_NO_PAUSE pause
exit /b 1
:ERR_CMD_ENCODING
echo [ERROR] CMD encoding check failed.
if not defined AUDION_NO_PAUSE pause
exit /b 1
:ERR_DOOR
echo [ERROR] The console door did not read the manifest: system_core\cli.py describe
if not defined AUDION_NO_PAUSE pause
exit /b 1
:ERR_START
echo [ERROR] Start.exe was not found: install\Build-StartLauncher.cmd
if not defined AUDION_NO_PAUSE pause
exit /b 1
:ERR_APP
echo [ERROR] App\AudionOfficeOcrAi.exe or App\AudionPs.exe was not found: install\Build-App.cmd
if not defined AUDION_NO_PAUSE pause
exit /b 1
:ERR_SELF_CHECK
echo [ERROR] The window did not pass its own check (exit code %CHECK_RC%): run App\AudionOfficeOcrAi.exe --self-test --to report.txt
if not defined AUDION_NO_PAUSE pause
exit /b 1
