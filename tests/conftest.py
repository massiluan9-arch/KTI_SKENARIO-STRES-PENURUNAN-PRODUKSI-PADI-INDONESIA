import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture(scope="session")
def P_real():
    from crm import load_production
    return load_production(ROOT / "data" / "produksi_padi.xlsx")
