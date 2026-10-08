import math

import numpy as np
import pandas as pd
import pytest

from crm import (build_components, classify_level, exceedance_prob, priority_matrix,
                          replay_year, return_period, sentra_serentak, worst_relative_decline)


def toy():
    return pd.DataFrame({2018: [100.0, 50.0, 10.0], 2019: [90.0, 60.0, 10.0],
                         2020: [95.0, 40.0, 5.0]}, index=["A", "B", "C"])


def test_replay_year_toy():
    loss = replay_year(toy(), 2019, base_year=2020)
    assert loss["A"] == pytest.approx(9.5) and loss["B"] == 0 and loss["C"] == 0


def test_worst_and_sentra_toy():
    worst, year = worst_relative_decline(toy())
    assert worst["B"] == pytest.approx(1 / 3) and year["B"] == 2020
    loss = sentra_serentak(toy(), ["A", "B"], base_year=2020)
    assert loss["A"] == pytest.approx(9.5) and loss["B"] == pytest.approx(40 / 3)


def test_exceedance_and_return_period():
    S = np.arange(1, 101, dtype=float)
    assert exceedance_prob(S, 96) == pytest.approx(0.05)
    assert return_period(0.05) == pytest.approx(20)
    assert math.isinf(return_period(0.0))


def test_classify_level_boundaries():
    assert classify_level(1, 10, 20, 30) == "Normal"
    assert classify_level(10, 10, 20, 30) == "Waspada"
    assert classify_level(20, 10, 20, 30) == "Tinggi"
    assert classify_level(30, 10, 20, 30) == "Ekstrem"


def test_priority_matrix_toy():
    P = toy()
    X, *_ = build_components(P)
    m = priority_matrix(P, X, y_threshold_pct=10, x_threshold_pct=20, small_share_pct=0.1)
    assert m.loc["A", "porsi_X_pct"] == pytest.approx(100 * 10 / 35)
    assert m.loc["C", "kerugian_relatif_pct"] == pytest.approx(25.0)
    assert m.loc["A", "kuadran"] == "Penopang Nasional"
    assert m.loc["B", "kuadran"] == "Sentra Kritis"
    assert m.loc["C", "kuadran"] == "Rentan Lokal"
    m2 = priority_matrix(P, X, y_threshold_pct=10, x_threshold_pct=20, small_share_pct=10)
    assert m2.loc["C", "kuadran"] == "Skala Sangat Kecil"


def test_replay_2019_real(P_real):
    assert replay_year(P_real, 2019).sum() == pytest.approx(4_731_600, rel=2e-3)
