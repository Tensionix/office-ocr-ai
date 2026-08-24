@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

title Audion Office OCR AI - Проектный запуск

set "BASE_DIR=%~dp0"
if "%BASE_DIR:~-1%"=="\" set "BASE_DIR=%BASE_DIR:~0,-1%"
cd /d "%BASE_DIR%"

set "CORE_DIR=%BASE_DIR%\system_core"
set "INSTALL_DIR=%BASE_DIR%\install"
set "FZF_EXE=%CORE_DIR%\fzf.exe"
set "RUNTIME_DIR=%BASE_DIR%\._runtime"
set "MENU_FILE=%RUNTIME_DIR%\project_menu.txt"
set "RES_FILE=%RUNTIME_DIR%\project_menu_res.txt"

if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%" >nul 2>nul

call :RESOLVE_PYTHON
if errorlevel 1 goto NO_PYTHON

:MAIN
cls
echo ======================================================================
echo   AUDION OFFICE OCR AI - ПРОЕКТНЫЙ ЗАПУСК
echo ======================================================================
echo Корень: %BASE_DIR%
echo Python: %PYTHON_CMD% %PYTHON_ARGS%
echo.

if exist "%FZF_EXE%" goto FZF_MENU
goto FALLBACK_MENU

:FZF_MENU
> "%MENU_FILE%" echo [01] ОФИСНЫЙ ТЕКСТ БЕЗ OCR                   ^| extract_fast             ^| GUI service: выделяемый текст в Markdown
>>"%MENU_FILE%" echo [02] ЛОКАЛЬНЫЙ OCR - TESSERACT               ^| ocr_tesseract            ^| OCR Brick в DocumentModel + DOCX
>>"%MENU_FILE%" echo [03] ЛОКАЛЬНЫЙ OCR - SURYA                   ^| ocr_surya                ^| OCR Brick layout + DOCX
>>"%MENU_FILE%" echo [04] API OCR - YANDEX                        ^| ocr_yandex               ^| OCR Brick Yandex + DOCX
>>"%MENU_FILE%" echo [05] API OCR - MISTRAL                       ^| ocr_mistral              ^| OCR Brick Mistral + DOCX
>>"%MENU_FILE%" echo.
>>"%MENU_FILE%" echo [06] API OCR - XAI                           ^| ocr_xai                  ^| OCR Brick xAI + DOCX
>>"%MENU_FILE%" echo [07] API OCR - GEMINI                        ^| ocr_gemini               ^| OCR Brick Gemini + DOCX
>>"%MENU_FILE%" echo [08] API OCR - OPENAI                        ^| ocr_openai               ^| OCR Brick OpenAI + DOCX
>>"%MENU_FILE%" echo [09] WORKBENCH: ЛОКАЛЬНАЯ ПРОВЕРКА           ^| workbench_review         ^| локальные review-артефакты
>>"%MENU_FILE%" echo [10] WORKBENCH: OPENAI RESOLVER              ^| workbench_openai         ^| repair-only по crop-зонам
>>"%MENU_FILE%" echo [11] WORKBENCH: GEMINI RESOLVER              ^| workbench_gemini         ^| repair-only по crop-зонам
>>"%MENU_FILE%" echo [12] WORKBENCH: КООРДИНАТЫ                   ^| workbench_coordinates    ^| экспорт координатных таблиц
>>"%MENU_FILE%" echo [13] MISTRAL + YANDEX + TESSERACT            ^| ocr_mistral_fusion       ^| проверяемый fusion + DOCX/отчёт
>>"%MENU_FILE%" echo.
>>"%MENU_FILE%" echo [14] СОБРАТЬ DOCX                            ^| build_docx               ^| собрать Markdown в DOCX
>>"%MENU_FILE%" echo [15] СОБРАТЬ DOCX ИЗ LLM MARKDOWN            ^| build_docx_llm           ^| плотная раскладка для LLM Markdown
>>"%MENU_FILE%" echo [16] СОБРАТЬ PDF                             ^| build_pdf                ^| DOCX в PDF через Word COM
>>"%MENU_FILE%" echo [17] DEV MARKDOWN PDF                        ^| build_dev_pdf            ^| Chromium light/dark PDF из input
>>"%MENU_FILE%" echo [18] СОБРАТЬ PPTX                            ^| build_pptx               ^| Markdown в презентации
>>"%MENU_FILE%" echo [19] СОБРАТЬ XLSX                            ^| build_xlsx               ^| таблицы Markdown в Excel
>>"%MENU_FILE%" echo.
>>"%MENU_FILE%" echo [20] СТАТУС ПРОЕКТА                          ^| run_main                 ^| папки проекта и runtime
>>"%MENU_FILE%" echo [21] ДОКТОР ОКРУЖЕНИЯ                        ^| run_doctor               ^| проверки runtime и импортов
>>"%MENU_FILE%" echo [22] ПРОВЕРИТЬ МОДЕЛИ OPENAI                 ^| check_models_openai      ^| запросить модели для текущего API key
>>"%MENU_FILE%" echo [23] ПРОВЕРИТЬ МОДЕЛИ GEMINI                 ^| check_models_gemini      ^| запросить модели для текущего API key
>>"%MENU_FILE%" echo.
>>"%MENU_FILE%" echo [24] ОТКРЫТЬ input                            ^| open_input               ^| исходники и Markdown
>>"%MENU_FILE%" echo [25] ОТКРЫТЬ КОРЕНЬ ПРОЕКТА                   ^| open_root                ^| рабочая папка проекта
>>"%MENU_FILE%" echo [26] ОТКРЫТЬ output                           ^| open_output              ^| все результаты
>>"%MENU_FILE%" echo [27] ОТКРЫТЬ logs                             ^| open_logs                ^| журналы
>>"%MENU_FILE%" echo [28] СКОПИРОВАТЬ output В input               ^| copy_output_md           ^| вернуть сгенерированные файлы в input
>>"%MENU_FILE%" echo.
>>"%MENU_FILE%" echo [29] ЛАУНЧЕР ИНСТРУМЕНТОВ                    ^| tools                    ^| служебные инструменты
>>"%MENU_FILE%" echo.
>>"%MENU_FILE%" echo [00] ВЫХОД                                   ^| exit                    ^| закрыть

type "%MENU_FILE%" | "%FZF_EXE%" --prompt="audion@office-ocr-ai [ПРОЕКТ] > " --pointer=">" --header="Выберите действие:" --layout=reverse --border="rounded" --info=hidden --margin=1,2 > "%RES_FILE%"

set "CHOICE="
set /p CHOICE=<"%RES_FILE%"
if not defined CHOICE goto MAIN

for /f "tokens=2 delims=|" %%a in ("%CHOICE%") do set "RAW=%%a"
call :TRIM RAW

if /I "%RAW%"=="run_main" goto RUN_MAIN
if /I "%RAW%"=="run_doctor" goto RUN_DOCTOR
if /I "%RAW%"=="check_models_openai" goto CHECK_MODELS_OPENAI
if /I "%RAW%"=="check_models_gemini" goto CHECK_MODELS_GEMINI
if /I "%RAW%"=="extract_fast" goto EXTRACT_FAST
if /I "%RAW%"=="ocr_tesseract" goto OCR_TESSERACT
if /I "%RAW%"=="ocr_surya" goto OCR_SURYA
if /I "%RAW%"=="ocr_yandex" goto OCR_YANDEX
if /I "%RAW%"=="ocr_mistral" goto OCR_MISTRAL
if /I "%RAW%"=="ocr_xai" goto OCR_XAI
if /I "%RAW%"=="ocr_gemini" goto OCR_GEMINI
if /I "%RAW%"=="ocr_openai" goto OCR_OPENAI
if /I "%RAW%"=="workbench_review" goto WORKBENCH_REVIEW
if /I "%RAW%"=="workbench_openai" goto WORKBENCH_OPENAI
if /I "%RAW%"=="workbench_gemini" goto WORKBENCH_GEMINI
if /I "%RAW%"=="workbench_coordinates" goto WORKBENCH_COORDINATES
if /I "%RAW%"=="ocr_mistral_fusion" goto OCR_MISTRAL_FUSION
if /I "%RAW%"=="build_docx" goto BUILD_DOCX
if /I "%RAW%"=="build_docx_llm" goto BUILD_DOCX_LLM
if /I "%RAW%"=="build_pdf" goto BUILD_PDF
if /I "%RAW%"=="build_pptx" goto BUILD_PPTX
if /I "%RAW%"=="build_xlsx" goto BUILD_XLSX
if /I "%RAW%"=="open_input" goto OPEN_INPUT
if /I "%RAW%"=="open_root" goto OPEN_ROOT
if /I "%RAW%"=="open_output" goto OPEN_OUTPUT
if /I "%RAW%"=="open_logs" goto OPEN_LOGS
if /I "%RAW%"=="copy_output_md" goto COPY_OUTPUT_MD
if /I "%RAW%"=="tools" goto TOOLS
if /I "%RAW%"=="build_dev_pdf" goto BUILD_DEV_PDF
if /I "%RAW%"=="exit" exit /b 0
goto MAIN

:FALLBACK_MENU
echo [1] Офисный текст без OCR
echo [2] Локальный OCR - Tesseract
echo [3] Локальный OCR - Surya
echo [4] API OCR - Yandex
echo [5] API OCR - Mistral
echo.
echo [6] API OCR - xAI
echo [7] API OCR - Gemini
echo [8] API OCR - OpenAI
echo [9] Workbench: локальная проверка
echo [A] Workbench: OpenAI resolver
echo [B] Workbench: Gemini resolver
echo [C] Workbench: координаты
echo [D] Mistral + Yandex + Tesseract
echo.
echo [E] Собрать DOCX
echo [F] Собрать DOCX из LLM Markdown
echo [G] Собрать PDF
echo [H] DEV Markdown PDF
echo [I] Собрать PPTX
echo [J] Собрать XLSX
echo.
echo [K] Статус проекта
echo [L] Доктор окружения
echo [M] Проверить модели OpenAI
echo [N] Проверить модели Gemini
echo.
echo [O] Открыть input
echo [P] Открыть корень проекта
echo [Q] Открыть output
echo [R] Открыть logs
echo [S] Скопировать output в input
echo.
echo [T] Лаунчер инструментов
echo.
echo [0] Выход
echo.
choice /C 123456789ABCDEFGHIJKLMNOPQRST0 /N /M "Выбор: "
set "MENU_CHOICE=%errorlevel%"
if "%MENU_CHOICE%"=="30" exit /b 0
if "%MENU_CHOICE%"=="29" goto TOOLS
if "%MENU_CHOICE%"=="28" goto COPY_OUTPUT_MD
if "%MENU_CHOICE%"=="27" goto OPEN_LOGS
if "%MENU_CHOICE%"=="26" goto OPEN_OUTPUT
if "%MENU_CHOICE%"=="25" goto OPEN_ROOT
if "%MENU_CHOICE%"=="24" goto OPEN_INPUT
if "%MENU_CHOICE%"=="23" goto CHECK_MODELS_GEMINI
if "%MENU_CHOICE%"=="22" goto CHECK_MODELS_OPENAI
if "%MENU_CHOICE%"=="21" goto RUN_DOCTOR
if "%MENU_CHOICE%"=="20" goto RUN_MAIN
if "%MENU_CHOICE%"=="19" goto BUILD_XLSX
if "%MENU_CHOICE%"=="18" goto BUILD_PPTX
if "%MENU_CHOICE%"=="17" goto BUILD_DEV_PDF
if "%MENU_CHOICE%"=="16" goto BUILD_PDF
if "%MENU_CHOICE%"=="15" goto BUILD_DOCX_LLM
if "%MENU_CHOICE%"=="14" goto BUILD_DOCX
if "%MENU_CHOICE%"=="13" goto OCR_MISTRAL_FUSION
if "%MENU_CHOICE%"=="12" goto WORKBENCH_COORDINATES
if "%MENU_CHOICE%"=="11" goto WORKBENCH_GEMINI
if "%MENU_CHOICE%"=="10" goto WORKBENCH_OPENAI
if "%MENU_CHOICE%"=="9" goto WORKBENCH_REVIEW
if "%MENU_CHOICE%"=="8" goto OCR_OPENAI
if "%MENU_CHOICE%"=="7" goto OCR_GEMINI
if "%MENU_CHOICE%"=="6" goto OCR_XAI
if "%MENU_CHOICE%"=="5" goto OCR_MISTRAL
if "%MENU_CHOICE%"=="4" goto OCR_YANDEX
if "%MENU_CHOICE%"=="3" goto OCR_SURYA
if "%MENU_CHOICE%"=="2" goto OCR_TESSERACT
if "%MENU_CHOICE%"=="1" goto EXTRACT_FAST
goto MAIN

:EXTRACT_FAST
call :RUNPY "%CORE_DIR%\cli_operation.py" extract_local
if not defined AUDION_NO_PAUSE pause
goto MAIN

:OCR_TESSERACT
call :RUNPY "%CORE_DIR%\cli_operation.py" ocr_brick_run --engine tesseract --format docx
if not defined AUDION_NO_PAUSE pause
goto MAIN

:OCR_SURYA
call :RUNPY "%CORE_DIR%\cli_operation.py" ocr_brick_run --engine surya --contract structured --format docx
if not defined AUDION_NO_PAUSE pause
goto MAIN

:OCR_YANDEX
call :RUNPY "%CORE_DIR%\cli_operation.py" ocr_brick_run --engine yandex --format docx
if not defined AUDION_NO_PAUSE pause
goto MAIN

:OCR_MISTRAL
call :RUNPY "%CORE_DIR%\cli_operation.py" ocr_brick_run --engine mistral --format docx
if not defined AUDION_NO_PAUSE pause
goto MAIN

:OCR_XAI
call :RUNPY "%CORE_DIR%\cli_operation.py" ocr_brick_run --engine xai --format docx
if not defined AUDION_NO_PAUSE pause
goto MAIN

:OCR_GEMINI
call :RUNPY "%CORE_DIR%\cli_operation.py" ocr_brick_run --engine gemini --format docx
if not defined AUDION_NO_PAUSE pause
goto MAIN

:OCR_OPENAI
call :RUNPY "%CORE_DIR%\cli_operation.py" ocr_brick_run --engine chatgpt --format docx
if not defined AUDION_NO_PAUSE pause
goto MAIN

:WORKBENCH_REVIEW
call :RUNPY "%CORE_DIR%\cli_operation.py" workbench_review
if not defined AUDION_NO_PAUSE pause
goto MAIN

:WORKBENCH_OPENAI
call :RUNPY "%CORE_DIR%\cli_operation.py" workbench_openai_resolver
if not defined AUDION_NO_PAUSE pause
goto MAIN

:WORKBENCH_GEMINI
call :RUNPY "%CORE_DIR%\cli_operation.py" workbench_gemini_resolver
if not defined AUDION_NO_PAUSE pause
goto MAIN

:WORKBENCH_COORDINATES
call :RUNPY "%CORE_DIR%\cli_operation.py" workbench_coordinates
if not defined AUDION_NO_PAUSE pause
goto MAIN

:OCR_MISTRAL_FUSION
call :RUNPY "%CORE_DIR%\cli_operation.py" ocr_brick_run --engine mistral --set ocr_mistral_second_pass=yandex_tesseract --set ocr_yandex_fusion=true --format docx --format verification
if not defined AUDION_NO_PAUSE pause
goto MAIN


:BUILD_DOCX
call :RUNPY "%CORE_DIR%\cli_operation.py" build_docx
if not defined AUDION_NO_PAUSE pause
goto MAIN

:BUILD_DOCX_LLM
call :RUNPY "%CORE_DIR%\cli_operation.py" build_docx_llm
if not defined AUDION_NO_PAUSE pause
goto MAIN

:BUILD_PDF
call :RUNPY "%CORE_DIR%\cli_operation.py" build_pdf
if not defined AUDION_NO_PAUSE pause
goto MAIN

:BUILD_DEV_PDF
"%PYTHON_CMD%" %PYTHON_ARGS% "%CORE_DIR%\dev_markdown_pdf_engine.py"
if not defined AUDION_NO_PAUSE pause
goto MAIN

:BUILD_PPTX
call :RUNPY "%CORE_DIR%\cli_operation.py" build_pptx
if not defined AUDION_NO_PAUSE pause
goto MAIN

:BUILD_XLSX
call :RUNPY "%CORE_DIR%\cli_operation.py" build_xlsx
if not defined AUDION_NO_PAUSE pause
goto MAIN

:RUN_MAIN
call :RUNPY "%CORE_DIR%\cli_operation.py" project_status
if not defined AUDION_NO_PAUSE pause
goto MAIN

:RUN_DOCTOR
call :RUNPY "%CORE_DIR%\cli_operation.py" env_doctor
if not defined AUDION_NO_PAUSE pause
goto MAIN

:CHECK_MODELS_OPENAI
call :RUNPY "%CORE_DIR%\cli_operation.py" check_models_openai
if not defined AUDION_NO_PAUSE pause
goto MAIN

:CHECK_MODELS_GEMINI
call :RUNPY "%CORE_DIR%\cli_operation.py" check_models_gemini
if not defined AUDION_NO_PAUSE pause
goto MAIN

:OPEN_INPUT
start "" explorer "%BASE_DIR%\input"
goto MAIN

:OPEN_ROOT
start "" explorer "%BASE_DIR%"
goto MAIN

:OPEN_OUTPUT
start "" explorer "%BASE_DIR%\output"
goto MAIN

:OPEN_LOGS
start "" explorer "%BASE_DIR%\logs"
goto MAIN

:COPY_OUTPUT_MD
if not exist "%BASE_DIR%\output\" (
  echo [WARN] Папка не найдена: "%BASE_DIR%\output"
  if not defined AUDION_NO_PAUSE pause
  goto MAIN
)
if not exist "%BASE_DIR%\input\" mkdir "%BASE_DIR%\input" >nul 2>nul
robocopy "%BASE_DIR%\output" "%BASE_DIR%\input" *.md /S /R:1 /W:1 /NFL /NDL /NJH /NJS /NP >nul
set "RC=%errorlevel%"
if %RC% GEQ 8 (
  echo [ERROR] Ошибка копирования. Код robocopy: %RC%
) else (
  echo [OK] Markdown скопирован из output в input
)
if not defined AUDION_NO_PAUSE pause
goto MAIN

:TOOLS
call "%BASE_DIR%\launcher_tools.cmd"
goto MAIN

:NO_PYTHON
cls
echo [ERROR] Python runtime не найден.
echo.
echo Поддерживаемые варианты:
echo   runtime\python.exe
echo   runtime\python\python.exe
echo   py -3.12
echo   python
echo.
echo Используйте builder_main.cmd или install\Build_Portable_Env_Build.cmd
if not defined AUDION_NO_PAUSE pause
exit /b 1

:RUNPY
set "TARGET=%~1"
shift
set "RUN_ARGS="
:RUNPY_ARGS
if "%~1"=="" goto RUNPY_EXEC
set "RUN_ARGS=%RUN_ARGS% "%~1""
shift
goto RUNPY_ARGS
:RUNPY_EXEC
if not exist "%TARGET%" (
  echo [ERROR] Скрипт не найден:
  echo %TARGET%
  goto :eof
)
"%PYTHON_CMD%" %PYTHON_ARGS% "%TARGET%" %RUN_ARGS%
goto :eof

:RESOLVE_PYTHON
set "PYTHON_CMD="
set "PYTHON_ARGS="

if exist "%BASE_DIR%\runtime\python.exe" (
  set "PYTHON_CMD=%BASE_DIR%\runtime\python.exe"
  goto PY_OK
)

if exist "%BASE_DIR%\runtime\python\python.exe" (
  set "PYTHON_CMD=%BASE_DIR%\runtime\python\python.exe"
  goto PY_OK
)

py -3.12 -V >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=py"
  set "PYTHON_ARGS=-3.12"
  goto PY_OK
)

where python >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=python"
  goto PY_OK
)

exit /b 1

:PY_OK
exit /b 0

:TRIM
for /f "tokens=* delims= " %%z in ("!%~1!") do set "%~1=%%z"
:TRIM_R
if "!%~1:~-1!"==" " set "%~1=!%~1:~0,-1!" & goto TRIM_R
goto :eof
