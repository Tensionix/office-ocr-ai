from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
import atexit
import argparse
import ctypes
from ctypes import wintypes
import importlib
import ipaddress
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nicegui import app as nicegui_app, run, ui  # type: ignore
from system_core.ui_nicegui.workbench import (
    WorkbenchAdapter,
    WorkbenchConfig,
    WorkbenchHandlers,
    WorkbenchRenderer,
    WorkbenchRole,
    WORKBENCH_FEEDBACK_CSS,
    WORKBENCH_LAYOUT_CSS,
    WORKBENCH_OVERRIDE_CSS,
    canonical_role,
)

AUDION_CANONICAL_TOOLTIP_DELAY_MS = 1500
AUDION_CANONICAL_TOOLTIP_HIDE_DELAY_MS = 100
AUDION_CANONICAL_TOOLTIP_TRANSITION_MS = 100


def install_audion_canonical_tooltip_defaults() -> None:
    try:
        from nicegui.elements.tooltip import Tooltip as NiceGuiTooltip  # type: ignore
    except Exception:
        return
    if getattr(NiceGuiTooltip, "_audion_canonical_tooltip_defaults", False):
        return
    original_init = NiceGuiTooltip.__init__

    def audion_tooltip_init(self: Any, text: str = "") -> None:
        original_init(self, text)
        self.props["delay"] = AUDION_CANONICAL_TOOLTIP_DELAY_MS
        self.props["hide-delay"] = AUDION_CANONICAL_TOOLTIP_HIDE_DELAY_MS
        self.props["transition-duration"] = AUDION_CANONICAL_TOOLTIP_TRANSITION_MS
        self.classes("audion-tooltip")

    NiceGuiTooltip.__init__ = audion_tooltip_init  # type: ignore[method-assign]
    NiceGuiTooltip._audion_canonical_tooltip_defaults = True  # type: ignore[attr-defined]


install_audion_canonical_tooltip_defaults()


AUDION_CANONICAL_UI_CSS = """
<style id="audion-canonical-tooltip-icon-style">
  html body .q-tooltip,
  html body .audion-tooltip {
    background: rgb(23, 33, 43) !important;
    background-color: rgb(23, 33, 43) !important;
    color: #f4f8fb !important;
    border: 1px solid rgba(88, 166, 255, 0.24) !important;
    border-radius: 8px !important;
    box-shadow: 0 12px 28px rgba(0, 0, 0, 0.34) !important;
  }
  html body .q-icon.material-icons,
  html body .q-icon.material-symbols-outlined,
  html body .q-icon.material-symbols-rounded,
  html body i.material-icons,
  html body i.material-symbols-outlined,
  html body i.material-symbols-rounded,
  html body .q-btn .q-icon,
  html body .q-btn .material-icons,
  html body .q-btn .material-symbols-outlined,
  html body .q-btn .material-symbols-rounded,
  html body .q-field .q-field__append .q-icon,
  html body .q-field .q-field__prepend .q-icon,
  html body .q-item .q-icon,
  html body .q-menu .q-icon,
  html body .audion-label-icon,
  html body .audion-path-option-pin,
  html body .audion-select-option-pin {
    font-size: 14px !important;
    width: 14px !important;
    min-width: 14px !important;
    height: 14px !important;
    line-height: 14px !important;
  }
  html body .material-icons,
  html body .q-icon.material-icons {
    font-family: "Material Icons" !important;
  }
  html body .material-symbols-outlined,
  html body .q-icon.material-symbols-outlined {
    font-family: "Material Symbols Outlined" !important;
  }
  html body .material-symbols-rounded,
  html body .q-icon.material-symbols-rounded {
    font-family: "Material Symbols Rounded" !important;
  }
</style>
"""


def add_audion_canonical_ui_styles() -> None:
    ui.add_head_html(AUDION_CANONICAL_UI_CSS)



def audion_tooltip_path_text(path_value: Any) -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    try:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        return str(path)
    except Exception:
        return raw


def audion_folder_button_tooltip(folder_id: str, path_value: Any) -> str:
    key = str(folder_id or "folder").strip().lower()
    path_text = audion_tooltip_path_text(path_value)
    if getattr(settings, "language", "ru") == "ru":
        descriptions = {
            "logs": "папку логов запусков и вывода терминала",
            "report": "папку отчётов и результатов операций",
            "reports": "папку отчётов и результатов операций",
            "config": "папку конфигурации проекта: manifest, GUI-настройки и кэши",
            "state": "папку рабочего состояния GUI",
            "project": "корневую папку проекта",
            "root": "корневую папку проекта",
            "data": "папку данных проекта",
            "pipeline": "папку pipeline-артефактов и промежуточных результатов",
            "github": "папку GitHub-артефактов проекта",
            "install": "папку install/runtime-артефактов проекта",
        }
        description = descriptions.get(key, f"папку {folder_id}")
        return f"Открыть {description}: {path_text}" if path_text else f"Открыть {description}."
    descriptions = {
        "logs": "the logs folder with run and terminal output",
        "report": "the reports/results folder",
        "reports": "the reports/results folder",
        "config": "the project config folder with manifest, GUI settings, and caches",
        "state": "the GUI state folder",
        "project": "the project root folder",
        "root": "the project root folder",
        "data": "the project data folder",
        "pipeline": "the pipeline artifacts and intermediate results folder",
        "github": "the project GitHub artifacts folder",
        "install": "the project install/runtime artifacts folder",
    }
    description = descriptions.get(key, f"the {folder_id} folder")
    return f"Open {description}: {path_text}" if path_text else f"Open {description}."


def audion_terminal_action_tooltip(action: str) -> str:
    key = str(action or "").strip().lower()
    if getattr(settings, "language", "ru") == "ru":
        tips = {
            "clear_terminal_window": "Очистить только видимое окно терминала. Файлы логов, отчёты и результаты операций не удаляются.",
            "expand": "Открыть терминал в большом окне, чтобы читать длинный вывод без тесной панели.",
            "expand_log": "Открыть терминал в большом окне, чтобы читать длинный вывод без тесной панели.",
            "pin_command": "Закрепить текущую команду в истории терминала для быстрого повторного запуска.",
            "unpin_command": "Открепить текущую команду от верхней части истории терминала.",
            "clear_history": "Очистить историю команд терминала. Закреплённые команды и файлы логов не удаляются.",
            "terminal_shell": "Выбрать оболочку, в которой будут запускаться команды терминала.",
            "terminal_history": "Выбрать ранее сохранённую или закреплённую команду терминала.",
            "terminal_command": "Команда, которая будет выполнена из выбранной рабочей папки.",
            "terminal_cwd": "Рабочая папка терминала. Команда будет запущена именно отсюда.",
            "pick_folder": "Выбрать рабочую папку терминала через системный диалог.",
            "terminal_run": "Запустить введённую команду в выбранной оболочке и рабочей папке.",
            "latest_report": "Открыть последний созданный отчёт, если он уже есть.",
            "command_preview": "Показать команду, которая будет запущена с текущими параметрами, без выполнения операции.",
            "report_view": "Открыть встроенный список отчётов без перехода в проводник.",
            "close": "Закрыть большое окно терминала и вернуться к основной панели.",
        }
    else:
        tips = {
            "clear_terminal_window": "Clear only the visible terminal window. Log files, reports, and operation results are not deleted.",
            "expand": "Open the terminal in a large window for reading long output comfortably.",
            "expand_log": "Open the terminal in a large window for reading long output comfortably.",
            "pin_command": "Pin the current terminal command for quick reuse.",
            "unpin_command": "Remove the current command from the pinned command list.",
            "clear_history": "Clear terminal command history. Pinned commands and log files are not deleted.",
            "terminal_shell": "Choose the shell used to run terminal commands.",
            "terminal_history": "Pick a saved or pinned terminal command.",
            "terminal_command": "Command to run from the selected working folder.",
            "terminal_cwd": "Terminal working folder. Commands are started from here.",
            "pick_folder": "Choose the terminal working folder with the system dialog.",
            "terminal_run": "Run the entered command in the selected shell and working folder.",
            "latest_report": "Open the latest generated report, if one exists.",
            "command_preview": "Show the command that would run with the current settings, without executing it.",
            "report_view": "Open the built-in reports list without switching to the file explorer.",
            "close": "Close the large terminal window and return to the main panel.",
        }
    return tips.get(key, key.replace("_", " ").strip())


from system_core.core.ansi import terminal_lines_html as _terminal_lines_html
from system_core.core.config import load_yaml_or_json
from system_core.core.jobs import execute_operation
from system_core.core.manifest import CommandNode, Operation, load_manifest
from system_core.core.paths import ensure_project_dirs, get_project_paths, open_folder
from system_core.core.ui_theme_catalog import DEFAULT_THEME_ID, normalize_theme_id
from system_core.core.ui_settings import load_ui_settings


paths = get_project_paths(ROOT)
ensure_project_dirs(paths)
manifest = load_manifest(paths.config / "tool_manifest.yaml")
settings_path = paths.config / "gui_settings.yaml"
settings = load_ui_settings(settings_path)
tool_info: dict[str, Any] = manifest.raw.get("tool", {})
ui_info: dict[str, Any] = manifest.raw.get("ui", {})


def _workspace_history_file() -> Path:
    return paths.config / "path_history.json"


def _startup_workspace_path(role: str, configured: str, legacy: str, default_path: Path) -> str:
    return str(default_path)


def load_workspace_route_settings() -> tuple[str, str]:
    return (
        _startup_workspace_path("source", "", "", paths.input),
        _startup_workspace_path("target", "", "", paths.output),
    )


def _yaml_string(value: Any) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def _workspace_setting_for_disk(role: str, path_value: Any, default_path: Path) -> str:
    return ""


def display_path(path_value: Any) -> str:
    text = str(path_value or "").strip()
    if not text:
        return ""
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    try:
        resolved = path.resolve()
        relative = resolved.relative_to(ROOT)
    except (OSError, ValueError):
        return str(path)
    return str(relative) or "."

def save_app_settings() -> None:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    source_path = _workspace_setting_for_disk("source", getattr(settings, "source_path", ""), paths.input)
    destination_path = _workspace_setting_for_disk("target", getattr(settings, "destination_path", ""), paths.output)
    text = (
        "gui:\n"
        "  # Change to \"en\" for public GitHub builds.\n"
        f"  language: \"{settings.language if settings.language in {'en', 'ru'} else 'ru'}\"\n"
        f"  theme: \"{normalize_theme_id(settings.theme)}\"\n"
        f"  emoji: {str(bool(getattr(settings, 'emoji', False))).lower()}\n"
        f"  allow_runtime_switching: {str(bool(getattr(settings, 'allow_runtime_switching', True))).lower()}\n"
        f"  advanced_open: {str(bool(getattr(settings, 'advanced_open', False))).lower()}\n"
        f"  source_path: {_yaml_string(source_path)}\n"
        f"  destination_path: {_yaml_string(destination_path)}\n"
    )
    settings_path.write_text(text, encoding="utf-8", newline="\n")

settings.source_path, settings.destination_path = load_workspace_route_settings()
TESSERACT_INSTALL_OPERATION = Operation(
    id="install_tesseract",
    title="INSTALL TESSERACT (RECOMMENDED)",
    title_ru="УСТАНОВИТЬ TESSERACT (РЕКОМЕНДУЕТСЯ)",
    description="Install or refresh the recommended project-local Tesseract OCR engine.",
    description_ru="Установить или обновить рекомендуемый project-local Tesseract OCR.",
    tooltip="Recommended local minimum for OCR: free per page, fast, project-local, and useful for coordinates plus numeric-check hints.",
    tooltip_ru="Рекомендуемый локальный минимум для OCR: бесплатно за страницу, быстро, project-local, полезен для координат и подсказок numeric-check.",
    service="system_core.services.office_service:install_tesseract",
    kind="safe",
)


def terminal_lines_html(lines, *, leading_newline: bool = False) -> str:
    return _terminal_lines_html(lines, leading_newline=False).replace("\n", "")


def _string_map(value: Any) -> dict[str, str]:
    return {str(key).strip(): str(item).strip() for key, item in dict(value).items() if str(key).strip()} if isinstance(value, dict) else {}


BUILTIN_THEMES: dict[str, dict[str, Any]] = {
    "code_dark": {
        "label": "Code Dark",
        "label_ru": "Code Темная",
        "mode": "dark",
        "tokens": {
            "color-background-primary": "#141413",
            "color-background-secondary": "#1f1e1a",
            "color-background-tertiary": "#0f0f0e",
            "color-text-primary": "#faf9f5",
            "color-text-secondary": "#e8e6dc",
            "color-text-tertiary": "#b0aea5",
            "color-border-tertiary": "rgba(250, 249, 245, 0.15)",
            "color-border-secondary": "rgba(250, 249, 245, 0.3)",
            "color-border-primary": "rgba(250, 249, 245, 0.4)",
            "color-accent-primary": "#d97757",
            "color-accent-secondary": "#6a9bcc",
            "color-accent-tertiary": "#788c5d",
        },
    },
    "code_graphite": {
        "label": "Code Graphite",
        "label_ru": "Code графит",
        "mode": "dark",
        "tokens": {
            "color-background-primary": "#2c2c2a",
            "color-background-secondary": "#34332f",
            "color-background-tertiary": "#141413",
            "color-text-primary": "#faf9f5",
            "color-text-secondary": "#e8e6dc",
            "color-text-tertiary": "#b0aea5",
            "color-border-tertiary": "rgba(250, 249, 245, 0.15)",
            "color-border-secondary": "rgba(250, 249, 245, 0.3)",
            "color-border-primary": "rgba(250, 249, 245, 0.4)",
            "color-accent-primary": "#d97757",
            "color-accent-secondary": "#6a9bcc",
            "color-accent-tertiary": "#788c5d",
        },
    },
    "code_light": {
        "label": "Code Light",
        "label_ru": "Code светлая",
        "mode": "light",
        "tokens": {
            "color-background-primary": "#faf9f5",
            "color-background-secondary": "#fffdf8",
            "color-background-tertiary": "#f1efe8",
            "color-text-primary": "#141413",
            "color-text-secondary": "#5f5e5a",
            "color-text-tertiary": "#888780",
            "color-border-tertiary": "rgba(20, 20, 19, 0.15)",
            "color-border-secondary": "rgba(20, 20, 19, 0.3)",
            "color-border-primary": "rgba(20, 20, 19, 0.4)",
            "color-accent-primary": "#d97757",
            "color-accent-secondary": "#6a9bcc",
            "color-accent-tertiary": "#788c5d",
        },
    },
    "code_warm": {
        "label": "Code Warm",
        "label_ru": "Code теплая",
        "mode": "light",
        "tokens": {
            "color-background-primary": "#fffdf8",
            "color-background-secondary": "#faf9f5",
            "color-background-tertiary": "#e8e6dc",
            "color-text-primary": "#141413",
            "color-text-secondary": "#444441",
            "color-text-tertiary": "#888780",
            "color-border-tertiary": "rgba(20, 20, 19, 0.15)",
            "color-border-secondary": "rgba(20, 20, 19, 0.3)",
            "color-border-primary": "rgba(20, 20, 19, 0.4)",
            "color-accent-primary": "#d97757",
            "color-accent-secondary": "#6a9bcc",
            "color-accent-tertiary": "#788c5d",
        },
    },
    "audion_light": {
        "label": "Audion Light",
        "label_ru": "Audion светлая",
        "mode": "light",
        "tokens": {
            "color-background-primary": "#f7fbff",
            "color-background-secondary": "#ffffff",
            "color-background-tertiary": "#e6f1fb",
            "color-text-primary": "#102033",
            "color-text-secondary": "#36546f",
            "color-text-tertiary": "#6f879c",
            "color-border-tertiary": "rgba(4, 44, 83, 0.15)",
            "color-border-secondary": "rgba(4, 44, 83, 0.3)",
            "color-border-primary": "rgba(4, 44, 83, 0.4)",
            "color-accent-primary": "#378ADD",
            "color-accent-secondary": "#1D9E75",
            "color-accent-tertiary": "#534AB7",
        },
    },
    "audion_dark": {
        "label": "Audion Dark",
        "label_ru": "Audion Темная",
        "mode": "dark",
        "tokens": {
            "color-background-primary": "#08131f",
            "color-background-secondary": "#102033",
            "color-background-tertiary": "#050b12",
            "color-text-primary": "#f7fbff",
            "color-text-secondary": "#d7e7f6",
            "color-text-tertiary": "#9bb7cf",
            "color-border-tertiary": "rgba(247, 251, 255, 0.15)",
            "color-border-secondary": "rgba(247, 251, 255, 0.3)",
            "color-border-primary": "rgba(247, 251, 255, 0.4)",
            "color-accent-primary": "#6a9bcc",
            "color-accent-secondary": "#5DCAA5",
            "color-accent-tertiary": "#7F77DD",
        },
    },
    "asar_dark": {
        "label": "Asar Dark",
        "label_ru": "Asar Темная",
        "mode": "dark",
        "tokens": {
            "color-background-primary": "#181a1f",
            "color-background-secondary": "#20242b",
            "color-background-tertiary": "#0f1115",
            "color-text-primary": "#f4f7fb",
            "color-text-secondary": "#d6dde7",
            "color-text-tertiary": "#9aa7b8",
            "color-border-tertiary": "rgba(244, 247, 251, 0.15)",
            "color-border-secondary": "rgba(244, 247, 251, 0.3)",
            "color-border-primary": "rgba(244, 247, 251, 0.4)",
            "color-accent-primary": "#85B7EB",
            "color-accent-secondary": "#9FE1CB",
            "color-accent-tertiary": "#CECBF6",
        },
    },
}


def _normalize_theme(theme_id: str, theme_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": str(theme_data.get("label") or theme_id).strip(),
        "label_ru": str(theme_data.get("label_ru") or theme_data.get("label") or theme_id).strip(),
        "mode": "dark" if str(theme_data.get("mode", "dark")).lower() == "dark" else "light",
        "tokens": _string_map(theme_data.get("tokens", {})),
    }


def builtin_themes() -> dict[str, dict[str, Any]]:
    return {
        theme_id: _normalize_theme(theme_id, theme_data)
        for theme_id, theme_data in BUILTIN_THEMES.items()
    }


def load_ui_colors(path: Path) -> dict[str, Any]:
    data = load_yaml_or_json(path) if path.exists() else {}
    if not isinstance(data, dict):
        data = {}
    themes: dict[str, dict[str, Any]] = builtin_themes()
    themes_raw = data.get("themes", {})
    if not isinstance(themes_raw, dict):
        themes_raw = {}
    for theme_id, theme_data in themes_raw.items():
        if not isinstance(theme_data, dict):
            continue
        normalized_id = normalize_theme_id(theme_id, default="")
        if not normalized_id:
            continue
        normalized = _normalize_theme(normalized_id, theme_data)
        if normalized_id in themes:
            base = themes[normalized_id]
            normalized["tokens"] = {**_string_map(base.get("tokens", {})), **normalized["tokens"]}
        themes[normalized_id] = normalized
    return {
        "ramps": data.get("ramps", {}) if isinstance(data.get("ramps", {}), dict) else {},
        "tokens": _string_map(data.get("tokens", {})),
        "themes": themes,
    }


ui_colors = load_ui_colors(paths.config / "ui_colors.yaml")


def tolerate_missing_process_pool() -> None:
    """Keep NiceGUI alive when multiprocessing is blocked by the environment.

    NiceGUI initializes a process pool even when the GUI only uses thread/io-bound
    jobs. Some portable, sandboxed, or enterprise Windows environments reject the
    underlying multiprocessing handles, but the shell can still work without CPU
    pool tasks.
    """
    try:
        import nicegui.run as nicegui_run  # type: ignore
    except Exception:
        return

    original_setup = getattr(nicegui_run, "setup", None)
    if not callable(original_setup):
        return

    def safe_setup() -> None:
        try:
            original_setup()
        except (OSError, PermissionError) as exc:
            logging.warning("NiceGUI process pool disabled: %s", exc)
            nicegui_run.process_pool = None

    nicegui_run.setup = safe_setup


tolerate_missing_process_pool()

LABELS = {
    "ru": {
        "workspace": "Рабочие папки",
        "operations": "Операции",
        "maintenance": "Обслуживание",
        "status": "Статус",
        "log": "Журнал операции",
        "idle": "Ожидание",
        "running": "Выполняется",
        "done": "Готово",
        "error": "Ошибка",
        "cancel": "Отменить",
        "another_running": "Другая операция уже выполняется.",
        "confirm_title": "Подтвердите действие",
        "confirm_note": "Действие может изменить управляемую рабочую область.",
        "confirm_impact_title": "Что произойдет",
        "confirm_irreversible_note": "Проверьте параметры перед запуском. Если операция трогает диски, сеть, системные службы или учетные записи, откат может потребовать ручного восстановления.",
        "confirm_parameters_note": "Текущие параметры будут использованы ровно в этом виде.",
        "confirm_run_dangerous": "Понимаю, запустить",
        "run": "Запустить",
        "back": "Назад",
        "selected_operation": "Выбрана команда",
        "open_menu": "Открыть",
        "parameters": "Параметры",
        "advanced": "Дополнительно",
        "actions": "Действия",
        "section_advanced": "Дополнительно",
        "section_access": "Ключи и доступ",
        "section_cloud_access": "Платные API",
        "section_deliverables": "Готовые файлы",
        "section_encoding": "Движок",
        "section_format": "Формат",
        "section_filters": "Препроцессинг",
        "section_input_mode": "Режим входных файлов",
        "section_local_access": "Локально / 2-pass",
        "section_documents": "Документы",
        "section_layout": "Раскладка",
        "section_model": "Модели OCR",
        "section_options": "Постобработка",
        "section_output": "Результат",
        "section_output_mode": "Режим выходных файлов",
        "section_parameters": "Промпт и параметры",
        "section_preset": "Профиль",
        "section_run": "Запуск",
        "section_source": "Источник",
        "section_workbench": "Workbench",
        "close": "Закрыть",
        "logs": "Logs",
        "report": "Report",
        "config": "CONFIG",
        "expand": "Развернуть",
        "clear_terminal_window": "Очистить окно терминала",
        "add_files": "Добавить файлы...",
        "add_folder": "Добавить папку...",
        "source_folder": "Источник",
        "target_folder": "Назначение",
        "source_selected": "Источник выбран.",
        "target_selected": "Назначение выбрано.",
        "source_folder_missing": "Источник не найден: {path}",
        "clear_io_short": "Сбросить",
        "delete_io_short": "Удалить",
        "file_list_button": "Список",
        "path_required": "Выберите путь.",
        "path_pinned": "Путь закреплён.",
        "path_unpinned": "Путь откреплён.",
        "file_list": "File List",
        "file_list_empty": "INPUT has no files.",
        "file_list_missing": "INPUT was not found: {path}",
        "file_list_ready": "File list generated: {count}.",
        "terminal_file": "File",
        "source_path": "Источник",
        "destination_path": "Назначение",
        "pick_source_file": "Выбрать файл источника",
        "pick_source_folder": "Выбрать папку источника",
        "pick_destination_folder": "Выбрать папку назначения",
        "stage_files": "Добавление файлов в input",
        "stage_folder": "Добавление папки в input",
        "picker_cancelled": "Выбор отменен.",
        "operation_done": "Операция завершена.",
        "operation_failed": "Операция завершилась с кодом {code}.",
        "select_required": "Выберите хотя бы один пункт: {field}",
        "refresh_options": "Обновить список",
        "theme": "Тема",
        "theme_saved": "Тема сохранена. Перезагружаю интерфейс.",
        "lang_switch": "EN",
        "install_tesseract": "Tesseract (рекомендуется)",
        "install_tesseract_tip": "Установить или обновить рекомендуемый portable Tesseract",
    },
    "en": {
        "workspace": "Workspace folders",
        "operations": "Operations",
        "maintenance": "Maintenance",
        "status": "Status",
        "log": "Operation log",
        "idle": "Idle",
        "running": "Running",
        "done": "Done",
        "error": "Error",
        "cancel": "Cancel",
        "another_running": "Another operation is already running.",
        "confirm_title": "Confirm action",
        "confirm_note": "This action may change the managed workspace.",
        "confirm_impact_title": "What will happen",
        "confirm_irreversible_note": "Check the parameters before running. If the operation touches disks, network, system services, or accounts, rollback may require manual recovery.",
        "confirm_parameters_note": "The current parameters will be used exactly as shown.",
        "confirm_run_dangerous": "I understand, run",
        "run": "Run",
        "back": "Back",
        "selected_operation": "Selected command",
        "open_menu": "Open",
        "parameters": "Parameters",
        "advanced": "Advanced",
        "actions": "Actions",
        "section_advanced": "Advanced",
        "section_access": "Keys and access",
        "section_cloud_access": "Paid APIs",
        "section_deliverables": "Deliverables",
        "section_encoding": "Engine",
        "section_format": "Format",
        "section_filters": "Preprocess",
        "section_input_mode": "Input file mode",
        "section_local_access": "Local / 2-pass",
        "section_documents": "Documents",
        "section_layout": "Layout",
        "section_model": "OCR models",
        "section_options": "Postprocess",
        "section_output": "Output",
        "section_output_mode": "Output file mode",
        "section_parameters": "Prompt and params",
        "section_preset": "Profile",
        "section_run": "Run",
        "section_source": "Source",
        "section_workbench": "Workbench",
        "close": "Close",
        "logs": "Logs",
        "report": "Report",
        "config": "CONFIG",
        "expand": "Expand",
        "clear_terminal_window": "Clear terminal window",
        "add_files": "Add files...",
        "add_folder": "Add folder...",
        "source_folder": "Source",
        "target_folder": "Target",
        "source_selected": "Source selected.",
        "target_selected": "Target selected.",
        "source_folder_missing": "Source was not found: {path}",
        "clear_io_short": "Reset",
        "delete_io_short": "Delete",
        "file_list_button": "List",
        "path_required": "Choose a path.",
        "path_pinned": "Path pinned.",
        "path_unpinned": "Path unpinned.",
        "file_list": "File List",
        "file_list_empty": "INPUT has no files.",
        "file_list_missing": "INPUT was not found: {path}",
        "file_list_ready": "File list generated: {count}.",
        "terminal_file": "File",
        "source_path": "Source",
        "destination_path": "Destination",
        "pick_source_file": "Pick source file",
        "pick_source_folder": "Pick source folder",
        "pick_destination_folder": "Pick destination folder",
        "stage_files": "Adding files to input",
        "stage_folder": "Adding folder to input",
        "picker_cancelled": "Selection cancelled.",
        "operation_done": "Operation finished.",
        "operation_failed": "Operation finished with exit code {code}.",
        "select_required": "Select at least one item: {field}",
        "refresh_options": "Refresh list",
        "theme": "Theme",
        "theme_saved": "Theme saved. Reloading UI.",
        "lang_switch": "RU",
        "install_tesseract": "Tesseract (recommended)",
        "install_tesseract_tip": "Install or refresh recommended portable Tesseract",
    },
}

PICKER_BOOTSTRAP = r"""
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
try {
  Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class AudionDpiAwareness {
  [DllImport("user32.dll")]
  public static extern bool SetProcessDpiAwarenessContext(IntPtr dpiContext);
  [DllImport("shcore.dll")]
  public static extern int SetProcessDpiAwareness(int value);
}
"@
  try { [AudionDpiAwareness]::SetProcessDpiAwarenessContext([IntPtr](-4)) | Out-Null }
  catch { [AudionDpiAwareness]::SetProcessDpiAwareness(2) | Out-Null }
} catch {}
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
"""

state: dict[str, Any] = {
    "running": False,
    "cancel": False,
    "progress": 0.0,
    "status": "",
    "lines": [],
    "line_offset": 0,
    "log_version": 0,
    "terminal_scroll_top_seq": 0,
    "exit_code": None,
    "command_path": [],
    "pending_command": None,
    "project_tools_mode": "install",
    "field_values": {},
    "source_path": settings.source_path,
    "destination_path": settings.destination_path,
}

dynamic_option_cache: dict[str, tuple[float, list[Any]]] = {}
hardware_badge_cache: tuple[float, dict[str, Any]] | None = None

TERMINAL_HISTORY_LIMIT = 1500
TERMINAL_MAIN_PRE_ID = "audion-terminal-main-pre"
TERMINAL_EXPANDED_PRE_ID = "audion-terminal-expanded-pre"
HARDWARE_BADGE_CACHE_SECONDS = 300.0
PATH_HISTORY_LIMIT = 100


def tr(key: str, **kwargs: Any) -> str:
    lang = settings.language if settings.language in LABELS else "en"
    text = LABELS.get(lang, LABELS["en"]).get(key, key)
    return text.format(**kwargs) if kwargs else text


def em(key: str) -> str:
    if not bool(getattr(settings, "emoji", False)):
        return ""
    return {
        "workspace": "📁 ",
        "operations": "⚙ ",
        "maintenance": "🧰 ",
        "status": "● ",
        "log": "🖥 ",
    }.get(key, "")


def app_title() -> str:
    title = str(ui_info.get("title") or tool_info.get("name") or "Audion GUI Tool")
    return title[:-3] if title.endswith(" UI") else title


def active_theme() -> str:
    theme_id = normalize_theme_id(settings.theme)
    themes = ui_colors["themes"]
    if theme_id in themes:
        return theme_id
    return DEFAULT_THEME_ID if DEFAULT_THEME_ID in themes else next(iter(themes))


def active_theme_data() -> dict[str, Any]:
    return dict(ui_colors["themes"][active_theme()])


def active_theme_mode() -> str:
    return str(active_theme_data().get("mode", "dark"))


def theme_label(theme_id: str) -> str:
    theme_data = ui_colors["themes"].get(theme_id, {})
    label_key = "label_ru" if settings.language == "ru" else "label"
    return str(theme_data.get(label_key) or theme_data.get("label") or theme_id)


def theme_options() -> dict[str, str]:
    return {theme_id: theme_label(theme_id) for theme_id in ui_colors["themes"]}


def set_theme(theme_id: Any) -> None:
    selected = normalize_theme_id(theme_id)
    if selected not in ui_colors["themes"]:
        return
    settings.theme = selected
    save_app_settings()
    safe_notify(tr("theme_saved"), "positive")
    reload_ui()


def theme_change_handler(event: Any) -> None:
    set_theme(getattr(event, "value", None))

def reload_ui(delay_ms: int = 0) -> None:
    script = f"""
    window.setTimeout(() => {{
      try {{
        if ('scrollRestoration' in window.history) window.history.scrollRestoration = 'manual';
        window.sessionStorage.setItem('audion_force_scroll_top', '1');
        window.scrollTo(0, 0);
        document.documentElement.scrollTop = 0;
        document.body.scrollTop = 0;
      }} catch (error) {{}}
      window.location.reload();
    }}, {max(0, int(delay_ms))});
    """
    delivered = False
    for client in list(nicegui_app.clients()):
        if getattr(client, "_deleted", False) or not client.has_socket_connection:
            continue
        client.run_javascript(script)
        delivered = True
    if not delivered:
        ui.run_javascript(script)

def theme_variables() -> dict[str, str]:
    variables: dict[str, str] = {}
    for ramp_name, stops in ui_colors["ramps"].items():
        if not isinstance(stops, dict):
            continue
        for stop, color in stops.items():
            variables[f"color-{ramp_name}-{stop}"] = str(color).strip()
    variables.update(ui_colors["tokens"])
    variables.update(_string_map(active_theme_data().get("tokens", {})))
    variables.setdefault("color-background-primary", "#141413")
    variables.setdefault("color-background-secondary", "#1f1e1a")
    variables.setdefault("color-background-tertiary", "#0f0f0e")
    variables.setdefault("color-text-primary", "#faf9f5")
    variables.setdefault("color-text-secondary", "#e8e6dc")
    variables.setdefault("color-text-tertiary", "#b0aea5")
    variables.setdefault("color-border-tertiary", "rgba(250, 249, 245, 0.15)")
    variables.setdefault("color-border-secondary", "rgba(250, 249, 245, 0.3)")
    variables.setdefault("color-border-primary", "rgba(250, 249, 245, 0.4)")
    variables.setdefault("color-accent-primary", "#d97757")
    variables.setdefault("font-sans", "Inter, Segoe UI, Arial, sans-serif")
    variables.setdefault("font-mono", "Cascadia Mono, Consolas, monospace")
    variables.setdefault("border-radius-md", "8px")
    variables.setdefault("border-radius-lg", "12px")
    return variables


def add_log(message: str) -> None:
    if not str(message).strip():
        return
    state["lines"].append(str(message).rstrip())
    overflow = max(0, len(state["lines"]) - TERMINAL_HISTORY_LIMIT)
    if overflow:
        del state["lines"][:overflow]
        state["line_offset"] = int(state.get("line_offset", 0)) + overflow
    state["log_version"] = int(state["log_version"]) + 1


def clear_terminal_log() -> None:
    state["lines"] = []
    state["line_offset"] = 0
    state["terminal_scroll_top_seq"] = 0
    state["log_version"] = int(state["log_version"]) + 1


def terminal_line_spans_html(lines: list[str], start_index: int) -> str:
    chunks: list[str] = []
    for index, line in enumerate(lines):
        line_html = terminal_lines_html([str(line)])
        chunks.append(f'<span class="audion-terminal-line" data-line="{start_index + index}">{line_html}</span>')
    return "".join(chunks)


def terminal_pre_html(element_id: str) -> str:
    start_index = int(state.get("line_offset", 0))
    content = terminal_line_spans_html([str(line) for line in state["lines"]], start_index)
    return f'<pre id="{element_id}" class="audion-terminal-pre">{content}</pre>'


def progress_text() -> str:
    return f"{round(max(0.0, min(1.0, float(state['progress']))) * 100):.0f}%"


def safe_notify(message: str, kind: str = "info", **notify_kwargs: Any) -> None:
    notify_type = str(notify_kwargs.pop("type", kind))
    options = {"message": str(message), "type": notify_type, **notify_kwargs}
    delivered = False
    for client in list(nicegui_app.clients()):
        if getattr(client, "_deleted", False) or not client.has_socket_connection:
            continue
        try:
            client.outbox.enqueue_message("notify", options, client.id)
            delivered = True
        except Exception as exc:
            logging.warning("NiceGUI notification delivery failed for client %s: %s", getattr(client, "id", "?"), exc)
    if delivered:
        return

    try:
        ui.notify(message, type=notify_type, **notify_kwargs)
    except RuntimeError as exc:
        message_text = str(exc)
        if "slot belongs to has been deleted" not in message_text and "current slot cannot be determined" not in message_text:
            raise
        logging.warning("NiceGUI notification skipped because no live client slot was available: %s", message)


def dangerous_operation_notes(operation: Operation) -> list[str]:
    text = " ".join(
        [
            operation.id,
            operation.service,
            operation.display_title(settings.language),
            operation.display_description(settings.language),
        ]
    ).lower()
    notes: list[str] = []

    if any(word in text for word in ("disk", "partition", "format", "wipe", "winre", "diskpart", "vhd", "drive")):
        notes.append(
            "Возможны изменения дисков, разделов, VHD/образов или загрузочного окружения."
            if settings.language == "ru"
            else "Disk, partition, VHD/image, or recovery-boot data may be changed."
        )
    if any(word in text for word in ("network", "netsh", "wifi", "wi-fi", "winsock", "proxy", "adapter", "tcp", "ip", "dns")):
        notes.append(
            "Возможны сброс сети, переподключение адаптеров, изменение proxy/DNS или Wi-Fi профилей."
            if settings.language == "ru"
            else "Network reset, adapter reconnect, proxy/DNS, or Wi-Fi profile changes may occur."
        )
    if any(word in text for word in ("delete", "remove", "clean", "cleanup", "purge", "unregister", "reset")):
        notes.append(
            "Файлы, кэши, профили или зарегистрированные сущности могут быть удалены."
            if settings.language == "ru"
            else "Files, caches, profiles, or registered entities may be removed."
        )
    if any(word in text for word in ("wsl", "linux", "distro", "distribution", "import", "install", "export", "clone")):
        notes.append(
            "WSL-дистрибутивы могут быть созданы, импортированы, перемещены, экспортированы или перерегистрированы."
            if settings.language == "ru"
            else "WSL distributions may be created, imported, moved, exported, or registered again."
        )
    if any(word in text for word in ("admin", "uac", "elevat", "feature", "optionalfeature", "dism", "bcdedit", "set-service", "start-service", "stop-service", "sc.exe")):
        notes.append(
            "Windows может запросить UAC, а системные компоненты могут потребовать перезагрузку."
            if settings.language == "ru"
            else "Windows may request UAC, and system components may require a reboot."
        )

    if not notes:
        notes.append(operation.display_description(settings.language) or tr("confirm_parameters_note"))
    notes.append(tr("confirm_parameters_note"))
    return notes


RUN_STATE_LABELS = {
    "idle": ("idle", "audion-status-idle"),
    "running": ("running", "audion-status-running"),
    "done": ("done", "audion-status-done"),
    "error": ("error", "audion-status-error"),
}


def run_state() -> str:
    """Which of the four states the panel is showing.

    Colour carries this everywhere it appears, so it is decided once.
    """
    if bool(state["running"]):
        return "running"
    exit_code = state.get("exit_code")
    if exit_code is None:
        return "idle"
    return "done" if int(exit_code or 0) == 0 else "error"


def status_row_classes() -> str:
    return f"audion-status-row {RUN_STATE_LABELS[run_state()][1]}"


def status_state_text() -> str:
    return tr(RUN_STATE_LABELS[run_state()][0]).upper()


def elapsed_text(seconds: float | None) -> str:
    """A run's own clock, mm:ss, or an em dash before anything has run.

    The start is noticed by the refresh timer rather than written by the code that
    starts a run: there are several such places, and none of them has to know
    about the panel.
    """
    if seconds is None:
        return "—"
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def status_dot_classes() -> str:
    base = "audion-status-dot text-lg leading-none"
    if bool(state["running"]):
        return f"{base} text-sky-400 animate-pulse"
    if state.get("exit_code") is None:
        return f"{base} text-gray-500"
    if int(state.get("exit_code") or 0) == 0:
        return f"{base} text-green-400"
    return f"{base} text-red-400"


def _powershell_exe() -> str | None:
    portable = ROOT / "system_core" / "powershell" / "pwsh.exe"
    if portable.exists():
        return str(portable)
    for name in ("pwsh.exe", "powershell.exe"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _powershell_json(script: str, timeout: float = 4.0) -> Any:
    exe = _powershell_exe()
    if not exe:
        return None
    wrapped = (
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
        "$OutputEncoding = [Console]::OutputEncoding; "
        f"{script}"
    )
    try:
        proc = subprocess.run(
            [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", wrapped],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=hidden_subprocess_flags(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    text = (proc.stdout or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _video_controllers() -> list[dict[str, Any]]:
    data = _powershell_json(
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterCompatibility,DriverVersion,PNPDeviceID,AdapterRAM | "
        "ConvertTo-Json -Compress -Depth 3"
    )
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _cpu_name() -> str:
    data = _powershell_json(
        "Get-CimInstance Win32_Processor | "
        "Select-Object -First 1 -ExpandProperty Name | ConvertTo-Json -Compress"
    )
    return str(data or "").strip()


def _best_gpu_name(controllers: list[dict[str, Any]]) -> str:
    names = [str(item.get("Name") or "").strip() for item in controllers if str(item.get("Name") or "").strip()]
    if not names:
        return ""
    discrete_markers = ("nvidia", "rtx", "gtx", "radeon", "arc")
    for name in names:
        low = name.lower()
        if any(marker in low for marker in discrete_markers):
            return name
    return names[0]


def _gpu_generation(name: str) -> str:
    low = name.lower()
    if "nvidia" in low or "geforce" in low or "rtx" in low or "gtx" in low:
        match = re.search(r"\b(?:rtx|gtx)?\s*([2453][0-9]{3})\b", low, re.IGNORECASE)
        if match:
            series = int(match.group(1)) // 1000
            if series >= 5:
                return "nvidia50"
            if series >= 4:
                return "nvidia40"
            return "nvidia"
        return "nvidia"
    if "amd" in low or "radeon" in low:
        return "vulkan"
    if "intel" in low or "iris" in low or "arc" in low:
        return "vulkan"
    return "unknown"


def _hardware_recommended_installs(generation: str) -> tuple[list[str], list[str]]:
    base = ["install_tesseract", "install_realesrgan", "surya_acceleration", "install_surya_cpu"]
    if generation == "nvidia50":
        return [*base, "install_llamacpp_cuda133"], ["install_surya_pytorch_cuda50"]
    if generation == "nvidia40":
        return [*base, "install_llamacpp_cuda124"], ["install_surya_pytorch_cuda40"]
    if generation == "nvidia":
        return [*base, "install_llamacpp_cuda124"], []
    if generation == "vulkan":
        return [*base, "install_llamacpp_vulkan"], []
    return ["install_tesseract"], ["install_realesrgan", "surya_acceleration", "install_surya_cpu", "install_llamacpp_vulkan"]


def _hardware_recommendation(gpu_name: str) -> dict[str, Any]:
    generation = _gpu_generation(gpu_name)
    recommended_install_ids, optional_install_ids = _hardware_recommended_installs(generation)
    common = {
        "generation": generation,
        "surya_backend": "llamacpp",
        "recommended_install_ids": recommended_install_ids,
        "optional_install_ids": optional_install_ids,
    }
    if settings.language == "ru":
        if generation == "nvidia50":
            return {
                **common,
                "tone": "nvidia",
                "headline": "NVIDIA RTX 50xx обнаружена",
                "short": "Рекомендовано: llama.cpp CUDA 13.3",
                "details": "Surya backend выбирается автоматически: llama.cpp. PyTorch CUDA 50xx/cu128 остаётся тяжёлым optional benchmark.",
            }
        if generation in {"nvidia40", "nvidia"}:
            return {
                **common,
                "tone": "nvidia",
                "headline": "NVIDIA GPU обнаружена",
                "short": "Рекомендовано: llama.cpp CUDA 12.4",
                "details": "Surya backend выбирается автоматически: llama.cpp. PyTorch CUDA/cu128 ставим только если нужен benchmark кратного ускорения.",
            }
        if generation == "vulkan":
            return {
                **common,
                "tone": "vulkan",
                "headline": "Vulkan GPU обнаружена",
                "short": "Рекомендовано: llama.cpp Vulkan",
                "details": "Surya backend выбирается автоматически: llama.cpp. Пользователь настраивает очистку, а не backend.",
            }
        return {
            **common,
            "tone": "cpu",
            "headline": "GPU не распознана",
            "short": "Рекомендовано: Vulkan, затем CPU/API",
            "details": "Surya backend выбирается автоматически: llama.cpp. Если Vulkan не заработает, остаётся CPU или API OCR.",
        }
    if generation == "nvidia50":
        return {
            **common,
            "tone": "nvidia",
            "headline": "NVIDIA RTX 50xx detected",
            "short": "Recommended: llama.cpp CUDA 13.3",
            "details": "Surya backend is automatic: llama.cpp. PyTorch CUDA 50xx/cu128 stays a heavy optional benchmark.",
        }
    if generation in {"nvidia40", "nvidia"}:
        return {
            **common,
            "tone": "nvidia",
            "headline": "NVIDIA GPU detected",
            "short": "Recommended: llama.cpp CUDA 12.4",
            "details": "Surya backend is automatic: llama.cpp. Install PyTorch CUDA/cu128 only for multiple-speed benchmarks.",
        }
    if generation == "vulkan":
        return {
            **common,
            "tone": "vulkan",
            "headline": "Vulkan GPU detected",
            "short": "Recommended: llama.cpp Vulkan",
            "details": "Surya backend is automatic: llama.cpp. Users tune cleanup, not backend plumbing.",
        }
    return {
        **common,
        "tone": "cpu",
        "headline": "GPU not identified",
        "short": "Recommended: Vulkan, then CPU/API",
        "details": "Surya backend is automatic: llama.cpp. If Vulkan is not visible, use CPU or API OCR.",
    }


def hardware_badge_data(force: bool = False) -> dict[str, Any]:
    global hardware_badge_cache
    now = time.monotonic()
    if not force and hardware_badge_cache and now - hardware_badge_cache[0] < HARDWARE_BADGE_CACHE_SECONDS:
        return dict(hardware_badge_cache[1])
    controllers = _video_controllers()
    gpu_name = _best_gpu_name(controllers)
    cpu_name = _cpu_name()
    data = {
        "gpu": gpu_name or ("GPU не найдена" if settings.language == "ru" else "GPU not found"),
        "cpu": cpu_name,
        **_hardware_recommendation(gpu_name),
    }
    hardware_badge_cache = (now, dict(data))
    return data


def refresh_hardware_badge() -> None:
    hardware_badge_data(force=True)
    hardware_badge.refresh()


@ui.refreshable
def hardware_badge() -> None:
    data = hardware_badge_data()
    tone = str(data.get("tone") or "cpu")
    refresh_title = "Обновить GPU/CPU" if settings.language == "ru" else "Refresh GPU/CPU"
    with ui.element("div").classes(f"audion-hardware-badge audion-hardware-badge-{tone}"):
        with ui.element("div").classes("audion-hardware-main"):
            with ui.row().classes("audion-hardware-headline w-full items-center gap-2"):
                ui.icon("memory").classes("audion-hardware-icon")
                ui.label(str(data.get("headline") or "")).classes("audion-hardware-title")
            ui.label(str(data.get("gpu") or "")).classes("audion-hardware-gpu")
            ui.label(str(data.get("short") or "")).classes("audion-hardware-recommendation")
        with ui.element("div").classes("audion-hardware-side"):
            with ui.row().classes("audion-hardware-side-top w-full items-center gap-2"):
                cpu_name = str(data.get("cpu") or "").strip()
                if cpu_name:
                    ui.label(cpu_name).classes("audion-hardware-cpu")
                ui.space()
                refresh_button = ui.button(icon="refresh", on_click=refresh_hardware_badge).props("dense flat round")
                refresh_button.classes("audion-action audion-hardware-refresh")
                refresh_button.tooltip(refresh_title)
            ui.label(str(data.get("details") or "")).classes("audion-hardware-details")


def set_progress(value: float) -> None:
    state["progress"] = max(0.0, min(1.0, float(value)))


def cancel_requested() -> bool:
    return bool(state["cancel"])


def hidden_subprocess_flags() -> int:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return int(subprocess.CREATE_NO_WINDOW)
    return 0


def hidden_subprocess_startupinfo() -> subprocess.STARTUPINFO | None:
    if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return startupinfo


def resolve_dialog_powershell() -> list[str]:
    candidates = [
        [str(paths.system_core / "powershell" / "pwsh.exe"), "-NoLogo", "-NoProfile", "-STA", "-Command"],
        ["pwsh.exe", "-NoLogo", "-NoProfile", "-STA", "-Command"],
        ["powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command"],
    ]
    for candidate in candidates:
        exe = candidate[0]
        if Path(exe).exists() or shutil.which(exe):
            return candidate
    raise RuntimeError("PowerShell was not found for Windows picker.")


_PICKER_RUN_LOCK = threading.Lock()
_PICKER_JOB_LOCK = threading.Lock()
_PICKER_JOB_HANDLE: int | None = None


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def close_picker_job() -> None:
    global _PICKER_JOB_HANDLE
    with _PICKER_JOB_LOCK:
        handle = _PICKER_JOB_HANDLE
        _PICKER_JOB_HANDLE = None
    if os.name == "nt" and handle:
        ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(wintypes.HANDLE(handle))


def _picker_job_handle() -> int | None:
    global _PICKER_JOB_HANDLE
    if os.name != "nt":
        return None
    with _PICKER_JOB_LOCK:
        if _PICKER_JOB_HANDLE:
            return _PICKER_JOB_HANDLE
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            logging.warning("Could not create the Windows picker job: %s", ctypes.get_last_error())
            return None
        info = _JobObjectExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        configured = kernel32.SetInformationJobObject(
            wintypes.HANDLE(job),
            9,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not configured:
            error = ctypes.get_last_error()
            kernel32.CloseHandle(wintypes.HANDLE(job))
            logging.warning("Could not configure the Windows picker job: %s", error)
            return None
        _PICKER_JOB_HANDLE = int(job)
        return _PICKER_JOB_HANDLE


def _assign_picker_to_job(process: subprocess.Popen[str]) -> None:
    handle = _picker_job_handle()
    if os.name != "nt" or not handle:
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    assigned = kernel32.AssignProcessToJobObject(
        wintypes.HANDLE(handle),
        wintypes.HANDLE(int(process._handle)),  # type: ignore[attr-defined]
    )
    if not assigned:
        logging.warning("Could not attach picker PID %s to its Windows job: %s", process.pid, ctypes.get_last_error())


def run_picker_script(script: str, failure_message: str) -> str:
    if not _PICKER_RUN_LOCK.acquire(blocking=False):
        raise RuntimeError("A Windows picker is already open.")
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            [*resolve_dialog_powershell(), script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=hidden_subprocess_flags(),
            startupinfo=hidden_subprocess_startupinfo(),
        )
        _assign_picker_to_job(process)
        try:
            stdout, stderr = process.communicate(timeout=3600)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise RuntimeError("Windows picker timed out.") from exc
        if process.returncode != 0:
            raise RuntimeError(stderr.strip() or failure_message)
        return stdout
    finally:
        if process is not None and process.poll() is None:
            process.kill()
        _PICKER_RUN_LOCK.release()


atexit.register(close_picker_job)
nicegui_app.on_shutdown(close_picker_job)


def parse_picker_paths(text: str) -> list[Path]:
    import json

    payload = text.strip()
    if not payload:
        return []
    data = json.loads(payload)
    if isinstance(data, str):
        data = [data]
    return [Path(str(item)).resolve() for item in data if str(item).strip()]




def pick_single_file() -> list[Path]:
    script = PICKER_BOOTSTRAP + r"""
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = 'Choose one source file'
$dialog.Multiselect = $false
$dialog.Filter = 'All supported files|*.*|All files|*.*'
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  $dialog.FileName | ConvertTo-Json -Compress
}
"""
    return parse_picker_paths(run_picker_script(script, "File picker failed."))


def pick_folder(title: str = "Add folder to input", allow_new_folder: bool = False) -> list[Path]:
    script = PICKER_BOOTSTRAP + r"""
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '__TITLE__'
$dialog.ShowNewFolderButton = __ALLOW_NEW_FOLDER__
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  @($dialog.SelectedPath) | ConvertTo-Json -Compress
}
""".replace("__TITLE__", title.replace("'", "''")).replace("__ALLOW_NEW_FOLDER__", "$true" if allow_new_folder else "$false")
    return parse_picker_paths(run_picker_script(script, "Folder picker failed."))


def absolute_project_path(path_value: Any) -> Path:
    path = Path(str(path_value or "")).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path


def remove_path_tree(path: Path) -> int:
    is_junction = bool(getattr(os.path, "isjunction", lambda _path: False)(path))
    if path.is_symlink() or is_junction:
        if path.is_dir():
            path.rmdir()
        else:
            path.unlink()
        return 1
    if path.is_file():
        path.unlink()
        return 1
    if path.is_dir():
        shutil.rmtree(path)
        return 1
    return 0


def clear_directory_contents(folder: Path) -> int:
    removed = 0
    if not folder.exists():
        return removed
    for child in sorted(folder.iterdir(), key=lambda item: item.name.casefold()):
        # .gitkeep is not spared: input and output must be genuinely empty after
        # a clear, so nobody has to wonder what the leftover file is or whether it
        # is safe to delete. The folders come from install/init_folders.cmd.
        removed += remove_path_tree(child)
    return removed


def normalized_absolute_path(path_value: Any) -> Path:
    return absolute_project_path(path_value).resolve(strict=False)


def paths_equal(left: Any, right: Any) -> bool:
    return os.path.normcase(str(normalized_absolute_path(left))) == os.path.normcase(str(normalized_absolute_path(right)))


def validate_workspace_delete_target(path_value: Any) -> Path:
    target = normalized_absolute_path(path_value)
    if target.parent == target:
        raise RuntimeError(f"Refusing to delete a filesystem root: {target}")
    if paths_equal(target, ROOT):
        raise RuntimeError(f"Refusing to delete the project root: {target}")
    return target


def delete_workspace_path_contents(path_value: Any) -> dict[str, Any]:
    target = validate_workspace_delete_target(path_value)
    if not target.exists() and not target.is_symlink():
        return {"path": str(target), "kind": "missing", "removed": 0}
    is_junction = bool(getattr(os.path, "isjunction", lambda _path: False)(target))
    if target.is_file() or target.is_symlink() or is_junction:
        removed = remove_path_tree(target)
        return {"path": str(target), "kind": "file", "removed": removed}
    if not target.is_dir():
        raise RuntimeError(f"Unsupported workspace path: {target}")
    removed = clear_directory_contents(target)
    return {"path": str(target), "kind": "folder", "removed": removed}


def delete_workspace_io_contents(source: Path, target: Path) -> dict[str, Any]:
    source_result = delete_workspace_path_contents(source)
    if paths_equal(source, target):
        target_result = {"path": str(normalized_absolute_path(target)), "kind": "same", "removed": 0}
    else:
        target_result = delete_workspace_path_contents(target)
    return {"source": source_result, "target": target_result}


def save_workspace_path(kind: str, value: Any) -> None:
    text = str(value or "").strip().strip('"')
    role = canonical_role(kind)
    if role == "target":
        settings.destination_path = text
        state["destination_path"] = text
    else:
        settings.source_path = text
        state["source_path"] = text
    dynamic_option_cache.clear()
    save_app_settings()






def input_file_list_lines(source: Path) -> list[str]:
    if not source.exists():
        return [tr("file_list_missing", path=source)]
    if source.is_file():
        return ["No.  List", "---  ----", f"001. {source.name}"]
    if not source.is_dir():
        return [f"INPUT is not a file or folder: {source}"]

    names = sorted((path.name for path in source.rglob("*") if path.is_file()), key=lambda item: item.casefold())
    if not names:
        return [tr("file_list_empty")]

    number_width = max(3, len(str(len(names))))
    lines = [
        f"{'No.':>{number_width}}  List",
        f"{'-' * number_width}  ----",
    ]
    lines.extend(f"{index:0{number_width}d}. {name}" for index, name in enumerate(names, start=1))
    return lines


async def show_input_file_list() -> None:
    if state["running"]:
        safe_notify(tr("another_running"), "warning")
        return

    title = tr("file_list")
    state.update(
        {
            "running": True,
            "cancel": False,
            "progress": 0.02,
            "status": f"{tr('running')}: {title}",
            "lines": [],
            "line_offset": int(state.get("line_offset", 0)) + len(state.get("lines", [])) + 1,
            "log_version": int(state["log_version"]) + 1,
            "exit_code": None,
        }
    )
    try:
        lines = await run.io_bound(input_file_list_lines, current_source_path())
        for line in lines:
            add_log(line)
        count = max(0, len(lines) - 2)
        state["terminal_scroll_top_seq"] = int(state["log_version"])
        state["exit_code"] = 0
        state["progress"] = 1.0
        state["status"] = f"{tr('done')}: {title} [{count}]"
        safe_notify(tr("file_list_ready", count=count), "positive")
    except Exception as exc:
        state["exit_code"] = 1
        state["progress"] = max(float(state["progress"]), 0.98)
        state["status"] = f"{tr('error')}: {exc}"
        add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
        safe_notify(str(exc), "negative")
    finally:
        state["running"] = False




async def start_operation(operation: Operation) -> None:
    if state["running"]:
        safe_notify(tr("another_running"), "warning")
        return

    if operation.kind == "dangerous":
        with ui.dialog() as dialog, ui.card().classes("audion-dialog audion-confirm-card rounded-lg"):
            ui.label(tr("confirm_title")).classes("text-base font-semibold")
            ui.label(operation.display_title(settings.language)).classes("text-sm font-semibold")
            description = operation.display_description(settings.language)
            if description:
                ui.label(description).classes("text-sm text-gray-400")
            ui.label(tr("confirm_impact_title")).classes("audion-confirm-subtitle")
            for note in dangerous_operation_notes(operation):
                ui.label(f"- {note}").classes("audion-confirm-note")
            ui.label(tr("confirm_irreversible_note")).classes("audion-confirm-warning")
            with ui.row().classes("w-full items-center justify-end gap-2"):
                ui.button(tr("cancel"), on_click=dialog.close).props("dense flat").classes("audion-action rounded-lg")
                ui.button(tr("confirm_run_dangerous"), on_click=lambda: dialog.submit(True)).props("dense flat no-wrap").classes("audion-action rounded-lg")
        confirmed = await dialog
        if not confirmed:
            return

    state.update(
        {
            "running": True,
            "cancel": False,
            "progress": 0.02,
            "status": f"{tr('running')}: {operation.display_title(settings.language)}",
            "lines": [],
            "line_offset": 0,
            "log_version": int(state["log_version"]) + 1,
            "exit_code": None,
        }
    )
    started = time.perf_counter()
    try:
        routed_operation = replace(
            operation,
            parameters={
                **operation.parameters,
                "_workbench_source_path": str(current_source_path()),
                "_workbench_target_path": str(current_target_path()),
            },
        )
        result = await run.io_bound(
            execute_operation,
            active_project_paths(),
            routed_operation,
            add_log,
            set_progress,
            cancel_requested,
        )
        elapsed = time.perf_counter() - started
        state["exit_code"] = 0 if result.ok else 1
        state["progress"] = 1.0
        state["status"] = f"{tr('done') if result.ok else tr('error')}: {operation.display_title(settings.language)} [{state['exit_code']}] {elapsed:.1f}s"
        safe_notify(result.message, "positive" if result.ok else "negative")
    except Exception as exc:
        state["exit_code"] = 1
        state["progress"] = max(float(state["progress"]), 0.98)
        state["status"] = f"{tr('error')}: {exc}"
        add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
        safe_notify(str(exc), "negative")
    finally:
        state["running"] = False


def toggle_language() -> None:
    settings.language = "en" if settings.language == "ru" else "ru"
    save_app_settings()
    reload_ui()


def save_advanced_open(event: Any) -> None:
    settings.advanced_open = bool(getattr(event, "value", False))
    save_app_settings()


def current_source_path() -> Path:
    return Path(str(state.get("source_path") or getattr(settings, "source_path", "") or paths.input)).expanduser()


def current_target_path() -> Path:
    return Path(str(state.get("destination_path") or getattr(settings, "destination_path", "") or paths.output)).expanduser()


def active_project_paths():
    # Office OCR services own the Source -> managed input -> Target mirror.
    # Passing external Workbench paths as the managed roots bypasses staging and
    # can make legacy scripts read stale project input instead of the selection.
    return paths


def open_workspace_folder(role: str) -> None:
    role_key = canonical_role(role)
    folder = current_target_path() if role_key == "target" else current_source_path()
    if role_key != "target" and not folder.exists():
        raise FileNotFoundError(tr("source_folder_missing", path=folder))
    if folder.is_file():
        if os.name == "nt":
            subprocess.Popen(
                ["explorer.exe", f"/select,{folder}"],
                creationflags=hidden_subprocess_flags(),
                startupinfo=hidden_subprocess_startupinfo(),
            )
        else:
            open_folder(folder.parent)
        return
    open_folder(folder)


def mark_workspace_feedback(role: str, action: str) -> None:
    state["workspace_feedback"] = {
        "role": canonical_role(role),
        "action": str(action or "path"),
    }


def _save_workspace_adapter_path(role: WorkbenchRole, value: Any) -> None:
    save_workspace_path(role, value)


def _workspace_feedback() -> dict[str, str]:
    value = state.get("workspace_feedback")
    return dict(value) if isinstance(value, dict) else {}


def _clear_workspace_feedback() -> None:
    state["workspace_feedback"] = {}


WORKBENCH_CONFIG = WorkbenchConfig(
    root=ROOT,
    input_path=paths.input,
    output_path=paths.output,
    history_path=_workspace_history_file(),
    history_limit=PATH_HISTORY_LIMIT,
)
WORKBENCH_ADAPTER = WorkbenchAdapter(
    config=WORKBENCH_CONFIG,
    current_path_callback=lambda role: current_target_path() if role == "target" else current_source_path(),
    save_path_callback=_save_workspace_adapter_path,
    language_callback=lambda: settings.language,
    translate_callback=tr,
    log_callback=add_log,
    notify_callback=safe_notify,
    reload_callback=reload_ui,
    busy_callback=lambda: bool(state.get("running")),
    feedback_callback=_workspace_feedback,
    set_feedback_callback=mark_workspace_feedback,
    clear_feedback_callback=_clear_workspace_feedback,
)
WORKBENCH_ADAPTER.validate()
WORKBENCH_ADAPTER.ensure_initial_history()


def workspace_pin_click_handler(role: str, pinned: bool):
    async def handler() -> None:
        path_value = str(current_target_path() if role == "target" else current_source_path())
        if not path_value:
            safe_notify(WORKBENCH_ADAPTER.translate("path_required"), "warning")
            return
        try:
            await run.io_bound(WORKBENCH_ADAPTER.set_path_pinned, role, path_value, pinned)
            mark_workspace_feedback(role, "pin" if pinned else "unpin")
            add_log(f"{'Pinned' if pinned else 'Unpinned'} {role} path: {path_value}")
            reload_ui(150)
        except Exception as exc:
            add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
            safe_notify(str(exc), "negative")

    return handler


def workspace_delete_path_click_handler(role: str):
    async def handler() -> None:
        if state["running"]:
            safe_notify(tr("another_running"), "warning")
            return
        role_key = canonical_role(role)
        path = current_target_path() if role_key == "target" else current_source_path()
        path_value = str(path)
        if not path_value:
            safe_notify(WORKBENCH_ADAPTER.translate("path_required"), "warning")
            return
        external_source = role_key == "source" and not paths_equal(path, paths.input)
        if external_source:
            is_file = path.is_file()
            with ui.dialog() as dialog, ui.card().classes("audion-dialog rounded-lg"):
                title = "Удалить исходный файл?" if is_file else "Очистить внешний ИСТОЧНИК?"
                if settings.language != "ru":
                    title = "Delete the source file?" if is_file else "Clear the external SOURCE?"
                ui.label(title).classes("text-base font-semibold")
                warning = (
                    "Будет удалён исходный файл. Другой копии может не существовать."
                    if is_file
                    else "Будут безвозвратно удалены все файлы и вложенные папки."
                )
                if settings.language != "ru":
                    warning = (
                        "The source file will be deleted. Another copy may not exist."
                        if is_file
                        else "All files and nested folders will be permanently deleted."
                    )
                ui.label(warning).classes("text-sm text-gray-300")
                ui.label(str(normalized_absolute_path(path))).classes("max-w-3xl break-all font-mono text-xs text-gray-400")
                with ui.row().classes("gap-2"):
                    ui.button(tr("cancel"), on_click=dialog.close).props("dense flat")
                    ui.button(WORKBENCH_ADAPTER.translate("delete_io_short"), on_click=lambda: dialog.submit(True)).props("dense color=negative")
            if not await dialog:
                return
        try:
            result = await run.io_bound(delete_workspace_path_contents, path)
            if result.get("kind") == "file":
                await run.io_bound(WORKBENCH_ADAPTER.delete_path_history, role_key, path_value)
                save_workspace_path(role_key, "")
            mark_workspace_feedback(role_key, "delete")
            add_log(
                f"Cleared {'TARGET' if role_key == 'target' else 'SOURCE'}: {result.get('path')} "
                f"[kind={result.get('kind')}, removed={result.get('removed', 0)}]"
            )
            reload_ui(150)
        except Exception as exc:
            add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
            safe_notify(str(exc), "negative")

    return handler


def workspace_single_file_click_handler():
    async def handler() -> None:
        if state["running"]:
            safe_notify(tr("another_running"), "warning")
            return
        try:
            selected = await run.io_bound(pick_single_file)
        except Exception as exc:
            add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
            safe_notify(str(exc), "negative")
            return
        if not selected:
            add_log(tr("picker_cancelled"))
            return
        path_value = str(selected[0])
        save_workspace_path("source", path_value)
        await run.io_bound(WORKBENCH_ADAPTER.remember_path, "source", path_value)
        mark_workspace_feedback("source", "path")
        add_log(f"SOURCE FILE -> {path_value}")
        reload_ui(150)

    return handler


def workspace_open_click_handler(role: str):
    async def handler() -> None:
        try:
            await run.io_bound(open_workspace_folder, role)
            role_key = canonical_role(role)
            path = current_target_path() if role_key == "target" else current_source_path()
            add_log(f"Opened {role_key} path: {path}")
        except Exception as exc:
            add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
            safe_notify(str(exc), "negative")

    return handler


def reset_workspace_paths_click_handler():
    async def handler() -> None:
        if state["running"]:
            safe_notify(tr("another_running"), "warning")
            return
        result = await run.io_bound(WORKBENCH_ADAPTER.clear_path_history_cache_keep_pins)
        save_workspace_path("source", "")
        save_workspace_path("target", "")
        add_log(f"Workspace route reset: SOURCE -> {paths.input}")
        add_log(f"Workspace route reset: TARGET -> {paths.output}")
        add_log(
            "Workspace path cache cleared: "
            f"sources={result.get('removed_sources', 0)}, targets={result.get('removed_targets', 0)}, "
            f"pins kept={result.get('kept_pins', 0)}"
        )
        safe_notify(tr("operation_done"), "positive")
        reload_ui()

    return handler


def workspace_path_select_handler(role: str):
    async def handler(event: Any) -> None:
        path_value = str(getattr(event, "value", "") or "").strip()
        if not path_value:
            return
        role_key = canonical_role(role)
        current = current_target_path() if role_key == "target" else current_source_path()
        if paths_equal(current, path_value):
            return
        save_workspace_path(role_key, path_value)
        await run.io_bound(WORKBENCH_ADAPTER.remember_path, role_key, path_value)
        mark_workspace_feedback(role_key, "path")
        add_log(f"{'TARGET' if role_key == 'target' else 'SOURCE'} -> {path_value}")
        reload_ui(150)

    return handler


def workspace_delete_both_click_handler():
    async def handler() -> None:
        if state["running"]:
            safe_notify(tr("another_running"), "warning")
            return
        source = current_source_path()
        target = current_target_path()
        source_external = not paths_equal(source, paths.input)
        with ui.dialog() as dialog, ui.card().classes("audion-dialog rounded-lg"):
            ui.label("Удалить содержимое I/O?" if settings.language == "ru" else "Delete I/O contents?").classes("text-base font-semibold")
            warning = (
                "Будут удалены файлы ИСТОЧНИКА и НАЗНАЧЕНИЯ. Внешний ИСТОЧНИК может быть единственным экземпляром."
                if source_external
                else "Будут удалены файлы ИСТОЧНИКА и НАЗНАЧЕНИЯ."
            )
            if settings.language != "ru":
                warning = (
                    "SOURCE and TARGET files will be deleted. The external SOURCE may be the only copy."
                    if source_external
                    else "SOURCE and TARGET files will be deleted."
                )
            ui.label(warning).classes("text-sm text-gray-300")
            ui.label(f"SOURCE: {normalized_absolute_path(source)}").classes("max-w-3xl break-all font-mono text-xs text-gray-400")
            ui.label(f"TARGET: {normalized_absolute_path(target)}").classes("max-w-3xl break-all font-mono text-xs text-gray-400")
            with ui.row().classes("gap-2"):
                ui.button(tr("cancel"), on_click=dialog.close).props("dense flat")
                ui.button(WORKBENCH_ADAPTER.translate("delete_io_short"), on_click=lambda: dialog.submit(True)).props("dense color=negative")
        if not await dialog:
            return
        state["running"] = True
        try:
            result = await run.io_bound(delete_workspace_io_contents, source, target)
            source_result = result.get("source", {})
            target_result = result.get("target", {})
            if source_result.get("kind") == "file":
                await run.io_bound(WORKBENCH_ADAPTER.delete_path_history, "source", str(source))
                save_workspace_path("source", "")
            if target_result.get("kind") == "file":
                await run.io_bound(WORKBENCH_ADAPTER.delete_path_history, "target", str(target))
                save_workspace_path("target", "")
            add_log(
                f"Cleared SOURCE: {source_result.get('path')} "
                f"[kind={source_result.get('kind')}, removed={source_result.get('removed', 0)}]"
            )
            add_log(
                f"Cleared TARGET: {target_result.get('path')} "
                f"[kind={target_result.get('kind')}, removed={target_result.get('removed', 0)}]"
            )
            mark_workspace_feedback("source", "delete")
            reload_ui(150)
        except Exception as exc:
            add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
            safe_notify(str(exc), "negative")
        finally:
            state["running"] = False

    return handler


def workspace_pick_click_handler(role: str):
    async def handler() -> None:
        if state["running"]:
            safe_notify(tr("another_running"), "warning")
            return
        role_key = canonical_role(role)
        try:
            selected = await run.io_bound(
                pick_folder,
                WORKBENCH_ADAPTER.translate("target_folder") if role_key == "target" else WORKBENCH_ADAPTER.translate("source_folder"),
                True,
            )
        except Exception as exc:
            add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
            safe_notify(str(exc), "negative")
            return
        if not selected:
            add_log(tr("picker_cancelled"))
            return
        path_value = str(selected[0])
        save_workspace_path(role_key, path_value)
        await run.io_bound(WORKBENCH_ADAPTER.remember_path, role_key, path_value)
        mark_workspace_feedback(role_key, "path")
        add_log(f"{'TARGET' if role_key == 'target' else 'SOURCE'} -> {path_value}")
        safe_notify(
            WORKBENCH_ADAPTER.translate("target_selected" if role_key == "target" else "source_selected"),
            "positive",
        )
        reload_ui(150)

    return handler


WORKBENCH_RENDERER = WorkbenchRenderer(
    adapter=WORKBENCH_ADAPTER,
    handlers=WorkbenchHandlers(
        delete_path=workspace_delete_path_click_handler,
        pin_path=workspace_pin_click_handler,
        select_path=workspace_path_select_handler,
        pick_path=workspace_pick_click_handler,
        open_path=workspace_open_click_handler,
        add_file=workspace_single_file_click_handler,
        reset_paths=reset_workspace_paths_click_handler,
        delete_io=workspace_delete_both_click_handler,
        list_files=show_input_file_list,
    ),
    display_path_callback=display_path,
)

def operation_button(operation: Operation) -> None:
    with ui.element("div").classes("audion-operation-row"):
        button = ui.button(
            operation.display_title(settings.language),
            on_click=operation_click_handler(operation),
        ).props("dense flat no-wrap").classes("audion-action audion-operation-button rounded-lg")
        attach_tooltip(button, operation_tooltip(operation))
        ui.label(operation.display_description(settings.language)).classes("audion-operation-description")


def operation_click_handler(operation: Operation):
    async def handler() -> None:
        await start_operation(operation)

    return handler






def operation_to_command_node(operation: Operation) -> CommandNode:
    return CommandNode(
        id=operation.id,
        title=operation.title,
        description=operation.description,
        service=operation.service,
        kind=operation.kind,
        title_ru=operation.title_ru,
        description_ru=operation.description_ru,
        tooltip=operation.tooltip,
        tooltip_ru=operation.tooltip_ru,
        parameters=dict(operation.parameters),
        fields=operation.fields,
    )


LOCAL_OCR_ENGINE_IDS = ("tesseract", "surya")
API_OCR_ENGINE_IDS = ("yandex", "mistral", "xai", "gemini", "chatgpt")
PROJECT_TOOLS_INSTALL_NODE_IDS = (
    "install_tesseract",
    "install_realesrgan",
    "surya_acceleration",
)
INSTALL_RECOMMENDATION_NODE_IDS = {
    "install_tesseract",
    "install_realesrgan",
    "surya_acceleration",
    "install_llamacpp_vulkan",
    "install_llamacpp_cuda124",
    "install_llamacpp_cuda133",
    "install_surya_cpu",
    "install_surya_pytorch_cuda40",
    "install_surya_pytorch_cuda50",
}
PROJECT_TOOLS_CHECK_NODE_IDS = (
    "project_status",
    "env_doctor",
    "ocr_brick_status",
    "check_models_openai",
    "check_models_gemini",
    "check_models_yandex",
    "check_models_xai",
    "yandex_ocr_smoke",
    "xai_ocr_smoke",
)


def _find_command_node(nodes: list[CommandNode] | tuple[CommandNode, ...], node_id: str) -> CommandNode | None:
    for node in nodes:
        if node.id == node_id:
            return node
        found = _find_command_node(node.children, node_id)
        if found is not None:
            return found
    return None


def _filter_engine_field(field: dict[str, Any], allowed: tuple[str, ...], default: str) -> dict[str, Any]:
    cloned = dict(field)
    if str(cloned.get("id") or "") != "ocr_engine":
        return cloned
    allowed_set = set(allowed)
    options = []
    for option in cloned.get("options", []):
        if not isinstance(option, dict):
            continue
        if str(option.get("value") or "") in allowed_set:
            options.append(dict(option))
    cloned["options"] = options
    cloned["default"] = default
    cloned["choice_columns"] = max(2, min(8, len(options) or len(allowed)))
    return cloned


def _condition_values_for_key(condition: Any, key: str) -> list[Any]:
    if isinstance(condition, dict):
        if key in condition:
            return [condition.get(key)]
        values: list[Any] = []
        for item in condition.values():
            if isinstance(item, (dict, list, tuple)):
                values.extend(_condition_values_for_key(item, key))
        return values
    if isinstance(condition, (list, tuple)):
        values: list[Any] = []
        for item in condition:
            values.extend(_condition_values_for_key(item, key))
        return values
    return []


def _flatten_condition_values(value: Any) -> list[str]:
    if isinstance(value, dict):
        if "in" in value:
            return _flatten_condition_values(value.get("in"))
        if "equals" in value:
            return _flatten_condition_values(value.get("equals"))
        if "not" in value or "empty" in value:
            return []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(_flatten_condition_values(item))
        return out
    if value is None:
        return []
    return [str(value).strip()]


def _field_allowed_for_ocr_family(field: dict[str, Any], allowed: tuple[str, ...]) -> bool:
    show_if = field.get("show_if", field.get("visible_if", field.get("when")))
    expected = []
    for value in _condition_values_for_key(show_if, "ocr_engine"):
        expected.extend(_flatten_condition_values(value))
    if not expected:
        return True
    allowed_set = {str(item) for item in allowed}
    return any(item in allowed_set for item in expected)


def _ocr_fields_for_family(base_fields: tuple[dict[str, Any], ...], allowed: tuple[str, ...], default: str) -> tuple[dict[str, Any], ...]:
    return tuple(
        _filter_engine_field(field, allowed, default)
        for field in base_fields
        if _field_allowed_for_ocr_family(field, allowed)
    )


def _make_ocr_root_node(
    base: CommandNode,
    *,
    node_id: str,
    title: str,
    title_ru: str,
    description: str,
    description_ru: str,
    engines: tuple[str, ...],
    default_engine: str,
) -> CommandNode:
    fields = _ocr_fields_for_family(base.fields, engines, default_engine)
    parameters = dict(base.parameters)
    parameters["ocr_engine"] = default_engine
    run_node = CommandNode(
        id=f"{node_id}_run",
        title="Run OCR",
        title_ru="Запустить OCR",
        description=description,
        description_ru=description_ru,
        service=base.service,
        kind=base.kind,
        parameters=parameters,
        fields=fields,
    )
    return CommandNode(
        id=node_id,
        title=title,
        title_ru=title_ru,
        description=description,
        description_ru=description_ru,
        service="",
        kind=base.kind,
        parameters=parameters,
        fields=fields,
        children=(run_node,),
    )


def _root_ocr_nodes(base: CommandNode) -> list[CommandNode]:
    return [
        _make_ocr_root_node(
            base,
            node_id="ocr_local",
            title="Local OCR",
            title_ru="Локальный OCR",
            description="Free/local OCR with preprocessing, Tesseract and Surya modes.",
            description_ru="Бесплатный локальный OCR с препроцессингом: Tesseract и Surya.",
            engines=LOCAL_OCR_ENGINE_IDS,
            default_engine="tesseract",
        ),
        _make_ocr_root_node(
            base,
            node_id="ocr_api",
            title="Paid API OCR",
            title_ru="Платный API OCR",
            description="Paid OCR/vision models through Yandex, Mistral, xAI, Gemini, and ChatGPT.",
            description_ru="Платные OCR/vision-модели через Yandex, Mistral, xAI, Gemini и ChatGPT.",
            engines=API_OCR_ENGINE_IDS,
            default_engine="yandex",
        ),
    ]


def _project_tools_without_root_promotions(node: CommandNode, legacy_build: CommandNode | None = None) -> CommandNode:
    children = tuple(child for child in node.children if child.id not in {"coordinate_tables", "ocr_quality_benchmark", "numeric_check_pass"})
    if not any(child.id == "install_tesseract" for child in children):
        children = (operation_to_command_node(TESSERACT_INSTALL_OPERATION), *children)
    if legacy_build is not None:
        legacy_build = replace(
            legacy_build,
            title="Rebuild legacy Markdown",
            title_ru="Пересборка старого Markdown",
            description="Expert compatibility tools for rebuilding existing Markdown into office formats.",
            description_ru="Экспертные compatibility-инструменты для пересборки существующего Markdown в офисные форматы.",
        )
        children = (*children, legacy_build)
    return replace(
        node,
        children=children,
    )


def _table_workflow_with_coordinate_tables(node: CommandNode, coordinate_tables: CommandNode | None) -> CommandNode:
    if coordinate_tables is None or any(child.id == coordinate_tables.id for child in node.children):
        return node
    return replace(
        node,
        children=(coordinate_tables, *node.children),
    )


def _root_command_groups() -> list[CommandNode]:
    groups = list(manifest.operation_groups)
    benchmark = _find_command_node(groups, "ocr_quality_benchmark")
    numeric_check = _find_command_node(groups, "numeric_check_pass")
    coordinate_tables = _find_command_node(groups, "coordinate_tables")
    legacy_build = next((node for node in groups if node.id == "build"), None)
    roots: list[CommandNode] = []
    benchmark_added = False
    numeric_check_added = False
    coordinate_tables_added = False
    for node in groups:
        if node.id == "extract":
            for child in node.children:
                if child.id == "extract_local":
                    roots.append(child)
                elif child.id == "ocr_brick":
                    roots.extend(_root_ocr_nodes(child))
            if benchmark is not None:
                roots.append(benchmark)
                benchmark_added = True
            if numeric_check is not None:
                roots.append(numeric_check)
                numeric_check_added = True
            continue
        if node.id == "table_workflow":
            roots.append(_table_workflow_with_coordinate_tables(node, coordinate_tables))
            coordinate_tables_added = coordinate_tables is not None
            continue
        if node.id == "project_tools":
            roots.append(_project_tools_without_root_promotions(node, legacy_build))
            continue
        if node.id == "build":
            continue
        if node.id == "hybrid_workbench":
            continue
        roots.append(node)
    if benchmark is not None and not benchmark_added:
        roots.append(benchmark)
    if numeric_check is not None and not numeric_check_added:
        roots.append(numeric_check)
    if coordinate_tables is not None and not coordinate_tables_added:
        roots.append(coordinate_tables)
    return roots


def root_command_nodes() -> list[CommandNode]:
    if manifest.operation_groups:
        return _root_command_groups()
    return [operation_to_command_node(operation) for operation in manifest.operations]


def command_level_for_path(command_path: list[str]) -> tuple[list[CommandNode], list[CommandNode]]:
    trail: list[CommandNode] = []
    nodes = root_command_nodes()
    for node_id in command_path:
        node = next((candidate for candidate in nodes if candidate.id == node_id), None)
        if node is None:
            return [], root_command_nodes()
        trail.append(node)
        nodes = list(node.children)
    return trail, nodes


def compact_single_child_command_path(command_path: list[str]) -> list[str]:
    compact_path = list(command_path)
    while True:
        trail, nodes = command_level_for_path(compact_path)
        if trail or len(nodes) != 1 or not nodes[0].children:
            return compact_path
        compact_path.append(nodes[0].id)


def current_command_level() -> tuple[list[CommandNode], list[CommandNode]]:
    command_path = compact_single_child_command_path(list(state.get("command_path", [])))
    state["command_path"] = command_path
    trail, nodes = command_level_for_path(command_path)
    if not trail and command_path:
        state["command_path"] = []
        state["pending_command"] = None
        return [], root_command_nodes()
    return trail, nodes


def enter_command_path(command_path: list[str]) -> None:
    state["pending_command"] = None
    state["command_path"] = compact_single_child_command_path(command_path)
    command_tree.refresh()


def enter_command_node(node: CommandNode) -> None:
    enter_command_path([*state.get("command_path", []), node.id])


def select_command_node(node: CommandNode) -> None:
    state["pending_command"] = node
    command_tree.refresh()


async def activate_command_node(node: CommandNode, path_prefix: list[str] | None = None) -> None:
    prefix = list(path_prefix if path_prefix is not None else state.get("command_path", []))
    if node.children:
        if len(node.children) == 1:
            await activate_command_node(node.children[0], [*prefix, node.id])
            return
        enter_command_path([*prefix, node.id])
        return
    if command_visible_fields(node.fields):
        select_command_node(node)
        return
    state["pending_command"] = None
    await start_operation(operation_from_pending_command(node))


def command_click_handler(node: CommandNode):
    async def handler() -> None:
        await activate_command_node(node)

    return handler


def go_back_command() -> None:
    if state.get("pending_command") is not None:
        state["pending_command"] = None
    else:
        path = list(state.get("command_path", []))
        if path:
            path.pop()
        state["command_path"] = compact_single_child_command_path(path)
    command_tree.refresh()


def field_id(field: dict[str, Any]) -> str:
    return str(field.get("id") or field.get("name") or "").strip()


def field_label(field: dict[str, Any]) -> str:
    language = settings.language
    if language == "ru" and field.get("label_ru"):
        return str(field["label_ru"])
    return str(field.get("label") or field.get("title") or field_id(field))


def field_hint(field: dict[str, Any]) -> str:
    language = settings.language
    if language == "ru" and field.get("hint_ru"):
        return str(field["hint_ru"])
    return str(field.get("hint") or "")


def generated_field_tooltip(field: dict[str, Any]) -> str:
    key = field_id(field)
    label = field_label(field)
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    language = settings.language

    if language == "ru":
        specific = {
            "dev_pdf_source_mode": "Выберите, откуда брать Markdown для сборки PDF: текущий Источник Workbench, управляемые input/output, документацию проекта или только файлы с готовыми/устаревшими PDF.",
            "dev_pdf_output_mode": "Выберите схему размещения PDF до запуска. По умолчанию документация пересобирается в соответствующие docs/PDF; режим «Зеркало в Назначение» пишет отдельное дерево в текущее Назначение Workbench.",
            "dev_pdf_source_path": "Необязательный путь для ручного поиска Markdown. Можно указать абсолютный путь или путь относительно корня проекта; пустое поле означает корень проекта.",
            "dev_pdf_custom_filters": "Дополнительный фильтр имён Markdown через запятую. Подходит, если нужно собрать PDF только для API, INSTALL, ROADMAP или похожих файлов.",
            "dev_pdf_exclude_dirs": "Папки, которые сканер пропустит при поиске Markdown. Это защищает runtime, output, logs, node_modules и другие тяжёлые служебные каталоги.",
            "dev_pdf_selected_docs": "Список Markdown, найденных по текущим фильтрам. Если ничего не отмечено, запуск обработает все найденные файлы.",
            "dev_pdf_margin_left_mm": "Левое поле страницы PDF в миллиметрах. Меняйте только если тексту тесно или нужен другой офисный шаблон.",
            "dev_pdf_margin_right_mm": "Правое поле страницы PDF в миллиметрах. Обычно держится симметрично левому полю.",
            "dev_pdf_margin_top_mm": "Верхнее поле страницы PDF в миллиметрах. Увеличьте, если заголовки слишком близко к краю.",
            "dev_pdf_margin_bottom_mm": "Нижнее поле страницы PDF в миллиметрах. Увеличьте, если нужен больший запас под футер или визуальный воздух.",
            "dev_pdf_page_margin_y_mm": "Дополнительный вертикальный воздух внутри страницы, поверх верхнего и нижнего полей.",
            "dev_pdf_line_height": "Межстрочный интервал PDF. Больше значение делает документ читабельнее, но увеличивает число страниц.",
        }
        if key in specific:
            return specific[key]
        if key.endswith("_api_key") or "api_key" in key:
            return f"Выберите файл API-ключа для поля «{label}». Ключ берётся из config и нужен только для платных или облачных запусков."
        if key.endswith("_model") or key in {"model", "openai_model", "gemini_model"}:
            return f"Выберите модель для поля «{label}». В списке должны оставаться только модели, пригодные для OCR/vision-сценария этого окна."
        if dynamic_option_source(field):
            return f"Поле «{label}» загружает список динамически. Если список устарел или пустой, используйте кнопку обновления рядом с полем."
        if kind in {"select", "choice", "format"}:
            return f"Выберите один вариант в поле «{label}». Это значение будет передано в запуск как параметр текущей операции."
        if kind in {"radio", "radiobuttons", "radio-buttons"}:
            return f"Выберите один режим «{label}». Активная кнопка определяет поведение следующего запуска."
        if kind in {"number", "int", "integer", "float"}:
            return f"Числовой параметр «{label}». Используйте стрелки или введите значение вручную; оно применится при следующем запуске."
        if kind in {"checkbox", "bool", "boolean", "toggle"}:
            return f"Переключатель «{label}». Включает или выключает соответствующую опцию текущей операции."
        if is_checkbox_group(field):
            return f"Набор опций «{label}». Отмеченные пункты ограничивают или уточняют работу текущей операции."
        if any(part in key for part in ("path", "file", "folder")):
            return f"Поле пути «{label}». Можно указать абсолютный путь или путь относительно корня проекта, если операция это поддерживает."
        if kind in {"textarea", "multiline"}:
            return f"Многострочное поле «{label}». Используется как текстовый параметр текущей операции."
        return f"Параметр «{label}» для текущей операции. Значение будет использовано при следующем запуске."

    specific_en = {
        "dev_pdf_source_mode": "Choose where Markdown files come from: current Workbench Source, managed input/output, project docs, or only files with existing/outdated PDFs.",
        "dev_pdf_output_mode": "Choose the PDF output layout before running. By default, documentation is rebuilt into the corresponding docs/PDF folders; Mirror to Target writes a separate tree into the current Workbench Target.",
    }
    if key in specific_en:
        return specific_en[key]
    if key.endswith("_api_key") or "api_key" in key:
        return f"Choose the API key file for {label}. Keys are read from config and are used only for cloud/API runs."
    if key.endswith("_model") or key in {"model", "openai_model", "gemini_model"}:
        return f"Choose the OCR/vision-capable model for {label}."
    if dynamic_option_source(field):
        return f"{label} loads its options dynamically. Refresh the list if it is empty or stale."
    if kind in {"select", "choice", "format", "radio", "radiobuttons", "radio-buttons"}:
        return f"Choose one value for {label}; it will be passed to the next run."
    if kind in {"number", "int", "integer", "float"}:
        return f"Numeric setting for {label}; use the arrows or type a value."
    if kind in {"checkbox", "bool", "boolean", "toggle"}:
        return f"Toggle {label} for the current operation."
    if is_checkbox_group(field):
        return f"Select the {label} options used by the current operation."
    return f"Parameter {label} for the current operation."


def compact_tooltip_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def attach_tooltip(control: Any, text: Any) -> Any:
    tooltip = compact_tooltip_text(text)
    if tooltip:
        control.tooltip(tooltip)
    return control


def dict_tooltip(item: dict[str, Any]) -> str:
    language = settings.language
    if language == "ru":
        for key in ("tooltip_ru", "hint_ru", "description_ru"):
            if item.get(key):
                return compact_tooltip_text(item.get(key))
    for key in ("tooltip", "hint", "description"):
        if item.get(key):
            return compact_tooltip_text(item.get(key))
    return ""


def field_tooltip(field: dict[str, Any]) -> str:
    return dict_tooltip(field) or generated_field_tooltip(field)


def operation_tooltip(operation: Operation) -> str:
    return compact_tooltip_text(operation.display_tooltip(settings.language))


def command_node_tooltip(node: CommandNode) -> str:
    return compact_tooltip_text(node.display_tooltip(settings.language))


def checkbox_action_tooltip(field: dict[str, Any], mode: str, label: str) -> str:
    field_name = field_label(field)
    if settings.language == "ru":
        descriptions = {
            "all": f"Отметить все пункты в наборе «{field_name}». Удобно перед точечным исключением лишнего.",
            "default": f"Вернуть набор «{field_name}» к проектному значению по умолчанию.",
            "none": f"Снять все отметки в наборе «{field_name}». Для некоторых полей пустой выбор означает обработать всё найденное.",
            "clear": f"Очистить текущий выбор в наборе «{field_name}».",
            "missing_pdf": "Оставить отмеченными только Markdown-файлы, для которых ещё не найдена полная пара PDF.",
            "outdated": "Оставить отмеченными только Markdown-файлы, у которых PDF старее исходного Markdown.",
            "changelog": "Оставить отмеченными только найденные CHANGELOG-файлы.",
        }
        return descriptions.get(mode, f"Применить действие «{label}» к набору «{field_name}».")
    descriptions_en = {
        "all": f"Select every option in {field_name}.",
        "default": f"Restore the default selection for {field_name}.",
        "none": f"Clear every selected option in {field_name}.",
        "clear": f"Clear the current selection in {field_name}.",
        "missing_pdf": "Select only Markdown files that do not yet have a complete PDF pair.",
        "outdated": "Select only Markdown files whose generated PDF is older than the source Markdown.",
        "changelog": "Select only found CHANGELOG files.",
    }
    return descriptions_en.get(mode, f"Apply {label} to {field_name}.")


def field_default(field: dict[str, Any]) -> Any:
    if "default" in field:
        return field["default"]
    default_file = str(field.get("default_file") or "").strip()
    if default_file:
        path = Path(default_file)
        if not path.is_absolute():
            path = ROOT / path
        try:
            return path.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            return ""
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    options = field.get("options", [])
    if kind in {"checkboxes", "multi_checkbox", "multicheckbox", "multi-select", "multiselect"}:
        if not isinstance(options, list):
            return []
        selected: list[Any] = []
        for option in options:
            if isinstance(option, dict) and option.get("default", False):
                selected.append(option.get("value", option.get("id", option.get("label"))))
        return selected
    if isinstance(options, list) and options:
        first = options[0]
        if isinstance(first, dict):
            return first.get("value", first.get("id", ""))
        return first
    return ""


def current_field_value(field: dict[str, Any]) -> Any:
    key = field_id(field)
    values = state.setdefault("field_values", {})
    if key not in values:
        values[key] = field_default(field)
    return values[key]


def _raw_option_values(field: dict[str, Any]) -> list[Any]:
    options = field.get("options", [])
    if not isinstance(options, list):
        return []
    values: list[Any] = []
    for option in options:
        if isinstance(option, dict):
            values.append(option.get("value", option.get("id", option.get("label"))))
        else:
            values.append(option)
    return values


def _coerce_field_values_for_fields(values: dict[str, Any], fields: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> None:
    state_values = state.setdefault("field_values", {})
    for field in fields or ():
        key = field_id(field)
        if key not in {"ocr_engine", "dev_pdf_output_mode"}:
            continue
        options = _raw_option_values(field)
        if not options:
            continue
        current = values.get(key, field_default(field))
        if any(str(current).strip().lower() == str(option).strip().lower() for option in options):
            continue
        corrected = field_default(field)
        values[key] = corrected
        state_values[key] = corrected
        return


def _coerce_field_values_for_command(values: dict[str, Any], node: CommandNode | None) -> None:
    if node is None:
        return
    _coerce_field_values_for_fields(values, getattr(node, "fields", ()) or ())


def current_option_values() -> dict[str, Any]:
    pending = state.get("pending_command")
    values: dict[str, Any] = {}
    node_for_coercion: CommandNode | None = None
    if pending is not None:
        node_for_coercion = pending
        values.update(getattr(pending, "parameters", {}) or {})
    else:
        trail, _nodes = current_command_level()
        if trail:
            node_for_coercion = trail[-1]
            values.update(getattr(node_for_coercion, "parameters", {}) or {})
    values.update(dict(state.setdefault("field_values", {})))
    _coerce_field_values_for_command(values, node_for_coercion)
    try:
        values["input_path"] = str(current_source_path())
        values["output_path"] = str(current_target_path())
    except Exception:
        pass
    provider = str(values.get("provider") or "").strip().lower()
    if provider:
        provider_key = values.get(f"{provider}_api_key")
        provider_model = values.get(f"{provider}_model")
        if provider_key is not None:
            values["api_key"] = provider_key
        if provider_model is not None:
            values["model"] = provider_model
    return values


def set_field_value(key: str, value: Any) -> None:
    values = state.setdefault("field_values", {})
    previous = values.get(key)
    values[key] = value
    if previous == value:
        return
    if key == "provider":
        values.pop("api_key", None)
        values.pop("model", None)
        for cache_key in list(dynamic_option_cache):
            dynamic_option_cache.pop(cache_key, None)
        command_tree.refresh()
    elif key == "api_key":
        values.pop("model", None)
        for cache_key in list(dynamic_option_cache):
            if "model_options" in cache_key:
                dynamic_option_cache.pop(cache_key, None)
        command_tree.refresh()
    elif key.endswith("_api_key"):
        provider = key[: -len("_api_key")]
        values.pop(f"{provider}_model", None)
        for cache_key in list(dynamic_option_cache):
            if "model_options" in cache_key:
                dynamic_option_cache.pop(cache_key, None)
        command_tree.refresh()


def adjusted_number_value(field: dict[str, Any], current: Any, direction: int) -> int | float:
    step_raw = field.get("step", 1)
    try:
        step = float(step_raw)
    except (TypeError, ValueError):
        step = 1.0

    seed = current
    if seed is None or seed == "":
        seed = field_default(field) or 0
    try:
        value = float(seed)
    except (TypeError, ValueError):
        value = 0.0

    value += step * (1 if direction > 0 else -1)
    for bound_key, clamp in (("min", max), ("max", min)):
        bound = field.get(bound_key)
        if bound is None or bound == "":
            continue
        try:
            value = clamp(value, float(bound))
        except (TypeError, ValueError):
            continue

    kind = str(field.get("type", field.get("kind", "number"))).lower()
    integer_like = kind in {"number", "int", "integer"} and float(step).is_integer()
    return int(round(value)) if integer_like else round(value, 6)


def spin_number_field(key: str, field: dict[str, Any], control: Any, direction: int) -> None:
    value = adjusted_number_value(field, state.setdefault("field_values", {}).get(key), direction)
    set_field_value(key, value)
    control.set_value(value)


def dynamic_option_source(field: dict[str, Any]) -> str:
    return str(field.get("options_source") or field.get("source") or "").strip()


def dynamic_cache_key(field: dict[str, Any]) -> str:
    source = dynamic_option_source(field)
    values = current_option_values()
    cache_fields = field.get("cache_fields", [])
    if isinstance(cache_fields, list) and cache_fields:
        relevant = {str(name): values.get(str(name)) for name in cache_fields}
        return source + "|" + json.dumps(relevant, ensure_ascii=False, sort_keys=True)
    provider = str(values.get("provider") or "").strip().lower()
    relevant = {
        "provider": values.get("provider"),
        "api_key": values.get("api_key") or values.get(f"{provider}_api_key"),
    }
    return source + "|" + json.dumps(relevant, ensure_ascii=False, sort_keys=True)


def refresh_dynamic_options(field: dict[str, Any]) -> None:
    source = dynamic_option_source(field)
    if source:
        for cache_key in list(dynamic_option_cache):
            if cache_key == source or cache_key.startswith(source + "|"):
                dynamic_option_cache.pop(cache_key, None)
    key = field_id(field)
    if key:
        state.setdefault("field_values", {}).pop(key, None)
    command_tree.refresh()


def refresh_options_click_handler(field: dict[str, Any]):
    def handler() -> None:
        refresh_dynamic_options(field)

    return handler


API_KEY_PROVIDERS = {"openai", "gemini", "yandex", "xai"}


def api_key_provider_for_field(field: dict[str, Any]) -> str:
    key = field_id(field)
    if key == "api_key":
        provider = str(current_option_values().get("provider") or "").strip().lower()
        return provider if provider in API_KEY_PROVIDERS else ""
    if key.endswith("_api_key"):
        provider = key[: -len("_api_key")]
        return provider if provider in API_KEY_PROVIDERS else ""

    source = dynamic_option_source(field).lower()
    for provider in API_KEY_PROVIDERS:
        if f"{provider}_api_key_options" in source:
            return provider
    return ""


def provider_default_key_filename(provider: str) -> str:
    if provider == "yandex":
        return "api_key_yandex_studio.txt"
    return f"api_key_{provider}.txt"


def sanitized_api_key_filename(provider: str, raw_name: str) -> str:
    raw = str(raw_name or "").strip().strip("\"'")
    if not raw:
        return provider_default_key_filename(provider)
    name = Path(raw).name.strip()
    name = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", "_", name).strip(" .")
    if not name:
        return provider_default_key_filename(provider)
    path = Path(name)
    stem = path.stem.strip(" ._") or provider
    suffix = path.suffix if path.suffix else ".txt"
    if suffix.lower() != ".txt":
        suffix = ".txt"
    lowered_stem = stem.lower()
    if provider not in lowered_stem:
        stem = f"api_key_{provider}_{stem}"
    return f"{stem}{suffix}"


def unique_api_key_path(provider: str, raw_name: str) -> Path:
    filename = sanitized_api_key_filename(provider, raw_name)
    target = (paths.config / filename).resolve()
    try:
        target.relative_to(paths.config.resolve())
    except ValueError:
        target = (paths.config / provider_default_key_filename(provider)).resolve()
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix or ".txt"
    for index in range(2, 1000):
        candidate = target.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return target.with_name(f"{stem}_{timestamp}{suffix}")


def project_relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def clear_api_key_ui_state(provider: str, field_key: str) -> None:
    values = state.setdefault("field_values", {})
    values.pop("model", None)
    values.pop(f"{provider}_model", None)
    if field_key == "api_key":
        values.pop("api_key", None)
    elif field_key.endswith("_api_key"):
        values.pop(field_key, None)
    dynamic_option_cache.clear()


def resolve_api_key_file(provider: str, selector: str) -> Path:
    from system_core.services import office_service

    return office_service._resolve_key_file(ROOT, provider, selector)  # type: ignore[attr-defined]


def archived_api_key_path(provider: str, source: Path) -> Path:
    archive_dir = paths.config / "deleted_keys" / provider
    archive_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", "_", source.name).strip(" .") or f"api_key_{provider}.txt"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = archive_dir / f"{timestamp}_{safe_name}.deleted"
    index = 2
    while candidate.exists():
        candidate = archive_dir / f"{timestamp}_{index}_{safe_name}.deleted"
        index += 1
    return candidate


def can_archive_api_key_path(path: Path) -> bool:
    resolved = path.resolve()
    allowed_roots = [paths.config.resolve(), ROOT.resolve()]
    for allowed_root in allowed_roots:
        try:
            resolved.relative_to(allowed_root)
            return True
        except ValueError:
            continue
    return False


async def show_add_api_key_dialog(field: dict[str, Any]) -> None:
    provider = api_key_provider_for_field(field)
    if not provider:
        safe_notify("Не удалось определить провайдера ключа." if settings.language == "ru" else "Could not detect the key provider.", "warning")
        return

    default_name = provider_default_key_filename(provider)
    with ui.dialog() as dialog, ui.card().classes("audion-dialog audion-key-dialog rounded-lg"):
        title = f"Добавить ключ {provider}" if settings.language == "ru" else f"Add {provider} key"
        ui.label(title).classes("text-base font-semibold")
        ui.label(
            "Ключ будет сохранён обычным .txt-файлом в папке config. В журнал он не выводится."
            if settings.language == "ru"
            else "The key will be saved as a plain .txt file in config. It will not be printed to the log."
        ).classes("text-sm text-gray-400")
        name_input = ui.input(
            "Имя файла" if settings.language == "ru" else "File name",
            value=default_name,
        ).props("dense outlined").classes("audion-control w-full")
        attach_tooltip(
            name_input,
            "Введите короткое имя файла. Если в имени нет названия провайдера, интерфейс добавит безопасный префикс сам."
            if settings.language == "ru"
            else "Enter a short file name. If the provider name is missing, the UI will add a safe prefix.",
        )
        key_input = ui.input(
            "API key" if settings.language != "ru" else "API-ключ",
            password=True,
            password_toggle_button=True,
        ).props("dense outlined").classes("audion-control w-full")
        attach_tooltip(
            key_input,
            "Вставьте секретный ключ целиком. Он будет записан в файл, но не будет показан в журнале операции."
            if settings.language == "ru"
            else "Paste the full secret key. It will be written to a file, but not shown in the operation log.",
        )
        with ui.row().classes("w-full items-center justify-end gap-2"):
            ui.button(tr("cancel"), on_click=dialog.close).props("dense flat").classes("audion-action rounded-lg")
            save_button = ui.button(
                "Сохранить ключ" if settings.language == "ru" else "Save key",
                on_click=lambda: dialog.submit(True),
            ).props("dense flat no-wrap").classes("audion-action rounded-lg")
            attach_tooltip(save_button, "Создать файл ключа и выбрать его в текущем поле." if settings.language == "ru" else "Create the key file and select it in the current field.")

    confirmed = await dialog
    if not confirmed:
        return

    secret = str(key_input.value or "").strip()
    if not secret:
        safe_notify("Ключ пустой, файл не создан." if settings.language == "ru" else "The key is empty; no file was created.", "warning")
        return

    try:
        key_path = unique_api_key_path(provider, str(name_input.value or default_name))
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(secret + "\n", encoding="utf-8", newline="\n")
        dynamic_option_cache.clear()
        field_key = field_id(field)
        if field_key:
            set_field_value(field_key, project_relative_path(key_path))
        command_tree.refresh()
        safe_notify(
            f"Ключ {provider} сохранён: {project_relative_path(key_path)}"
            if settings.language == "ru"
            else f"{provider} key saved: {project_relative_path(key_path)}",
            "positive",
        )
    except Exception as exc:
        safe_notify(str(exc), "negative")


async def show_delete_api_key_dialog(field: dict[str, Any]) -> None:
    provider = api_key_provider_for_field(field)
    field_key = field_id(field)
    if not provider or not field_key:
        safe_notify("Не удалось определить провайдера ключа." if settings.language == "ru" else "Could not detect the key provider.", "warning")
        return

    selector = str(current_field_value(field) or "")
    try:
        key_path = resolve_api_key_file(provider, selector)
    except Exception as exc:
        safe_notify(str(exc), "negative")
        return
    if not key_path.exists():
        safe_notify("Файл ключа не найден." if settings.language == "ru" else "The key file was not found.", "warning")
        return
    if not can_archive_api_key_path(key_path):
        safe_notify(
            "Этот ключ находится вне проекта, поэтому интерфейс не будет его перемещать."
            if settings.language == "ru"
            else "This key is outside the project, so the UI will not move it.",
            "warning",
        )
        return

    archive_path = archived_api_key_path(provider, key_path)
    with ui.dialog() as dialog, ui.card().classes("audion-dialog audion-key-dialog rounded-lg"):
        title = f"Удалить ключ {provider}?" if settings.language == "ru" else f"Remove {provider} key?"
        ui.label(title).classes("text-base font-semibold")
        ui.label(project_relative_path(key_path)).classes("text-sm font-semibold")
        ui.label(
            "Файл не будет стёрт безвозвратно: он будет перенесён в config/deleted_keys. Запуски, которые используют этот ключ, перестанут работать, пока не выбран другой ключ."
            if settings.language == "ru"
            else "The file will not be erased permanently: it will be moved to config/deleted_keys. Runs using this key will stop working until another key is selected.",
        ).classes("text-sm text-gray-400")
        with ui.row().classes("w-full items-center justify-end gap-2"):
            ui.button(tr("cancel"), on_click=dialog.close).props("dense flat").classes("audion-action rounded-lg")
            delete_button = ui.button(
                "Перенести в архив" if settings.language == "ru" else "Move to archive",
                on_click=lambda: dialog.submit(True),
            ).props("dense flat no-wrap color=negative").classes("audion-action rounded-lg")
            attach_tooltip(delete_button, "Мягко убрать файл ключа из активной конфигурации." if settings.language == "ru" else "Safely remove the key file from active configuration.")

    confirmed = await dialog
    if not confirmed:
        return

    try:
        shutil.move(str(key_path), str(archive_path))
        clear_api_key_ui_state(provider, field_key)
        command_tree.refresh()
        safe_notify(
            f"Ключ перенесён в архив: {project_relative_path(archive_path)}"
            if settings.language == "ru"
            else f"Key moved to archive: {project_relative_path(archive_path)}",
            "positive",
        )
    except Exception as exc:
        safe_notify(str(exc), "negative")


def api_key_add_click_handler(field: dict[str, Any]):
    async def handler() -> None:
        await show_add_api_key_dialog(field)

    return handler


def api_key_delete_click_handler(field: dict[str, Any]):
    async def handler() -> None:
        await show_delete_api_key_dialog(field)

    return handler


def apply_preset(preset: dict[str, Any]) -> None:
    values = preset.get("values", {})
    if not isinstance(values, dict):
        return
    field_values = state.setdefault("field_values", {})
    for key, value in values.items():
        field_values[str(key)] = value
    command_tree.refresh()


def preset_label(preset: dict[str, Any]) -> str:
    if settings.language == "ru" and preset.get("label_ru"):
        return str(preset["label_ru"])
    return str(preset.get("label") or preset.get("title") or preset.get("id") or "Preset")


def preset_click_handler(preset: dict[str, Any]):
    def handler() -> None:
        apply_preset(preset)

    return handler


def load_dynamic_options(field: dict[str, Any]) -> list[Any]:
    source = dynamic_option_source(field)
    if not source:
        return []

    cache_seconds = float(field.get("cache_seconds", 45) or 0)
    now = time.monotonic()
    cache_key = dynamic_cache_key(field)
    cached = dynamic_option_cache.get(cache_key)
    if cached and cache_seconds > 0 and now - cached[0] < cache_seconds:
        return cached[1]

    try:
        if ":" not in source:
            raise RuntimeError(f"Dynamic option source must use module:function syntax: {source}")
        module_name, function_name = source.split(":", 1)
        module = importlib.import_module(module_name)
        provider = getattr(module, function_name)
        try:
            options = provider(ROOT, current_option_values())
        except TypeError:
            try:
                options = provider(ROOT)
            except TypeError:
                options = provider()
        if not isinstance(options, list):
            raise RuntimeError(f"Dynamic option source returned {type(options).__name__}, expected list.")
    except Exception as exc:
        message = f"Option source failed: {exc.__class__.__name__}: {exc}"
        options = [{"value": "", "label": message, "label_ru": message}]

    dynamic_option_cache[cache_key] = (now, options)
    return options


def field_options(field: dict[str, Any]) -> list[Any]:
    dynamic_options = load_dynamic_options(field)
    if dynamic_options:
        return dynamic_options
    options = field.get("options", [])
    return options if isinstance(options, list) else []


def select_options(field: dict[str, Any]) -> dict[Any, str] | list[Any]:
    options = field_options(field)
    if all(isinstance(option, dict) for option in options):
        result: dict[Any, str] = {}
        for option in options:
            value = option.get("value", option.get("id", ""))
            if settings.language == "ru" and option.get("label_ru"):
                label = str(option["label_ru"])
            else:
                label = str(option.get("label") or option.get("title") or value)
            result[value] = label
        return result
    return options


def option_value(option: Any) -> Any:
    if isinstance(option, dict):
        return option.get("value", option.get("id", option.get("label", "")))
    return option


def option_label(option: Any) -> str:
    if not isinstance(option, dict):
        return str(option)
    language = settings.language
    if language == "ru" and option.get("label_ru"):
        return str(option["label_ru"])
    return str(option.get("label") or option.get("title") or option_value(option))


def option_tooltip(option: Any) -> str:
    if not isinstance(option, dict):
        return ""
    return dict_tooltip(option)


def option_tone(option: Any) -> str:
    if not isinstance(option, dict):
        return ""
    raw = str(option.get("tone") or option.get("category") or option.get("group") or "").strip().lower()
    return "".join(char if char.isalnum() else "-" for char in raw).strip("-")


def choice_option_items(field: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for option in field_options(field):
        value = option_value(option)
        items.append(
            {
                "value": value,
                "label": option_label(option),
                "tooltip": option_tooltip(option),
                "tone": option_tone(option),
            }
        )
    return items


def field_choice_layout(field: dict[str, Any]) -> str:
    layout = str(field.get("layout") or field.get("choices_layout") or field.get("option_layout") or "").strip().lower()
    if layout in {"vertical", "column", "stack", "stacked"}:
        return "vertical"
    return "horizontal"


def field_choice_columns(field: dict[str, Any]) -> int:
    aliases = {
        "two_columns": 2,
        "three_columns": 3,
        "four_columns": 4,
        "five_columns": 5,
        "six_columns": 6,
        "seven_columns": 7,
        "eight_columns": 8,
    }
    layout = str(field.get("layout") or field.get("choices_layout") or field.get("option_layout") or "").strip().lower()
    raw = field.get("columns", field.get("choice_columns", aliases.get(layout, 0)))
    try:
        columns = int(raw or 0)
    except (TypeError, ValueError):
        return 0
    return columns if 2 <= columns <= 8 else 0


def field_choice_style(field: dict[str, Any]) -> str:
    return str(field.get("style") or field.get("choice_style") or field.get("variant") or "").strip().lower()


def css_token(value: Any) -> str:
    text = str(value or "").strip().lower()
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in text)
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned or "none"


def field_choice_row_classes(field: dict[str, Any]) -> str:
    if field_choice_layout(field) == "vertical":
        return "audion-choice-row audion-choice-column"
    columns = field_choice_columns(field)
    suffix = f" audion-choice-cols-{columns}" if columns else ""
    if bool(field.get("choice_compact", False)):
        suffix += " audion-choice-compact"
    return f"audion-choice-row{suffix}"


def set_segmented_choice_value(key: str, value: Any) -> None:
    set_field_value(key, value)
    command_tree.refresh()


def render_segmented_choice(field: dict[str, Any], option_items: list[dict[str, Any]], value: Any) -> None:
    key = field_id(field)
    row_classes = f"{field_choice_row_classes(field)} audion-segmented-choice"
    if str(field.get("choice_align") or field.get("align") or "").strip().lower() in {"center", "centered"}:
        row_classes += " audion-segmented-choice-centered"
    with ui.element("div").classes(row_classes):
        for item in option_items:
            classes = "audion-action audion-segmented-button rounded-md"
            if item["tone"]:
                classes += f" audion-segmented-tone-{item['tone']}"
            if item["value"] == value:
                classes += " audion-segmented-button-active"
            button = ui.button(
                item["label"],
                on_click=lambda item_value=item["value"]: set_segmented_choice_value(key, item_value),
            ).props("dense flat no-wrap").classes(classes)
            tooltip = item.get("tooltip") or field_tooltip(field)
            if tooltip:
                button.tooltip(tooltip)


def checkbox_options(field: dict[str, Any]) -> list[tuple[Any, str]]:
    return [(item["value"], item["label"]) for item in checkbox_option_items(field)]


def checkbox_option_items(field: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for option in field_options(field):
        if isinstance(option, dict):
            item = dict(option)
            item["value"] = option_value(option)
            item["label"] = option_label(option)
            item["tooltip"] = option_tooltip(option)
            items.append(item)
        else:
            items.append({"value": option, "label": str(option)})
    return items


def is_checkbox_group(field: dict[str, Any]) -> bool:
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    return kind in {"checkboxes", "multi_checkbox", "multicheckbox", "multi-select", "multiselect"}


def field_container_classes(field: dict[str, Any]) -> str:
    span = str(field.get("span") or field.get("width") or "").lower()
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    extra_classes = [
        f"audion-field-id-{css_token(field_id(field))}",
        f"audion-field-group-{css_token(field_section_id(field))}",
    ]
    if kind in {"radio", "radiobuttons", "radio-buttons"}:
        extra_classes.append("audion-radio-field")

    def classes(base: str) -> str:
        return " ".join([base, *extra_classes])

    if span in {"full", "wide", "100%", "1/-1"}:
        return classes("audion-field audion-field-wide")
    if span in {"compact", "small", "narrow", "quarter", "1"}:
        return classes("audion-field audion-field-compact")
    if span in {"compact-start", "small-start", "narrow-start", "row-start"}:
        return classes("audion-field audion-field-compact audion-field-row-start")
    if span in {"normal", "half", "double", "2"}:
        return classes("audion-field")
    if kind in {"select", "choice", "format"}:
        return classes("audion-field audion-field-select")
    if kind in {"textarea", "multiline", "path", "file", "folder"}:
        return classes("audion-field audion-field-wide")
    if kind in {"preset_buttons", "presets", "profile_buttons", "profiles"}:
        return classes("audion-field audion-field-wide")
    if kind in {"checkboxes", "multi_checkbox", "multicheckbox", "multi-select", "multiselect"}:
        return classes("audion-field audion-field-wide")
    return classes("audion-field")


def render_field(field: dict[str, Any]) -> None:
    key = field_id(field)
    if not key:
        return
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    label = field_label(field)
    value = current_field_value(field)
    hint = field_hint(field)
    tooltip = field_tooltip(field) or hint

    def render_field_label() -> None:
        if bool(field.get("hide_label", False)):
            return
        label_control = ui.label(label).classes("audion-field-label")
        attach_tooltip(label_control, tooltip)

    with ui.element("div").classes(field_container_classes(field)):
        if kind in {"preset_buttons", "presets", "profile_buttons", "profiles"}:
            presets = field.get("presets", field.get("options", []))
            if not isinstance(presets, list):
                presets = []
            render_field_label()
            with ui.row().classes("audion-choice-row"):
                for preset in presets:
                    if not isinstance(preset, dict):
                        continue
                    button = ui.button(
                        preset_label(preset),
                        on_click=preset_click_handler(preset),
                    ).props("dense flat no-wrap").classes("audion-action rounded-lg")
                    attach_tooltip(button, dict_tooltip(preset) or tooltip)
            if hint:
                ui.label(hint).classes("audion-field-hint")
            return

        if kind in {"select", "choice", "format"}:
            props = "dense outlined popup-content-class=audion-select-popup"
            if bool(field.get("searchable", field.get("with_input", False))):
                props += " use-input input-debounce=0"

            api_key_provider = api_key_provider_for_field(field)
            if api_key_provider:
                with ui.row().classes("audion-api-key-row"):
                    select = ui.select(
                        options=select_options(field),
                        label=label,
                        value=value,
                        on_change=lambda event, item_key=key: set_field_value(item_key, event.value),
                    )
                    select.props(props).classes("audion-control audion-select audion-api-key-select")
                    attach_tooltip(select, tooltip)
                    if dynamic_option_source(field):
                        refresh_button = ui.button(
                            icon="refresh",
                            on_click=refresh_options_click_handler(field),
                        ).props("dense flat round").classes("audion-action audion-api-key-icon-button")
                        attach_tooltip(refresh_button, field.get("refresh_tooltip_ru" if settings.language == "ru" else "refresh_tooltip") or tooltip or tr("refresh_options"))
                    add_button = ui.button(
                        icon="add",
                        on_click=api_key_add_click_handler(field),
                    ).props("dense flat round").classes("audion-action audion-api-key-icon-button")
                    attach_tooltip(
                        add_button,
                        f"Добавить новый ключ {api_key_provider} в config." if settings.language == "ru" else f"Add a new {api_key_provider} key to config.",
                    )
                    delete_button = ui.button(
                        icon="delete",
                        on_click=api_key_delete_click_handler(field),
                    ).props("dense flat round").classes("audion-action audion-api-key-icon-button audion-api-key-delete-button")
                    attach_tooltip(
                        delete_button,
                        "Убрать выбранный ключ через предупреждение и перенос в архив, не стирая безвозвратно."
                        if settings.language == "ru"
                        else "Remove the selected key through a warning and archive move, without permanent deletion.",
                    )
            else:
                select = ui.select(
                    options=select_options(field),
                    label=label,
                    value=value,
                    on_change=lambda event, item_key=key: set_field_value(item_key, event.value),
                )
                select.props(props).classes("audion-control audion-select w-full")
                attach_tooltip(select, tooltip)
                if dynamic_option_source(field):
                    refresh_button = ui.button(
                        tr("refresh_options"),
                        on_click=refresh_options_click_handler(field),
                    ).props("dense flat no-wrap").classes("audion-action audion-refresh-options rounded-lg")
                    attach_tooltip(refresh_button, field.get("refresh_tooltip_ru" if settings.language == "ru" else "refresh_tooltip") or tooltip or tr("refresh_options"))
            if hint:
                ui.label(hint).classes("audion-field-hint")
            return

        if kind in {"radio", "radiobuttons", "radio-buttons"}:
            render_field_label()
            option_items = choice_option_items(field)
            option_values = [item["value"] for item in option_items]
            if value not in option_values and option_values:
                value = option_values[0]
                set_field_value(key, value)
            if field_choice_style(field) in {"segmented", "tabs", "buttons", "button-toggle", "button_toggle"}:
                render_segmented_choice(field, option_items, value)
            else:
                radio = ui.radio(
                    options={item["value"]: item["label"] for item in option_items},
                    value=value,
                    on_change=lambda event, item_key=key: set_field_value(item_key, event.value),
                ).props("dense inline").classes(field_choice_row_classes(field))
                attach_tooltip(radio, tooltip)
            if dynamic_option_source(field):
                refresh_button = ui.button(
                    tr("refresh_options"),
                    on_click=refresh_options_click_handler(field),
                ).props("dense flat no-wrap").classes("audion-action audion-refresh-options rounded-lg")
                attach_tooltip(refresh_button, field.get("refresh_tooltip_ru" if settings.language == "ru" else "refresh_tooltip") or tooltip or tr("refresh_options"))
            if hint:
                ui.label(hint).classes("audion-field-hint")
            return

        if kind in {"number", "int", "integer", "float"}:
            number_input = ui.number(
                label=label,
                value=value if value != "" else None,
                min=field.get("min"),
                max=field.get("max"),
                step=field.get("step", 1),
                on_change=lambda event, item_key=key: set_field_value(item_key, event.value),
            ).props("dense outlined").classes("audion-control audion-number w-full")
            attach_tooltip(number_input, tooltip)
            with number_input.add_slot("append"):
                with ui.element("div").classes("audion-number-spinner"):
                    up_button = ui.button(
                        icon="keyboard_arrow_up",
                        on_click=lambda item_key=key, item_field=field, control=number_input: spin_number_field(item_key, item_field, control, 1),
                    ).props("dense flat round tabindex=-1").classes("audion-number-spin-button")
                    attach_tooltip(up_button, "Увеличить значение" if settings.language == "ru" else "Increase value")
                    down_button = ui.button(
                        icon="keyboard_arrow_down",
                        on_click=lambda item_key=key, item_field=field, control=number_input: spin_number_field(item_key, item_field, control, -1),
                    ).props("dense flat round tabindex=-1").classes("audion-number-spin-button")
                    attach_tooltip(down_button, "Уменьшить значение" if settings.language == "ru" else "Decrease value")
            if hint:
                ui.label(hint).classes("audion-field-hint")
            return

        if kind in {"checkbox", "bool", "boolean", "toggle"}:
            checkbox = ui.checkbox(
                label,
                value=bool(value),
                on_change=lambda event, item_key=key: set_field_value(item_key, bool(event.value)),
            ).props("dense").classes("audion-single-checkbox")
            attach_tooltip(checkbox, tooltip)
            if hint:
                ui.label(hint).classes("audion-field-hint")
            return

        if is_checkbox_group(field):
            selected = set(value if isinstance(value, list) else [])
            controls: dict[Any, Any] = {}
            option_items = checkbox_option_items(field)
            checkbox_layout = str(field.get("checkbox_layout") or ("list" if dynamic_option_source(field) else "grid")).strip().lower()
            if checkbox_layout not in {"grid", "list", "chips", "grouped_chips"}:
                checkbox_layout = "grid"

            def sync_checkboxes(item_key: str = key) -> None:
                set_field_value(
                    item_key,
                    [option_key for option_key, checkbox in controls.items() if bool(checkbox.value)],
                )

            def option_matches_button(item: dict[str, Any], mode: str, values: set[str] | None = None) -> bool:
                if values is not None:
                    return str(item.get("value") or "") in values
                if mode == "default":
                    default_value = field_default(field)
                    default_items = set(default_value if isinstance(default_value, list) else [])
                    return item.get("value") in default_items
                if mode == "all":
                    return True
                if mode in {"none", "clear"}:
                    return False
                if mode == "missing_pdf":
                    return bool(item.get("missing_pdf"))
                if mode == "outdated":
                    return bool(item.get("outdated"))
                if mode == "changelog":
                    return str(item.get("kind") or item.get("label") or "").upper().find("CHANGELOG") >= 0
                return False

            def apply_checkbox_button(mode: str, values: set[str] | None = None) -> None:
                item_by_value = {item["value"]: item for item in option_items}
                for option_key, checkbox in controls.items():
                    checkbox.set_value(option_matches_button(item_by_value.get(option_key, {}), mode, values))
                sync_checkboxes()

            render_field_label()
            if dynamic_option_source(field):
                refresh_button = ui.button(
                    str(field.get("refresh_label_ru" if settings.language == "ru" else "refresh_label") or tr("refresh_options")),
                    on_click=refresh_options_click_handler(field),
                ).props("dense flat no-wrap").classes("audion-action audion-refresh-options rounded-lg")
                attach_tooltip(refresh_button, field.get("refresh_tooltip_ru" if settings.language == "ru" else "refresh_tooltip") or tooltip or tr("refresh_options"))
            selection_buttons = field.get("selection_buttons", [])
            if isinstance(selection_buttons, list) and selection_buttons:
                with ui.row().classes("audion-checkbox-actions"):
                    for button in selection_buttons:
                        if not isinstance(button, dict):
                            continue
                        mode = str(button.get("mode") or "").strip()
                        explicit_values = {
                            str(value) for value in button.get("values", [])
                        } if isinstance(button.get("values"), list) else None
                        button_label = str(
                            button.get("label_ru" if settings.language == "ru" else "label")
                            or button.get("label")
                            or mode
                        )
                        action_button = ui.button(
                            button_label,
                            on_click=lambda _mode=mode, _values=explicit_values: apply_checkbox_button(_mode, _values),
                        ).props("dense flat no-wrap").classes("audion-action rounded-lg")
                        attach_tooltip(action_button, dict_tooltip(button) or checkbox_action_tooltip(field, mode, button_label))
            def render_checkbox_items(items: list[dict[str, Any]]) -> None:
                for item in items:
                    option_key = item["value"]
                    option_text = item["label"]
                    item_classes = "audion-checkbox-item"
                    if item.get("tone"):
                        item_classes += f" audion-checkbox-tone-{item['tone']}"
                    checkbox = ui.checkbox(
                        option_text,
                        value=option_key in selected,
                        on_change=lambda _event: sync_checkboxes(),
                    ).props("dense").classes(item_classes)
                    if key != "dev_pdf_doc_kinds":
                        attach_tooltip(checkbox, item.get("tooltip") or tooltip)
                    controls[option_key] = checkbox
            if checkbox_layout == "grouped_chips":
                groups: dict[str, list[dict[str, Any]]] = {}
                for item in option_items:
                    groups.setdefault(str(item.get("tone") or "default"), []).append(item)
                requested_order = field.get("checkbox_group_order", [])
                group_order = [str(group) for group in requested_order] if isinstance(requested_order, list) else []
                group_order.extend(group for group in groups if group not in group_order)
                with ui.element("div").classes("audion-checkbox-options audion-checkbox-options-grouped-chips"):
                    for group in group_order:
                        items = groups.get(group, [])
                        if not items:
                            continue
                        with ui.element("div").classes(f"audion-checkbox-chip-row audion-checkbox-chip-row-{group}"):
                            render_checkbox_items(items)
            else:
                with ui.element("div").classes(f"audion-checkbox-options audion-checkbox-options-{checkbox_layout}"):
                    render_checkbox_items(option_items)
            if hint:
                ui.label(hint).classes("audion-field-hint")
            sync_checkboxes()
            return

        if kind in {"textarea", "multiline"}:
            rows_raw = field.get("rows", field.get("lines", 8))
            try:
                rows = max(3, int(rows_raw or 8))
            except (TypeError, ValueError):
                rows = 8
            textarea_control = ui.textarea(
                label=label,
                value=str(value) if value is not None else "",
                placeholder=str(field.get("placeholder", "")),
                on_change=lambda event, item_key=key: set_field_value(item_key, event.value),
            ).props(f"dense outlined autogrow rows={rows}").classes("audion-control w-full")
            attach_tooltip(textarea_control, tooltip)
            if hint:
                ui.label(hint).classes("audion-field-hint")
            return

        input_control = ui.input(
            label=label,
            value=str(value) if value is not None else "",
            placeholder=str(field.get("placeholder", "")),
            on_change=lambda event, item_key=key: set_field_value(item_key, event.value),
        ).props("dense outlined").classes("audion-control w-full")
        attach_tooltip(input_control, tooltip)
        if hint:
            ui.label(hint).classes("audion-field-hint")


def is_empty_field_value(value: Any) -> bool:
    return value is None or value == "" or value == []


def field_kind(field: dict[str, Any]) -> str:
    return str(field.get("type", field.get("kind", "text"))).strip().lower()


def is_module_path_field(field: dict[str, Any]) -> bool:
    return field_id(field) in {"input_path", "output_path"} and field_kind(field) in {"path", "folder", "file"}


def _condition_items(condition: Any) -> list[tuple[str, Any]]:
    if isinstance(condition, dict):
        return [(str(key), value) for key, value in condition.items()]
    if isinstance(condition, list):
        items: list[tuple[str, Any]] = []
        for entry in condition:
            if isinstance(entry, dict):
                field_key = str(entry.get("field") or entry.get("id") or entry.get("key") or "").strip()
                if field_key:
                    items.append((field_key, entry.get("value", entry.get("equals", entry.get("in")))))
        return items
    return []


def _value_matches_condition(actual: Any, expected: Any) -> bool:
    if isinstance(expected, (list, tuple, set)):
        return any(_value_matches_condition(actual, item) for item in expected)
    if isinstance(expected, dict):
        if "not" in expected:
            return not _value_matches_condition(actual, expected.get("not"))
        if "in" in expected:
            return _value_matches_condition(actual, expected.get("in"))
        if "equals" in expected:
            return _value_matches_condition(actual, expected.get("equals"))
        if "empty" in expected:
            return is_empty_field_value(actual) is bool(expected.get("empty"))
    if isinstance(actual, (list, tuple, set)):
        return any(_value_matches_condition(item, expected) for item in actual)
    if isinstance(actual, bool) or isinstance(expected, bool):
        return bool(actual) is bool(expected)
    return str(actual).strip().lower() == str(expected).strip().lower()


def _field_condition_matches(condition: Any, values: dict[str, Any]) -> bool:
    items = _condition_items(condition)
    if not items:
        return True
    return all(_value_matches_condition(values.get(key), expected) for key, expected in items)


def is_field_visible_for_values(field: dict[str, Any], values: dict[str, Any]) -> bool:
    if bool(field.get("hidden", False)):
        return False
    if field.get("visible") is False:
        return False
    show_if = field.get("show_if", field.get("visible_if", field.get("when")))
    if show_if is not None and not _field_condition_matches(show_if, values):
        return False
    hide_if = field.get("hide_if")
    if hide_if is not None and _field_condition_matches(hide_if, values):
        return False
    return True


def command_visible_fields(fields: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = current_option_values()
    _coerce_field_values_for_fields(values, fields)
    for field in fields:
        key = field_id(field)
        if key and key not in values:
            values[key] = field_default(field)
    return [field for field in fields if not is_module_path_field(field) and is_field_visible_for_values(field, values)]


def operation_from_pending_command(node: CommandNode) -> Operation:
    parameters = dict(node.parameters)
    values = state.setdefault("field_values", {})
    visible_fields = command_visible_fields(node.fields)
    for field in visible_fields:
        key = field_id(field)
        if not key:
            continue
        value = values.get(key, field_default(field))
        if bool(field.get("omit_if_empty", False)) and is_empty_field_value(value):
            continue
        parameters[key] = value
    if any(field_id(field) == "input_path" for field in node.fields):
        parameters["input_path"] = str(current_source_path())
    if any(field_id(field) == "output_path" for field in node.fields):
        parameters["output_path"] = str(current_target_path())
    return node.to_operation(parameters)


def validate_pending_fields(node: CommandNode) -> bool:
    values = state.setdefault("field_values", {})
    for field in command_visible_fields(node.fields):
        if not is_checkbox_group(field):
            continue
        min_selected = int(field.get("min_selected", 0) or 0)
        if min_selected <= 0:
            continue
        key = field_id(field)
        selected = values.get(key, field_default(field))
        if not isinstance(selected, list) or len(selected) < min_selected:
            safe_notify(tr("select_required", field=field_label(field)), "warning")
            return False
    return True


async def run_pending_command(node: CommandNode) -> None:
    if validate_pending_fields(node):
        await start_operation(operation_from_pending_command(node))


def run_pending_click_handler(node: CommandNode):
    async def handler() -> None:
        await run_pending_command(node)

    return handler


def field_signature(fields: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    return tuple(field_id(field) for field in command_visible_fields(fields) if field_id(field))


def can_inline_child_actions(parent: CommandNode | None, children: list[CommandNode]) -> bool:
    if parent is None or not parent.fields or not children:
        return False
    parent_signature = field_signature(parent.fields)
    if not parent_signature:
        return False
    return all(not child.children and field_signature(child.fields) == parent_signature for child in children)


ADVANCED_FIELD_SUFFIXES = (
    "_model_override",
    "_chunk_tokens",
    "_overlap_tokens",
    "_min_chunks",
    "_max_retries",
    "_max_output_tokens",
    "_timeout_sec",
    "_resume",
)

OCR_FIELD_SECTION_ORDER = (
    "encoding",
    "deliverables",
    "model",
    "access",
    "cloud_access",
    "filters",
    "local_access",
    "parameters",
    "options",
    "output",
    "format",
    "source",
    "run",
    "advanced",
)


def is_advanced_field(field: dict[str, Any]) -> bool:
    if bool(field.get("advanced", False)):
        return True
    priority = str(field.get("priority") or field.get("section") or "").strip().lower()
    if priority in {"advanced", "expert", "rare"}:
        return True
    key = field_id(field)
    return any(key.endswith(suffix) for suffix in ADVANCED_FIELD_SUFFIXES)


def split_primary_advanced_fields(fields: tuple[dict[str, Any], ...]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    primary: list[dict[str, Any]] = []
    advanced: list[dict[str, Any]] = []
    for field in fields:
        if is_advanced_field(field):
            advanced.append(field)
        else:
            primary.append(field)
    return primary, advanced


def field_section_id(field: dict[str, Any]) -> str:
    key = field_id(field)
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    section = str(field.get("section") or "").strip().lower()
    explicit = str(field.get("group") or field.get("ui_group") or field.get("section_group") or "").strip().lower()
    if not explicit and section and section not in {"advanced", "expert", "rare"}:
        explicit = section
    if explicit:
        return explicit
    if kind in {"profile_select", "profile-select", "preset_select", "preset-select", "preset_buttons", "presets", "profile_buttons", "profiles"}:
        return "preset"
    if key.endswith("_api_key") or "api_key" in key:
        return "access"
    if key.endswith("_model") or key in {"model", "openai_model", "gemini_model"}:
        return "access"
    if key.startswith("docx_") or key.startswith("dev_pdf_") or any(part in key for part in ("margin", "font", "orientation", "line_height")):
        return "layout"
    if key.startswith("workbench_") or key.startswith("ai_resolver_"):
        return "workbench"
    if key in {"overwrite", "dry_run", "limit_first_file", "test_first_file"} or key.endswith(("_dry_run", "_overwrite")):
        return "run"
    if any(part in key for part in ("source", "input", "url", "file", "folder", "path")):
        return "source"
    if any(part in key for part in ("format", "container", "profile", "preset", "quality", "dpi", "bitrate", "resolution", "prep", "mode")):
        return "format"
    if any(part in key for part in ("output", "report", "export", "package", "release")):
        return "output"
    if any(part in key for part in ("codec", "encode", "engine")):
        return "encoding"
    if kind in {"checkbox", "bool", "boolean", "toggle", "checkboxes", "multi_checkbox", "multicheckbox", "multi-select", "multiselect"}:
        return "options"
    return "parameters"


def field_section_label(section_id: str) -> str:
    key = f"section_{section_id}"
    label = tr(key)
    if label != key:
        return label
    return section_id.replace("_", " ").title()


def group_fields_by_section(
    fields: list[dict[str, Any]],
    section_order: tuple[str, ...] | None = None,
) -> list[tuple[str, list[dict[str, Any]]]]:
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    group_index: dict[str, int] = {}
    for field in fields:
        section_id = field_section_id(field)
        if section_id not in group_index:
            group_index[section_id] = len(groups)
            groups.append((section_id, [field]))
        else:
            groups[group_index[section_id]][1].append(field)
    if section_order:
        priority = {section_id: index for index, section_id in enumerate(section_order)}
        groups = [
            group
            for _, group in sorted(
                enumerate(groups),
                key=lambda item: (priority.get(item[1][0], len(priority) + item[0]), item[0]),
            )
        ]
    return groups


def render_field_grid(fields: list[dict[str, Any]], section_order: tuple[str, ...] | None = None) -> None:
    if not fields:
        return
    with ui.element("div").classes("audion-fields-grid"):
        for section_id, section_fields in group_fields_by_section(fields, section_order):
            with ui.element("section").classes(f"audion-field-section audion-field-section-{section_id}"):
                ui.label(field_section_label(section_id)).classes("audion-section-title")
                with ui.element("div").classes("audion-section-fields"):
                    for field in section_fields:
                        render_field(field)


def render_advanced_fields(fields: list[dict[str, Any]], section_order: tuple[str, ...] | None = None) -> None:
    if not fields:
        return
    with ui.expansion(
        tr("advanced"),
        value=bool(getattr(settings, "advanced_open", False)),
        on_value_change=save_advanced_open,
    ).classes("audion-advanced-expansion w-full") as expansion:
        expansion.props("dense switch-toggle-side")
        render_field_grid(fields, section_order)


def command_node_recommendation_role(node: CommandNode) -> str:
    if node.id not in INSTALL_RECOMMENDATION_NODE_IDS:
        return ""
    data = hardware_badge_data()
    recommended = set(data.get("recommended_install_ids") or [])
    optional = set(data.get("optional_install_ids") or [])
    if node.id in recommended:
        return "recommended"
    if node.id in optional:
        return "optional"
    return ""


def recommendation_pill_text(role: str) -> str:
    if role == "recommended":
        return "Рекомендовано для GPU" if settings.language == "ru" else "Recommended for GPU"
    if role == "optional":
        return "Тяжёлый optional" if settings.language == "ru" else "Heavy optional"
    return ""


def render_operation_description(description: str, role: str = "") -> None:
    with ui.element("div").classes("audion-operation-description"):
        pill = recommendation_pill_text(role)
        if pill:
            ui.label(pill).classes(f"audion-recommendation-pill audion-recommendation-pill-{role}")
        ui.label(description).classes("audion-operation-description-text")


def command_node_button(node: CommandNode) -> None:
    has_children = bool(node.children)
    label = node.display_title(settings.language)
    description = node.display_description(settings.language)
    if has_children and not description:
        description = tr("open_menu")
    role = command_node_recommendation_role(node)
    row_classes = "audion-operation-row"
    button_classes = "audion-action audion-operation-button rounded-lg"
    if node.id == "extract_local":
        row_classes += " audion-operation-row-primary-action"
        button_classes += " audion-operation-button-primary-action"
    if role:
        row_classes += f" audion-operation-row-{role}"
        button_classes += f" audion-operation-button-{role}"

    with ui.element("div").classes(row_classes):
        button = ui.button(
            label,
            on_click=command_click_handler(node),
        ).props("dense flat no-wrap").classes(button_classes)
        attach_tooltip(button, command_node_tooltip(node) or description)
        render_operation_description(description, role)


def render_command_node_list(nodes: list[CommandNode]) -> None:
    with ui.element("div").classes("audion-command-list"):
        for node in nodes:
            command_node_button(node)


def render_inline_operation_blocks(nodes: list[CommandNode]) -> None:
    """Render a small workflow as expanded blocks without another navigation level."""
    with ui.column().classes("audion-inline-operation-blocks w-full gap-2"):
        for node in nodes:
            with ui.expansion(
                node.display_title(settings.language),
                value=True,
            ).props("dense expand-separator").classes("audion-inline-operation-block w-full"):
                description = node.display_description(settings.language)
                if description:
                    ui.label(description).classes("audion-command-description")
                visible_fields = command_visible_fields(node.fields)
                if visible_fields:
                    primary_fields, advanced_fields = split_primary_advanced_fields(visible_fields)
                    render_field_grid(primary_fields)
                    render_advanced_fields(advanced_fields)
                with ui.row().classes("w-full justify-end pt-1"):
                    run_button = ui.button(
                        tr("run"),
                        on_click=run_pending_click_handler(node),
                    ).props("dense flat no-wrap").classes("audion-action audion-nav-run-button rounded-lg")
                    attach_tooltip(run_button, command_node_tooltip(node) or node.display_description(settings.language))


def is_ocr_command_node(node: CommandNode | None) -> bool:
    if node is None:
        return False
    return node.id in {"ocr_local_run", "ocr_api_run", "ocr_brick_run"}


LOCAL_HARDWARE_BADGE_NODE_IDS = {
    "ocr_local",
    "ocr_local_run",
}


def should_show_hardware_badge(
    trail: list[CommandNode],
    pending: CommandNode | None,
    nodes: list[CommandNode],
) -> bool:
    del nodes
    if pending is None and not trail:
        return False
    candidates = [node.id for node in trail]
    if pending is not None:
        candidates.append(pending.id)
    return any(item in LOCAL_HARDWARE_BADGE_NODE_IDS for item in candidates)


def is_project_tools_window(trail: list[CommandNode], pending: CommandNode | None) -> bool:
    return pending is None and bool(trail) and trail[-1].id == "project_tools"


def project_tools_mode() -> str:
    mode = str(state.get("project_tools_mode") or "install").strip().lower()
    return mode if mode in {"install", "check"} else "install"


def set_project_tools_mode(mode: str) -> None:
    state["project_tools_mode"] = "check" if mode == "check" else "install"
    state["pending_command"] = None
    command_tree.refresh()


def project_tools_nodes_for_mode(nodes: list[CommandNode]) -> list[CommandNode]:
    by_id = {node.id: node for node in nodes}
    ordered_ids = PROJECT_TOOLS_CHECK_NODE_IDS if project_tools_mode() == "check" else PROJECT_TOOLS_INSTALL_NODE_IDS
    return [by_id[node_id] for node_id in ordered_ids if node_id in by_id]


def project_tools_switcher() -> None:
    active = project_tools_mode()
    install_label = "УСТАНОВКА" if settings.language == "ru" else "INSTALL"
    check_label = "ПРОВЕРКА" if settings.language == "ru" else "CHECK"
    install_tip = (
        "Установка локальных компонентов: Tesseract для бесплатного OCR, Real-ESRGAN для улучшения сканов, Surya/llama.cpp для тяжёлого локального OCR."
        if settings.language == "ru"
        else "Install local components: Tesseract for free OCR, Real-ESRGAN for scan enhancement, Surya/llama.cpp for heavy local OCR."
    )
    check_tip = (
        "Проверка проекта, окружения, ключей API, списков моделей и короткие smoke-тесты OCR."
        if settings.language == "ru"
        else "Check project status, runtime, API keys, model lists, and short OCR smoke tests."
    )

    def button_classes(mode: str) -> str:
        classes = "audion-project-mode-button"
        if active == mode:
            classes += " audion-project-mode-button-active"
        return classes

    with ui.row().classes("audion-project-mode-switch w-full items-center"):
        install_button = ui.button(
            install_label,
            on_click=lambda: set_project_tools_mode("install"),
        ).props("dense flat no-wrap").classes(button_classes("install"))
        attach_tooltip(install_button, install_tip)
        ui.space()
        check_button = ui.button(
            check_label,
            on_click=lambda: set_project_tools_mode("check"),
        ).props("dense flat no-wrap").classes(button_classes("check"))
        attach_tooltip(check_button, check_tip)


def command_nav_row(
    trail: list[CommandNode],
    pending: CommandNode | None,
    inline_actions: list[CommandNode] | None = None,
) -> None:
    can_go_back = pending is not None or bool(trail)
    if pending is not None:
        title = pending.display_title(settings.language)
    elif trail:
        title = " / ".join(node.display_title(settings.language) for node in trail)
    else:
        title = ""

    with ui.row().classes("audion-command-nav w-full items-center gap-2"):
        if can_go_back:
            back_button = ui.button(
                tr("back"),
                on_click=go_back_command,
            ).props("dense flat no-wrap").classes("audion-action w-28 rounded-lg")
            attach_tooltip(back_button, "Вернуться на уровень выше без запуска операции." if settings.language == "ru" else "Go one level back without running an operation.")
        ui.label(title).classes("audion-nav-title min-w-0 flex-1 truncate")
        if pending is not None:
            run_button = ui.button(
                tr("run"),
                on_click=run_pending_click_handler(pending),
            ).props("dense flat no-wrap").classes("audion-action audion-nav-run-button rounded-lg")
            attach_tooltip(run_button, command_node_tooltip(pending) or tr("run"))
        elif inline_actions:
            with ui.row().classes("audion-command-nav-actions items-center gap-2"):
                for node in inline_actions:
                    action_button = ui.button(
                        node.display_title(settings.language),
                        on_click=run_pending_click_handler(node),
                    ).props("dense flat no-wrap").classes("audion-action audion-nav-run-button rounded-lg")
                    attach_tooltip(action_button, command_node_tooltip(node) or node.display_description(settings.language))


@ui.refreshable
def command_tree() -> None:
    trail, nodes = current_command_level()
    pending = state.get("pending_command")
    parent = trail[-1] if trail else None
    inline_actions = nodes if pending is None and can_inline_child_actions(parent, nodes) else []
    command_nav_row(trail, pending, inline_actions)
    if is_project_tools_window(trail, pending):
        hardware_badge()
        project_tools_switcher()
        render_command_node_list(project_tools_nodes_for_mode(nodes))
        return
    if pending is None and parent is not None and parent.id == "table_workflow":
        render_inline_operation_blocks(nodes)
        return
    if should_show_hardware_badge(trail, pending, nodes):
        hardware_badge()

    if pending is not None:
        dialog_classes = "audion-command-dialog"
        if is_ocr_command_node(pending):
            dialog_classes += " audion-ocr-command-dialog"
        if pending.id == "ocr_local_run":
            dialog_classes += " audion-ocr-local-dialog"
        elif pending.id == "ocr_api_run":
            dialog_classes += " audion-ocr-api-dialog"
        with ui.element("div").classes(dialog_classes):
            visible_fields = command_visible_fields(pending.fields)
            if visible_fields:
                primary_fields, advanced_fields = split_primary_advanced_fields(visible_fields)
                section_order = OCR_FIELD_SECTION_ORDER if is_ocr_command_node(pending) else None
                ui.label(tr("parameters")).classes("audion-section-title")
                render_field_grid(primary_fields, section_order)
            else:
                advanced_fields = []
                section_order = None
            if visible_fields:
                render_advanced_fields(advanced_fields, section_order)
            description = pending.display_description(settings.language)
            if description:
                ui.label(description).classes("audion-command-description")
        return

    if inline_actions:
        with ui.element("div").classes("audion-command-dialog"):
            primary_fields, advanced_fields = split_primary_advanced_fields(command_visible_fields(parent.fields))
            ui.label(tr("parameters")).classes("audion-section-title")
            render_field_grid(primary_fields)
            render_advanced_fields(advanced_fields)
        return

    render_command_node_list(nodes)


def operation_by_id(operation_id: str) -> Operation | None:
    for operation in [*manifest.operations, *manifest.maintenance_operations]:
        if operation.id == operation_id:
            return operation
    return None


APPLICATION_CSS_PATH = Path(__file__).resolve().with_name("theme.css")
_application_css_cache = ""


def application_css() -> str:
    """The application stylesheet lives next to this module, not inside it."""
    global _application_css_cache
    if not _application_css_cache:
        _application_css_cache = APPLICATION_CSS_PATH.read_text(encoding="utf-8")
    return _application_css_cache


def add_styles() -> None:
    add_audion_canonical_ui_styles()
    variables_css = "\n".join(
        f"            --{key}: {value};"
        for key, value in sorted(theme_variables().items())
    )
    ui.add_head_html(
        "<style>\n"
        ":root {\n"
        f"{variables_css}\n"
        "}\n"
        + application_css()
        + WORKBENCH_LAYOUT_CSS
        + WORKBENCH_OVERRIDE_CSS
        + "\n</style>\n"
    )
    ui.add_head_html(WORKBENCH_FEEDBACK_CSS)


def build_ui() -> None:
    ensure_project_dirs(paths)
    if not state["status"]:
        state["status"] = tr("idle")
    if active_theme_mode() == "dark":
        ui.dark_mode().enable()
    else:
        ui.dark_mode().disable()
    add_styles()

    with ui.header().classes("audion-header h-[42px] items-center justify-between px-4"):
        ui.label(app_title()).classes("audion-header-title text-lg font-bold")
        with ui.row().classes("audion-header-controls items-center gap-2"):
            ui.icon("palette").classes("text-lg")
            ui.select(
                options=theme_options(),
                value=active_theme(),
                on_change=theme_change_handler,
            ).props("dense outlined options-dense").classes("audion-theme-select").tooltip(
                "Выбрать цветовую тему интерфейса." if settings.language == "ru" else "Choose the UI color theme."
            )
            lang_button = ui.button(tr("lang_switch"), on_click=toggle_language).props("dense flat").classes("audion-action rounded-lg")
            attach_tooltip(lang_button, "Переключить язык интерфейса." if settings.language == "ru" else "Switch interface language.")
            cancel_button = ui.button(tr("cancel"), on_click=lambda: state.update({"cancel": True})).props("dense flat color=negative")
            attach_tooltip(cancel_button, "Попросить текущую операцию остановиться." if settings.language == "ru" else "Ask the current operation to stop.")
            cancel_button.visible = False

    with ui.element("div").classes("audion-shell"):
        with ui.column().classes("audion-pane audion-scroll gap-3"):
            with ui.column().classes("audion-panel audion-workspace-panel w-full gap-2 p-2"):
                WORKBENCH_RENDERER.render_address_rows()
                WORKBENCH_RENDERER.render_action_bar()

            ui.label(f"{em('operations')}{tr('operations')}").classes("text-lg font-bold")
            command_tree()

            if manifest.maintenance_operations:
                ui.label(f"{em('maintenance')}{tr('maintenance')}").classes("text-lg font-bold pt-2")
                for operation in manifest.maintenance_operations:
                    if operation.id == "cleanup_input_output":
                        continue
                    operation_button(operation)

        ui.element("div").classes("audion-splitter").props('title="Resize panels"')

        with ui.element("div").classes("audion-pane audion-right gap-2 pt-3"):
            with ui.column().classes("audion-panel w-full gap-2 p-3"):
                        with ui.element("div").classes(status_row_classes()) as status_row:
                            status_dot_main = ui.element("span").classes("audion-status-dot-mark")
                            status_state_label = ui.label(status_state_text()).classes("audion-status-state")
                            status_label = ui.label(str(state["status"])).classes("audion-status-message")
                            status_clock = ui.label(elapsed_text(None)).classes("audion-status-clock")
                            with ui.element("div").classes("audion-status-bar"):
                                status_bar_fill = ui.element("i").style("width: 0%")
                            status_percent = ui.label(progress_text()).classes("audion-status-percent")

            with ui.column().classes("audion-terminal-panel w-full gap-2 p-3"):
                with ui.row().classes("audion-log-toolbar w-full items-center gap-2"):
                    ui.label(f"{em('log')}{tr('log')}").classes("text-base font-semibold")
                    ui.space()
                    logs_button = ui.button(tr("logs"), on_click=lambda: open_folder(paths.logs)).props("dense flat").classes("audion-action rounded-lg").tooltip(audion_folder_button_tooltip("logs", paths.logs))
                    attach_tooltip(logs_button, "Открыть папку с логами запусков." if settings.language == "ru" else "Open the run logs folder.")
                    report_button = ui.button(tr("report"), on_click=lambda: open_folder(paths.report)).props("dense flat").classes("audion-action rounded-lg").tooltip(audion_folder_button_tooltip("report", paths.report))
                    attach_tooltip(report_button, "Открыть папку с отчётами и диагностикой." if settings.language == "ru" else "Open reports and diagnostics.")
                    config_button = ui.button(tr("config"), on_click=lambda: open_folder(paths.config)).props("dense flat").classes("audion-action rounded-lg").tooltip(audion_folder_button_tooltip("config", paths.config))
                    attach_tooltip(config_button, "Открыть папку настроек и ключей проекта." if settings.language == "ru" else "Open project settings and key files.")
                    clear_log_button = ui.button(icon="delete_sweep", on_click=clear_terminal_log).props("dense flat round").classes("audion-action audion-log-icon-button")
                    clear_log_button.tooltip(audion_terminal_action_tooltip("clear_terminal_window"))
                    expand_log_button = ui.button(icon="open_in_full", on_click=lambda: log_dialog.open()).props("dense flat round").classes("audion-action audion-log-icon-button")
                    expand_log_button.tooltip(audion_terminal_action_tooltip("expand"))
                log_view = ui.html(terminal_pre_html(TERMINAL_MAIN_PRE_ID), sanitize=False).classes("audion-terminal w-full min-h-[66vh]")
                with ui.row().classes("audion-terminal-footer w-full items-center gap-2 px-1 pt-1"):
                    status_dot = ui.label("●").classes(status_dot_classes())
                    terminal_status_label = ui.label(str(state["status"])).classes("min-w-0 flex-1 truncate text-xs")

    with ui.dialog() as log_dialog:
        with ui.card().classes("audion-dialog h-[92vh] w-[92vw] rounded-lg p-3"):
            with ui.row().classes("w-full items-center gap-2"):
                ui.label(f"{em('log')}{tr('log')}").classes("text-base font-semibold")
                ui.space()
                expanded_config_button = ui.button(tr("config"), on_click=lambda: open_folder(paths.config)).props("dense flat").classes("audion-action rounded-lg").tooltip(audion_folder_button_tooltip("config", paths.config))
                attach_tooltip(expanded_config_button, "Открыть папку настроек и ключей проекта." if settings.language == "ru" else "Open project settings and key files.")
                clear_expanded_log_button = ui.button(icon="delete_sweep", on_click=clear_terminal_log).props("dense flat round").classes("audion-action audion-log-icon-button")
                clear_expanded_log_button.tooltip(audion_terminal_action_tooltip("clear_terminal_window"))
                close_button = ui.button(tr("close"), on_click=log_dialog.close).props("dense flat").classes("audion-action rounded-lg").tooltip(audion_terminal_action_tooltip("close"))
                attach_tooltip(close_button, "Закрыть большое окно журнала." if settings.language == "ru" else "Close the expanded log window.")
            expanded_log_view = ui.html(terminal_pre_html(TERMINAL_EXPANDED_PRE_ID), sanitize=False).classes("audion-terminal audion-terminal-expanded w-full")

    ui.run_javascript(
        """
        (() => {
          const storageKey = 'audion_gui_terminal_width_px';
          const defaultWidth = 620;
          const minLeft = 520;
          const minRight = 420;

          const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

          const applyWidth = (width) => {
            const shell = document.querySelector('.audion-shell');
            if (!shell) return;
            const rect = shell.getBoundingClientRect();
            const maxRight = Math.max(minRight, rect.width - minLeft - 40);
            const next = clamp(Number(width) || defaultWidth, minRight, maxRight);
            shell.style.setProperty('--audion-terminal-width', `${Math.round(next)}px`);
            localStorage.setItem(storageKey, String(Math.round(next)));
          };

          const setup = () => {
            const shell = document.querySelector('.audion-shell');
            const splitter = document.querySelector('.audion-splitter');
            if (!shell || !splitter) {
              setTimeout(setup, 80);
              return;
            }
            if (splitter.dataset.audionReady === '1') return;
            splitter.dataset.audionReady = '1';

            applyWidth(localStorage.getItem(storageKey) || defaultWidth);

            let dragging = false;
            const updateFromEvent = (event) => {
              if (!dragging) return;
              const rect = shell.getBoundingClientRect();
              const rightWidth = rect.right - event.clientX - 10;
              applyWidth(rightWidth);
            };

            splitter.addEventListener('pointerdown', (event) => {
              dragging = true;
              splitter.setPointerCapture?.(event.pointerId);
              document.body.classList.add('audion-resizing');
              event.preventDefault();
            });
            splitter.addEventListener('pointermove', updateFromEvent);
            splitter.addEventListener('pointerup', (event) => {
              dragging = false;
              splitter.releasePointerCapture?.(event.pointerId);
              document.body.classList.remove('audion-resizing');
            });
            splitter.addEventListener('pointercancel', () => {
              dragging = false;
              document.body.classList.remove('audion-resizing');
            });
            window.addEventListener('resize', () => applyWidth(localStorage.getItem(storageKey) || defaultWidth));
          };

          setup();
        })();
        """
    )

    last_log_version = {"value": -1}
    terminal_render_state = {
        "offset": int(state.get("line_offset", 0)),
        "count": len(state["lines"]),
    }

    refresh_timer: Any | None = None

    def update_terminal_dom(html: str, *, reset: bool) -> None:
        if not html and not reset:
            return
        mode = "reset" if reset else "append"
        ui.run_javascript(
            f"""
            (() => {{
              const html = {json.dumps(html)};
              const mode = {json.dumps(mode)};
              const limit = {TERMINAL_HISTORY_LIMIT};
              const selection = window.getSelection ? window.getSelection() : null;
              const selecting = Boolean(selection && selection.rangeCount && !selection.isCollapsed);
              requestAnimationFrame(() => {{
                document.querySelectorAll('.audion-terminal-pre').forEach((pre) => {{
                  const terminal = pre.closest('.audion-terminal');
                  const wasAtBottom = !terminal || (terminal.scrollHeight - terminal.scrollTop - terminal.clientHeight) <= 8;
                  if (mode === 'reset') {{
                    pre.innerHTML = html;
                  }} else if (html) {{
                    pre.insertAdjacentHTML('beforeend', html);
                  }}
                  if (!selecting) {{
                    while (pre.children.length > limit) {{
                      pre.firstElementChild?.remove();
                    }}
                  }}
                  if (wasAtBottom && terminal && !selecting) {{
                    terminal.scrollTop = terminal.scrollHeight;
                  }}
                }});
              }});
            }})();
            """
        )

    # Every one of these used to be written twice a second whether or not it had
    # changed, so an idle window still sent ten element updates a second. Holding
    # the last value makes an idle panel cost nothing and pays for the clock.
    shown = {"status": None, "state": None, "row": None, "clock": None, "percent": None, "fill": None}
    run_clock: dict[str, float | None] = {"started": None, "frozen": None}

    def refresh() -> None:
        nonlocal refresh_timer
        try:
            running = bool(state["running"])
            if running and run_clock["started"] is None:
                run_clock["started"] = time.monotonic()
                run_clock["frozen"] = None
            elif not running and run_clock["started"] is not None:
                run_clock["frozen"] = time.monotonic() - run_clock["started"]
                run_clock["started"] = None
            seconds = (
                time.monotonic() - run_clock["started"]
                if run_clock["started"] is not None
                else run_clock["frozen"]
            )

            def show(key: str, value: Any, assign: Any) -> None:
                if shown[key] != value:
                    shown[key] = value
                    assign(value)

            message = str(state["status"])
            show("status", message, lambda value: (
                setattr(status_label, "text", value),
                setattr(terminal_status_label, "text", value),
            ))
            show("state", status_state_text(), lambda value: setattr(status_state_label, "text", value))
            show("row", status_row_classes(), lambda value: (
                status_row.classes(replace=value),
                status_dot.classes(replace=status_dot_classes()),
            ))
            show("clock", elapsed_text(seconds), lambda value: setattr(status_clock, "text", value))
            show("percent", progress_text(), lambda value: setattr(status_percent, "text", value))
            show("fill", f"{float(state['progress']) * 100:.1f}%",
                lambda value: status_bar_fill.style(f"width: {value}"))
            log_version = int(state["log_version"])
            if log_version != last_log_version["value"]:
                last_log_version["value"] = log_version
                lines = [str(line) for line in state["lines"]]
                offset = int(state.get("line_offset", 0))
                current_next = offset + len(lines)
                previous_next = int(terminal_render_state["offset"]) + int(terminal_render_state["count"])
                reset_needed = (
                    previous_next < offset
                    or previous_next > current_next
                    or (not lines and int(terminal_render_state["count"]) > 0)
                )
                if reset_needed:
                    update_terminal_dom(terminal_line_spans_html(lines, offset), reset=True)
                else:
                    new_lines = lines[previous_next - offset :]
                    if new_lines:
                        update_terminal_dom(terminal_line_spans_html(new_lines, previous_next), reset=False)
                terminal_render_state["offset"] = offset
                terminal_render_state["count"] = len(lines)
            cancel_button.visible = bool(state["running"])
        except RuntimeError as exc:
            message = str(exc)
            if "slot belongs to has been deleted" not in message and "current slot cannot be determined" not in message:
                raise
            logging.warning("NiceGUI refresh timer stopped because the client slot was deleted.")
            if refresh_timer is not None:
                refresh_timer.deactivate()

    refresh_timer = ui.timer(0.5, refresh)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audion NiceGUI shell.")
    parser.add_argument("--host", default=str(ui_info.get("host", "127.0.0.1")))
    parser.add_argument("--port", type=int, default=int(ui_info.get("port", 8080)))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    return parser.parse_args()


def port_is_open(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in str(host or "") else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.3)
            return sock.connect_ex((host, port)) == 0
    except OSError:
        return False


def env_flag_enabled(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def assert_gui_host_allowed(host: str) -> None:
    normalized = str(host or "").strip().lower().strip("[]")
    try:
        is_loopback = normalized == "localhost" or ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        is_loopback = normalized == "localhost"
    if is_loopback or env_flag_enabled("AUDION_ALLOW_REMOTE_GUI"):
        return
    raise SystemExit(
        "Refusing non-loopback host for a GUI with process execution. "
        "Use 127.0.0.1/localhost/::1, or set AUDION_ALLOW_REMOTE_GUI=1 explicitly."
    )


def build_ui_once() -> dict[str, int]:
    """Build the whole page once, headlessly, and report what came of it.

    `--smoke` used to print a line and return, so an app could ship a `build_ui`
    that raised on its first statement and still pass — twice in this fleet it did.
    Here the page is actually built: no browser and no HTTP request, so whatever
    the app defers until a client attaches is skipped, but every widget is
    constructed and the stylesheet has to arrive.
    """
    import asyncio
    import logging
    import re

    from nicegui import core
    from nicegui.client import Client
    from nicegui.page import page as page_definition

    async def build() -> tuple[int, str]:
        core.loop = asyncio.get_running_loop()
        # Work deferred to a connected browser fails here and says nothing about
        # the build. An exception raised by build_ui itself still propagates.
        core.loop.set_exception_handler(lambda _loop, _context: None)
        logging.getLogger("nicegui").setLevel(logging.CRITICAL)
        client = Client(page_definition("/__smoke__"))
        with client:
            build_ui()
        report = len(client.elements), client.shared_head_html + client.head_html
        # The page starts work that waits for a browser to attach. Nothing will
        # attach, so stop it deliberately instead of letting the loop close on it.
        pending = asyncio.all_tasks(core.loop) - {asyncio.current_task()}
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        return report

    element_count, head = asyncio.run(build())
    if element_count < 2:
        raise RuntimeError("build_ui produced no widgets")
    # Token prefixes differ between apps, so look for any custom property rather
    # than for one project's naming.
    if not re.search(r"--[\w-]+\s*:", head):
        raise RuntimeError("the stylesheet never reached the page")
    return {"elements": element_count, "stylesheet_bytes": len(head)}


def main() -> int:
    args = parse_args()
    assert_gui_host_allowed(args.host)
    ensure_project_dirs(paths)
    if args.smoke:
        try:
            report = build_ui_once()
        except Exception as error:  # noqa: BLE001
            print(f"FAIL nicegui shell: {ROOT}: {error}")
            return 1
        print(
            f"OK nicegui shell: {ROOT}"
            f" | widgets={report['elements']}"
            f" | stylesheet={report['stylesheet_bytes']} bytes"
        )
        return 0

    if port_is_open(args.host, args.port):
        url = f"http://{args.host}:{args.port}/"
        print(f"GUI already appears to be running: {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0

    ui.run(
        root=build_ui,
        title=app_title(),
        host=args.host,
        port=args.port,
        reload=False,
        native=False,
        show=not args.no_browser,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
