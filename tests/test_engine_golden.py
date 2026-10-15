"""The engine makes what it made before the move to Avalonia.

Each case of tests\\engine_golden_cases.py is run on a fresh stand (copy of system_core and the
non-secret config, runtime linked, fake keys, providers answering from canned replies) and its
digest is compared with tests\\engine_golden.json, written by tests\\record_engine_golden.py from
version 1.8.2. A difference is either a regression or a deliberate change - then the reference is
written again and the change is named in CHANGELOG.

Two recorded cases end in an error, on purpose: they pin how 1.8.2 behaved (LAYOUT with Tesseract is
refused by the engine; Build PPTX fails on a slide layout without a body). If a fix changes that,
the reference changes with it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine_golden_cases import CASES, run_case
from engine_golden_lib import build_stand, make_fixtures, remove_stand

REFERENCE = Path(__file__).resolve().parent / "engine_golden.json"


@pytest.fixture(scope="module")
def golden_stand(tmp_path_factory: pytest.TempPathFactory):
    base = tmp_path_factory.mktemp("audion-ocr-golden")
    stand = build_stand(base / "stand")
    fixtures = make_fixtures(base / "fixtures")
    yield stand, fixtures
    remove_stand(stand)


def _first_difference(expected, actual, where: str = "") -> str | None:
    if type(expected) is not type(actual):
        return f"{where}: {type(expected).__name__} != {type(actual).__name__}"
    if isinstance(expected, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in actual:
                return f"{where}/{key}: missing now"
            if key not in expected:
                return f"{where}/{key}: new now"
            found = _first_difference(expected[key], actual[key], f"{where}/{key}")
            if found:
                return found
        return None
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return f"{where}: {len(expected)} items before, {len(actual)} now"
        for index, (left, right) in enumerate(zip(expected, actual)):
            found = _first_difference(left, right, f"{where}[{index}]")
            if found:
                return found
        return None
    if expected != actual:
        return f"{where}: {str(expected)[:200]!r} before, {str(actual)[:200]!r} now"
    return None


@pytest.mark.integration
@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_engine_makes_what_it_made_before(case, golden_stand) -> None:
    stand, fixtures = golden_stand
    expected = json.loads(REFERENCE.read_text(encoding="utf-8"))["cases"][case.id]
    actual = json.loads(json.dumps(run_case(case, stand, fixtures), ensure_ascii=False, sort_keys=True))
    difference = _first_difference(expected, actual)
    assert difference is None, f"{case.id}: {difference}"
