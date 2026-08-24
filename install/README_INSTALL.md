# Audion Office OCR AI - Install Notes

This file covers the portable Python environment and optional external tools used by the project.

## Main build paths

### Recommended
Run:

```bat
builder_main.cmd
```

or directly:

```bat
install\Build_Portable_Env_Build.cmd
```

This is the main CMD build script.
It normalizes project `.cmd` files, builds wheels with `pip wheel --prefer-binary --no-build-isolation`, installs from the local wheelhouse, then runs `doctor.py` and a NiceGUI smoke check.

### Template alignment

These files intentionally follow the portable GUI template structure:

- `builder_main.cmd`
- `install\Build_Portable_Env.cmd`
- `install\Build_Portable_Env.ps1`
- `install\Build_Portable_Env_Build.cmd`
- `install\init_folders.cmd`

Project-specific differences are expected and should be preserved:

- `builder_main.cmd` adds Playwright Chromium, portable Tesseract, Real-ESRGAN, llama.cpp, and optional Surya builder entries.
- `Build_Portable_Env_Build.cmd` and `Build_Portable_Env.ps1` build the core Python bundle without Tesseract, then print the optional component command before `doctor.py`.
- `init_folders.cmd` creates OpenAI/Gemini key folders and `._runtime\tmp`.
- `install\tools` is reserved for persistent installer helpers and is not cleared by `cleanup_project.cmd`.
- Template-only cleanup helpers are not part of this project.

### Optional PowerShell route
Run:

```bat
install\Build_Portable_Env.cmd
```

This is a thin wrapper for the same-name `Build_Portable_Env.ps1`.

The wrapper looks for PowerShell in:

1. `system_core\powershell\pwsh.exe`
2. `pwsh.exe` in `PATH`
3. `powershell.exe` in `PATH`

To install a project-local PowerShell for portable picker dialogs and build helpers, run:

```bat
install\Install-Portable-PowerShell.cmd
```

## Reproducible payloads

Python runtime, wheelhouse, portable PowerShell, FZF and optional portable components are reproducible tool payloads. Install/update scripts may resolve latest upstream artifacts and cleanly replace only their owned targets: `runtime\`, `wheelhouse\`, `system_core\powershell\`, `system_core\fzf.exe`, `runtime\tesseract\`, `tools\realesrgan-ncnn-vulkan\`, `tools\llama.cpp\`, and `tools\optional-ocr-engines\`.

## Portable flow

1. Create folders
2. Resolve and download latest Python Embedded `3.12.x` ZIP
3. Extract to `runtime\`
4. Enable `import site` in `python3<minor>._pth`
5. Download `get-pip.py`
6. Build local `wheelhouse\`
7. Install packages into portable runtime
8. Print optional component hints: Tesseract, Real-ESRGAN, llama.cpp, Surya
9. Verify with `system_core\doctor.py`
10. Run NiceGUI smoke check
11. Optionally create a release ZIP in `release\`

`install\init_folders.cmd` is intentionally limited to directories and `.gitkeep` markers. It does not create API key files, token placeholders, or default business configuration.

## Offline flow

If `runtime\` and `wheelhouse\` are already populated, run:

```bat
install\install_portable_offline.cmd
```

Then verify with:

```bat
install\verify_portable_env.cmd
```

## Optional Portable Tesseract for OCR Brick

The core portable Python environment installs `pytesseract`, but that package is only a Python bridge. Native Tesseract is not part of the core bundle. The project starts without it; Workbench will explicitly report that Tesseract is not found and local OCR is limited.

When local Workbench OCR is needed, install Tesseract as an optional portable component. The project prefers this layout:

```text
runtime\tesseract\tesseract.exe
runtime\tesseract\tessdata\eng.traineddata
runtime\tesseract\tessdata\rus.traineddata
runtime\tesseract\tessdata\deu.traineddata
runtime\tesseract\tessdata\osd.traineddata
```

Install or refresh the optional component from `builder_main.cmd` -> `[10] TESSERACT`, or run:

```bat
install\Install-Portable-Tesseract.cmd
```

A fresh core rebuild recreates `runtime\`; run the optional component installer afterwards if you want local Tesseract OCR in Workbench.

The installer owns only the project-local `runtime\tesseract` folder. Every run builds a fresh temporary payload, reuses cached `tessdata_fast` language files when present, removes the previous `runtime\tesseract` copy if it exists, and moves the fresh payload into place.

No system Tesseract installation is required when a local payload cache is present. If no payload/source exists, the script resolves the latest stable x64 UB Mannheim build, downloads it, and tries to run the NSIS installer into project staging with `/S /D=runtime\_tesseract_installer_stage`; because this is still a real Windows installer, some machines may show elevation or installer UI. For no-UI refreshes, prefer `install\download\tesseract_payload`.

If a Windows install such as `C:\Program Files\Tesseract-OCR` already exists, the default path copies from it as a read-only source. This avoids NSIS maintenance/uninstall UI and still produces a project-local `runtime\tesseract` copy. After that project-local copy exists, the system Tesseract install is not needed by this project.

For machines where GitHub raw or the Mannheim installer is blocked, preseed the local cache before running the installer:

```text
install\download\tesseract_payload\tesseract.exe
install\download\tesseract_payload\*.dll
install\download\tesseract_payload\tessdata\eng.traineddata
install\download\tesseract_payload\tessdata\rus.traineddata
install\download\tesseract_payload\tessdata\deu.traineddata
install\download\tesseract_payload\tessdata\osd.traineddata
```

Alternatively, cache language files only:

```text
install\download\tessdata\tessdata_fast\eng.traineddata
install\download\tessdata\tessdata_fast\rus.traineddata
install\download\tessdata\tessdata_fast\deu.traineddata
install\download\tessdata\tessdata_fast\osd.traineddata
```

Then run `install\Install-Portable-Tesseract.cmd`. A cached `tesseract_payload` folder is copied directly and does not launch the UB Mannheim installer UI.

Do not point the UB Mannheim installer UI at the project folder manually. The project target is fixed:

```text
runtime\tesseract
```

If Tesseract is installed in a non-standard location, set the source folder before running the installer:

```powershell
$env:AUDION_TESSERACT_SOURCE_DIR = "D:\Tools\Tesseract-OCR"
install\Install-Portable-Tesseract.cmd
```

Fallback lookup order:

1. `runtime\tesseract\tesseract.exe`
2. `AUDION_TESSERACT_EXE`
3. `tesseract.exe` in `PATH`

Verify:

```bat
runtime\tesseract\tesseract.exe --version
runtime\tesseract\tesseract.exe --list-langs
```

Recommended upstream sources:

1. Open the official Tesseract installation docs: https://tesseract-ocr.github.io/tessdoc/Installation.html
2. Follow the Windows link to UB Mannheim builds: https://github.com/UB-Mannheim/tesseract/wiki
3. Installer files: https://digi.bib.uni-mannheim.de/tesseract/
4. Language data: https://github.com/tesseract-ocr/tessdata_fast

For Russian+English OCR runs, use:

```text
rus+eng
```

If Tesseract is unavailable, local Tesseract OCR and 2-pass OCR checks are unavailable. The GUI should report this explicitly instead of failing silently.

## Optional OCR/layout engines

Surya is a heavy optional OCR/layout engine. It is not installed into the core portable Python runtime. The core runtime remains reproducible from:

```text
install\requirements_full.in
```

Optional engine installers create separate project-local payloads under:

```text
tools\optional-ocr-engines\<engine>\runtime\
```

Recommended installs are machine-local and optional:

```bat
install\Install-Portable-LlamaCpp.cmd -Variant vulkan
install\Install-Optional-OCREngines.cmd -Engine surya -Mode cpu
```

Use Vulkan as the default non-NVIDIA path. On NVIDIA machines, try the light llama.cpp CUDA path before installing heavy PyTorch wheels:

```bat
install\Install-Portable-LlamaCpp.cmd -Variant cuda124
install\Install-Portable-LlamaCpp.cmd -Variant cuda133
```

Only benchmark PyTorch CUDA when a CUDA workstation is expected to give a multiple-speed win:

```bat
install\Install-Optional-OCREngines.cmd -Engine surya -Mode cuda40
install\Install-Optional-OCREngines.cmd -Engine surya -Mode cuda50
```

Use `-Force` to recreate only the selected optional payload:

```bat
install\Install-Optional-OCREngines.cmd -Engine surya -Mode cpu -Force
```

The GUI exposes the same controls in Project tools -> Surya acceleration installs. The child window shows a GPU/CPU recommendation badge directly under the top Back/Run row, so the needed Vulkan/CUDA/PyTorch route is visible before running an installer.

The same payloads are exposed from `builder_main.cmd`:

```text
[11] REAL-ESRGAN VULKAN
[12] LLAMA.CPP VULKAN
[13] SURYA CPU OCR
[14] LLAMA.CPP CUDA 12.4
[15] LLAMA.CPP CUDA 13.3
[16] SURYA PYTORCH CUDA 40XX
[17] SURYA PYTORCH CUDA 50XX
```

What each entry is for:

| Entry | Install when | Purpose |
| --- | --- | --- |
| `[11] REAL-ESRGAN VULKAN` | Any machine with a working Vulkan GPU, especially for bad scans | Image cleanup/upscale before OCR: JPEG artifacts, sharpness and weak text. It is not an OCR engine. |
| `[12] LLAMA.CPP VULKAN` | AMD, Intel Arc, or NVIDIA machines where CUDA is not the chosen route | Lightweight Surya backend through Vulkan. Good default for non-NVIDIA GPU acceleration. |
| `[13] SURYA CPU OCR` | When Surya is needed at all | Installs the optional Surya OCR/layout runtime. Slow but local/free. |
| `[14] LLAMA.CPP CUDA 12.4` | NVIDIA RTX 20xx/30xx/40xx | Recommended lightweight Surya backend for most CUDA NVIDIA machines before trying PyTorch. |
| `[15] LLAMA.CPP CUDA 13.3` | NVIDIA RTX 50xx | Recommended lightweight Surya backend for RTX 50xx. |
| `[16] SURYA PYTORCH CUDA 40XX` | RTX 40xx benchmark only | Heavy PyTorch CUDA optional runtime. Install only to test whether it gives a multiple-speed Surya win. |
| `[17] SURYA PYTORCH CUDA 50XX` | RTX 50xx benchmark only | Heavy PyTorch CUDA optional runtime for RTX 50xx. Not the default path. |

Practical combinations:

| Machine | Recommended entries | Optional experiment |
| --- | --- | --- |
| NVIDIA RTX 50xx | `[11]`, `[13]`, `[15]` | `[17]` |
| NVIDIA RTX 40xx | `[11]`, `[13]`, `[14]` | `[16]` |
| NVIDIA older/unknown CUDA | `[11]`, `[13]`, `[14]` | none first |
| AMD / Intel Arc / Vulkan GPU | `[11]`, `[13]`, `[12]` | none first |
| CPU-only | `[13]` only if Surya is required | Prefer Tesseract/API for speed |

Only one llama.cpp payload is active under `tools\llama.cpp`; installing Vulkan/CUDA replaces that payload with the selected variant. Do not install all llama.cpp variants on one machine. PyTorch CUDA payloads are large and should stay machine-local benchmark options, not default project dependencies.

## Optional Chromium for DEV Markdown PDF

The office PDF pipeline remains Word-based and is launched from `launcher_project.cmd` as `BUILD PDF`
or from `launcher_project_ru.cmd` as `СОБРАТЬ PDF`.

The separate DEV Markdown PDF engine renders Markdown through Playwright Chromium into paired dark/light PDF files.
It is launched from `launcher_project.cmd` / `launcher_project_ru.cmd` -> `[17] DEV Markdown PDF` or fallback key `[H]`.

By default it scans only:

```text
input\
```

The CLI path is input-only unless `--source` or `--source-list` is passed. Internal project Markdown files are not converted by default.

In the GUI, DEV Markdown PDF can scan project documentation, selected files/folders, existing PDF pairs, or outdated PDF pairs. The default output mode creates one shared `PDF` subfolder beside each Markdown folder; direct beside-source output, shared `docs/PDF`, and mirrored output into the current Workbench Target remain available. The command also exposes layout settings: left/right/top/bottom margins, page top/bottom reserve, and line height.

Current defaults are:

```text
left/right margins: 17 mm
top margin: 16 mm
bottom margin: 20 mm
page top/bottom reserve: 4 mm
line height: 1.25
```

Tables are allowed to continue on the next page by rows; table headers are repeated where Chromium supports it.

Install the portable Chromium runtime from:

```bat
builder_main.cmd
```

then choose:

```text
[05] PLAYWRIGHT CHROMIUM
```

Chromium is stored under:

```text
runtime\.playwright\
```

## Release licensing

Third-party notices and license files are generated from the finalized staged release contents during `make_release_archive.cmd`. They are no longer generated during routine environment build/install steps.

---

## Current Builder Order And Dependency Hygiene

`builder_main.cmd` uses fixed numeric entries. Keep the bootstrap order stable: `[01] PYTHON ENV CMD`, `[02] PYTHON ENV PS`, `[03] FZF`, `[04] POWERSHELL`, `[05] PLAYWRIGHT CHROMIUM`, then project-specific payload installers and one-time maintenance/diagnostic actions below.

Current builder install/maintenance map:

```text
[01] PYTHON ENV CMD
[02] PYTHON ENV PS
[03] FZF
[04] POWERSHELL
[05] PLAYWRIGHT CHROMIUM
[09] PORTABLE OFFLINE
[10] TESSERACT
[11] REAL-ESRGAN VULKAN
[12] LLAMA.CPP VULKAN
[13] SURYA CPU OCR
[14] LLAMA.CPP CUDA 12.4
[15] LLAMA.CPP CUDA 13.3
[16] SURYA PYTORCH CUDA 40XX
[17] SURYA PYTORCH CUDA 50XX
[70] CLEAN INSTALL CACHE
[71] VERIFY / DOCTOR
[72] CMD ENCODING CHECK
[74] COLLECT LICENSES
[75] PRUNE LICENSES
[76] DEDUP LICENSES
[77] MAKE RELEASE ARCHIVE
[90] PROJECT LAUNCHER
[94] OPEN tools
[95] OPEN install
[96] OPEN runtime
[97] OPEN wheelhouse
[98] OPEN licenses
[99] OPEN release
[00] EXIT
```

Project-specific payload entries before diagnostics:

[10] TESSERACT
[11] REAL-ESRGAN VULKAN
[12] LLAMA.CPP VULKAN
[13] SURYA CPU OCR
[14] LLAMA.CPP CUDA 12.4
[15] LLAMA.CPP CUDA 13.3
[16] SURYA PYTORCH CUDA 40XX
[17] SURYA PYTORCH CUDA 50XX

Dependency hygiene rules:

- Python Embedded tracks the latest `3.12.x`; do not pin a concrete patch version in docs or scripts.
- Use the active embedded Python `_pth` file for path edits; do not hard-code a concrete filename.
- Bootstrap installs must include `setuptools`, `wheel`, and `packaging` before building or installing project wheels.
- `runtime\`, `wheelhouse\`, `system_core\powershell\`, `system_core\fzf.exe`, browser payloads, `runtime\tesseract\`, and root `tools\` external payload folders are reproducible payloads. Install/update scripts may cleanly replace only their owned targets.
- GPL or unknown-license external tools are explicit install/update payloads. Prefer GUI install buttons where the project exposes them, or fixed builder entries otherwise; do not silently bundle them as default source contents.
- `install\Clean-Install-Cache.cmd` / `.ps1` is the general install-cache cleanup. It removes transient `install\download\` artifacts (preserving `.gitkeep`, `get-pip.py`, and `7z*-extra.7z`), exact installer staging dirs under `system_core\` and root `tools\`, and Python bytecode caches outside runtime, wheelhouse, tools, and user-data zones.
- `cleanup_project.cmd` is a separate source/release cleanup tool. It can remove runtime payloads, root `tools\` optional payloads, cache, and user-output zones after explicit confirmation; do not describe it as the general install-cache cleaner and do not wire it into install flow.

Project-specific notes:

- Portable Tesseract, Playwright Chromium, Real-ESRGAN, llama.cpp, and Surya are explicit installer entries. Keep them out of the core Python build and install them only when needed.


