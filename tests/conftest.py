from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_SITE_PACKAGES = PROJECT_ROOT / "runtime" / "Lib" / "site-packages"

for path in (PROJECT_ROOT, PROJECT_SITE_PACKAGES):
    text = str(path)
    if path.exists() and text not in sys.path:
        sys.path.insert(0, text)
