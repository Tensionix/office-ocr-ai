@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

title Audion Office OCR AI - Builder

set "BASE_DIR=%~dp0"
if "%BASE_DIR:~-1%"=="\" set "BASE_DIR=%BASE_DIR:~0,-1%"
cd /d "%BASE_DIR%"

rem What a build is for: fresh components. Step 01 or 02 brings back the current Python 3.12 and the
rem packages of install\requirements_full.in; steps 10-17 bring the local engines of OCR one by one.
rem Nothing else is downloaded.
rem
rem App\ - the window and the PowerShell the program carries - is not a product of a build: it stays
rem through a cleanup and travels in a release as it is. Step 04 rebuilds it and is for the day
rem Source\ changes (.NET 10 SDK); a release build does not need the SDK. Step 03 rebuilds Start.exe.
rem
rem Until 2.0.0 this menu had FZF, a portable PowerShell, the licences, the release archive and the
rem menus of the project: the console menus went with the window on NiceGUI; the licences are
rem collected by Audion Build Licenses and the release is made by Audion Build Publisher.
rem
rem Step bodies are read by the orchestrator, not only run from the menu: it cuts everything
rem between a label and `goto MAIN` into its own batch file where only BASE_DIR is set. So a body
rem must stand alone.

set /a EMPTY_TRIES=0

:MAIN
set /a EMPTY_TRIES+=1
rem Without a console the prompt reads nothing and the menu would redraw for ever. Three empty
rem answers in a row mean there is nobody to ask.
if !EMPTY_TRIES! GTR 3 (
  echo [ERROR] No input available - run the builder from a console.
  exit /b 2
)
cls
echo ======================================================================
echo   Audion Office OCR AI - builder
echo ======================================================================
echo Root: %BASE_DIR%
echo.

if defined AUDION_AUTO_EXIT (
  echo [SMOKE] AUDION_AUTO_EXIT is set. Exiting before menu interaction.
  exit /b 0
)

echo [01] PYTHON ENV CMD                        ^| build_cmd                ^| build portable runtime via CMD
echo [02] PYTHON ENV PS                         ^| build_ps                 ^| build portable runtime via PowerShell
echo [03] START LAUNCHER                        ^| build_launcher           ^| rebuild Start.exe
echo [04] WINDOW                                ^| build_app                ^| rebuild App\ - only after a change in Source\
echo [09] PORTABLE OFFLINE                      ^| install_offline          ^| install from local runtime/wheelhouse
echo.
echo [10] TESSERACT                             ^| install_tess             ^| install portable Tesseract
echo [11] REAL-ESRGAN VULKAN                    ^| install_realesrgan       ^| install portable image cleanup/upscale engine
echo [12] LLAMA.CPP VULKAN                      ^| install_llamacpp_vulkan  ^| install portable Vulkan llama-server for Surya
echo [13] SURYA CPU OCR                         ^| install_surya_cpu        ^| install optional Surya runtime
echo [14] LLAMA.CPP CUDA 12.4                   ^| install_llamacpp_cuda124 ^| NVIDIA llama-server CUDA 12.4
echo [15] LLAMA.CPP CUDA 13.3                   ^| install_llamacpp_cuda133 ^| NVIDIA llama-server CUDA 13.3
echo [16] SURYA PYTORCH CUDA 40XX               ^| install_surya_cuda40     ^| heavy optional Surya CUDA runtime
echo [17] SURYA PYTORCH CUDA 50XX               ^| install_surya_cuda50     ^| heavy optional Surya CUDA runtime
echo.
echo [70] CLEAN INSTALL CACHE                   ^| clean_cache              ^| install cache, bytecode, bin and obj of Source
echo [71] VERIFY / DOCTOR                       ^| verify                   ^| check the environment and the built window
echo [72] CMD ENCODING CHECK                    ^| cmd_encoding             ^| UTF-8 no-BOM CRLF
echo [73] UPDATE REQUIREMENTS LOCK              ^| update_req_lock          ^| compile requirements_lock.txt
echo.
echo [95] OPEN install                          ^| open_install             ^| explorer install
echo [96] OPEN runtime                          ^| open_runtime             ^| explorer runtime
echo [97] OPEN wheelhouse                       ^| open_wheels              ^| explorer wheelhouse
echo [98] OPEN licenses                         ^| open_licenses            ^| explorer licenses
echo.
echo [00] EXIT                                  ^| exit                     ^| close builder
echo.
set "RAW="
set /p RAW="Select step number or id: "
call :TRIM RAW
if not defined RAW goto MAIN
set /a EMPTY_TRIES=0
if /I "%RAW%"=="01" goto BUILD_CMD
if /I "%RAW%"=="1" goto BUILD_CMD
if /I "%RAW%"=="build_cmd" goto BUILD_CMD
if /I "%RAW%"=="02" goto BUILD_PS
if /I "%RAW%"=="2" goto BUILD_PS
if /I "%RAW%"=="build_ps" goto BUILD_PS
if /I "%RAW%"=="03" goto BUILD_LAUNCHER
if /I "%RAW%"=="3" goto BUILD_LAUNCHER
if /I "%RAW%"=="build_launcher" goto BUILD_LAUNCHER
if /I "%RAW%"=="04" goto BUILD_APP
if /I "%RAW%"=="4" goto BUILD_APP
if /I "%RAW%"=="build_app" goto BUILD_APP
if /I "%RAW%"=="09" goto INSTALL_OFFLINE
if /I "%RAW%"=="9" goto INSTALL_OFFLINE
if /I "%RAW%"=="install_offline" goto INSTALL_OFFLINE
if /I "%RAW%"=="10" goto INSTALL_TESSERACT
if /I "%RAW%"=="install_tess" goto INSTALL_TESSERACT
if /I "%RAW%"=="11" goto INSTALL_REALESRGAN
if /I "%RAW%"=="install_realesrgan" goto INSTALL_REALESRGAN
if /I "%RAW%"=="12" goto INSTALL_LLAMACPP_VULKAN
if /I "%RAW%"=="install_llamacpp_vulkan" goto INSTALL_LLAMACPP_VULKAN
if /I "%RAW%"=="13" goto INSTALL_SURYA_CPU
if /I "%RAW%"=="install_surya_cpu" goto INSTALL_SURYA_CPU
if /I "%RAW%"=="14" goto INSTALL_LLAMACPP_CUDA124
if /I "%RAW%"=="install_llamacpp_cuda124" goto INSTALL_LLAMACPP_CUDA124
if /I "%RAW%"=="15" goto INSTALL_LLAMACPP_CUDA133
if /I "%RAW%"=="install_llamacpp_cuda133" goto INSTALL_LLAMACPP_CUDA133
if /I "%RAW%"=="16" goto INSTALL_SURYA_CUDA40
if /I "%RAW%"=="install_surya_cuda40" goto INSTALL_SURYA_CUDA40
if /I "%RAW%"=="17" goto INSTALL_SURYA_CUDA50
if /I "%RAW%"=="install_surya_cuda50" goto INSTALL_SURYA_CUDA50
if /I "%RAW%"=="70" goto CLEAN_CACHE
if /I "%RAW%"=="clean_cache" goto CLEAN_CACHE
if /I "%RAW%"=="71" goto VERIFY
if /I "%RAW%"=="verify" goto VERIFY
if /I "%RAW%"=="72" goto CMD_ENCODING
if /I "%RAW%"=="cmd_encoding" goto CMD_ENCODING
if /I "%RAW%"=="73" goto UPDATE_REQ_LOCK
if /I "%RAW%"=="update_req_lock" goto UPDATE_REQ_LOCK
if /I "%RAW%"=="95" goto OPEN_INSTALL
if /I "%RAW%"=="open_install" goto OPEN_INSTALL
if /I "%RAW%"=="96" goto OPEN_RUNTIME
if /I "%RAW%"=="open_runtime" goto OPEN_RUNTIME
if /I "%RAW%"=="97" goto OPEN_WHEELS
if /I "%RAW%"=="open_wheels" goto OPEN_WHEELS
if /I "%RAW%"=="98" goto OPEN_LICENSES
if /I "%RAW%"=="open_licenses" goto OPEN_LICENSES
if /I "%RAW%"=="00" exit /b 0
if /I "%RAW%"=="0" exit /b 0
if /I "%RAW%"=="exit" exit /b 0
goto MAIN

:BUILD_CMD
call "%BASE_DIR%\install\Build_Portable_Env_Build.cmd"
goto MAIN

:BUILD_PS
call "%BASE_DIR%\install\Build_Portable_Env.cmd"
goto MAIN

:BUILD_LAUNCHER
call "%BASE_DIR%\install\Build-StartLauncher.cmd"
goto MAIN

:BUILD_APP
call "%BASE_DIR%\install\Build-App.cmd" /NOPAUSE
goto MAIN

:INSTALL_OFFLINE
call "%BASE_DIR%\install\install_portable_offline.cmd"
goto MAIN

:INSTALL_TESSERACT
call "%BASE_DIR%\install\Install-Portable-Tesseract.cmd"
goto MAIN

:INSTALL_REALESRGAN
call "%BASE_DIR%\install\Install-Portable-RealESRGAN.cmd"
goto MAIN

:INSTALL_LLAMACPP_VULKAN
call "%BASE_DIR%\install\Install-Portable-LlamaCpp.cmd" -Variant vulkan
goto MAIN

:INSTALL_SURYA_CPU
call "%BASE_DIR%\install\Install-Optional-OCREngines.cmd" -Engine surya -Mode cpu
goto MAIN

:INSTALL_LLAMACPP_CUDA124
call "%BASE_DIR%\install\Install-Portable-LlamaCpp.cmd" -Variant cuda124
goto MAIN

:INSTALL_LLAMACPP_CUDA133
call "%BASE_DIR%\install\Install-Portable-LlamaCpp.cmd" -Variant cuda133
goto MAIN

:INSTALL_SURYA_CUDA40
call "%BASE_DIR%\install\Install-Optional-OCREngines.cmd" -Engine surya -Mode cuda40
goto MAIN

:INSTALL_SURYA_CUDA50
call "%BASE_DIR%\install\Install-Optional-OCREngines.cmd" -Engine surya -Mode cuda50
goto MAIN

:CLEAN_CACHE
call "%BASE_DIR%\install\Clean-Install-Cache.cmd"
goto MAIN

:VERIFY
call "%BASE_DIR%\install\verify_portable_env.cmd"
goto MAIN

:CMD_ENCODING
call "%BASE_DIR%\install\Check-CmdEncoding.cmd" -Fix
set "RC=%errorlevel%"
echo.
echo [INFO] CMD encoding repair finished with exit code %RC%.
echo [INFO] Restart builder_main.cmd before continuing: a file that was fixed is read anew only then.
if not defined AUDION_NO_PAUSE pause
exit /b %RC%
goto MAIN

:UPDATE_REQ_LOCK
call "%BASE_DIR%\install\Update-Requirements-Lock.cmd"
goto MAIN

:OPEN_INSTALL
start "" explorer "%BASE_DIR%\install"
goto MAIN

:OPEN_RUNTIME
start "" explorer "%BASE_DIR%\runtime"
goto MAIN

:OPEN_WHEELS
start "" explorer "%BASE_DIR%\wheelhouse"
goto MAIN

:OPEN_LICENSES
if not exist "%BASE_DIR%\licenses" mkdir "%BASE_DIR%\licenses" >nul 2>nul
start "" explorer "%BASE_DIR%\licenses"
goto MAIN

:TRIM
for /f "tokens=* delims= " %%z in ("!%~1!") do set "%~1=%%z"
:TRIM_R
if "!%~1:~-1!"==" " set "%~1=!%~1:~0,-1!" & goto TRIM_R
goto :eof
