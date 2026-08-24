# gui_panel.py
# NiceGUI panel SKELETON for the OCR brick. Adapt into the existing Audion GUI.
# Engine selection is via TOGGLE BUTTONS (not radio): the active engine button is
# highlighted, and toggles can shade / show / hide dependent controls. The master
# Preprocess toggle hides the whole cleaning-controls block when set to raw
# passthrough. This is a stub; wire the run button to the app's job runner.
# No globals; the controller is passed in. EN comments only. UTF-8 without BOM.
#
# Requires: nicegui.  TODO(codex): integrate with the live OCR GUI layout/threading.

from __future__ import annotations

from typing import Any

from nicegui import ui

from pipeline_controller import PipelineController, JobRequest


# Manual choice per image; no auto-selection.
ENGINES = ["tesseract", "surya", "yandex", "gemini", "chatgpt"]


def build_panel(controller: PipelineController, on_done=None) -> None:
    state: dict[str, Any] = {
        "source": "",
        "engine": "tesseract",
        "overrides": {},          # only set what the user changes
        "engine_params": {"lang": "rus", "psm": 6},
    }
    engine_buttons: dict[str, Any] = {}

    ui.label("OCR - engine & cleaning").classes("text-lg")

    # --- engine selector: TOGGLE BUTTONS with active highlight ---
    def select_engine(name: str) -> None:
        state["engine"] = name
        for n, b in engine_buttons.items():
            active = (n == name)
            # highlight active, flatten the rest
            b.props(remove="flat color=grey")
            if active:
                b.props("color=primary")
            else:
                b.props("flat color=grey")
        # show engine-specific controls only for the active engine
        yandex_box.set_visibility(name == "yandex")

    with ui.row():
        for name in ENGINES:
            engine_buttons[name] = ui.button(
                name, on_click=lambda _, n=name: select_engine(n))

    # --- Yandex-specific controls (mode + recognition model), toggled visible ---
    yandex_box = ui.column()
    with yandex_box:
        # sync vs async batch as a toggle
        ui.toggle({"sync": "Sync (per page)", "batch": "Batch (thousands)"},
                  value="sync",
                  on_change=lambda e: state["engine_params"].update(mode=e.value))
        # recognition model: page (print) vs handwritten vs specialized
        ui.toggle({"page": "Printed", "handwritten": "Handwritten"},
                  value="page",
                  on_change=lambda e: state["engine_params"].update(model=e.value))

    # --- MASTER preprocess toggle: hides the cleaning block when OFF ---
    cleaning_box = ui.column()  # container whose visibility we flip

    def set_preprocess(enabled: bool) -> None:
        state["overrides"]["enabled"] = enabled
        cleaning_box.set_visibility(enabled)   # raw passthrough -> hide all knobs

    ui.switch("Preprocess (off = raw passthrough)", value=True,
              on_change=lambda e: set_preprocess(e.value))

    # --- cleaning overrides (each control only mutates a CleanConfig field) ---
    with cleaning_box:
        ui.select({0: "Upscale Off", 2: "2x", 4: "4x"}, value=2,
                  on_change=lambda e: state["overrides"].update(sr_scale=e.value)) \
            .props("label='Upscale'")
        ui.select(["none", "weak", "strong"], value="weak",
                  on_change=lambda e: state["overrides"].update(denoise=e.value)) \
            .props("label='Denoise (JPEG)'")
        ui.switch("Remove vertical lines", value=False,
                  on_change=lambda e: state["overrides"].update(strip_vlines=e.value))
        ui.switch("Deskew", value=True,
                  on_change=lambda e: state["overrides"].update(deskew=e.value))
        ui.select(["auto", "on", "off"], value="auto",
                  on_change=lambda e: state["overrides"].update(binarize=e.value)) \
            .props("label='Binarize'")
        ui.select(["text", "image"], value="text",
                  on_change=lambda e: state["overrides"].update(intent=e.value)) \
            .props("label='Cleaning intent'")

    # --- source + run ---
    ui.input("Source path", on_change=lambda e: state.update(source=e.value))

    def run() -> None:
        # TODO(codex): run off the UI thread; stream per-page progress.
        req = JobRequest(
            source_path=state["source"],
            engine=state["engine"],
            gui_overrides=dict(state["overrides"]),
            engine_params=dict(state["engine_params"]),
        )
        import uuid
        results = controller.run_job(req, job_id=uuid.uuid4().hex)
        if on_done:
            on_done(results)
        else:
            ui.notify(f"{len(results)} page(s) processed")

    ui.button("Run OCR", on_click=run)

    select_engine("tesseract")  # set initial highlight
