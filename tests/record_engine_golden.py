"""Write tests\\engine_golden.json: the reference runs of the engine, as it is before the move.

Run: runtime\\python.exe -B tests\\record_engine_golden.py [case-id ...]
With case ids, only those cases are run, into %TEMP%\\audion-ocr-golden\\partial.json - the reference is not touched.
The stand lives in %TEMP%\\audion-ocr-golden and is removed at the end.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding="utf-8")
for extra in (HERE, ROOT, ROOT / "runtime" / "Lib" / "site-packages"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from engine_golden_cases import CASES, run_case  # noqa: E402
from engine_golden_lib import build_stand, make_fixtures, remove_stand  # noqa: E402

OUT = HERE / "engine_golden.json"


def main(argv: list[str]) -> int:
    wanted = set(argv)
    base = Path(tempfile.gettempdir()) / "audion-ocr-golden"
    stand = build_stand(base / "stand")
    fixtures = make_fixtures(base / "fixtures")
    results = {}
    try:
        for case in CASES:
            if wanted and case.id not in wanted:
                continue
            outcome = run_case(case, stand, fixtures)
            results[case.id] = outcome
            print(f"{case.id}: ok={outcome['ok']} files={len(outcome.get('output', {}))} requests={len(outcome['requests'])}", flush=True)
    finally:
        os.chdir(ROOT)
        remove_stand(stand)
    if wanted:
        partial = base / "partial.json"
        partial.write_text(json.dumps(results, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        print(f"{partial}: {len(results)} cases")
        return 0
    OUT.write_text(json.dumps({"schema": 1, "cases": results}, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"{OUT}: {len(results)} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
