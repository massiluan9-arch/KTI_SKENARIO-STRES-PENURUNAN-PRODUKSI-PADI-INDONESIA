import numpy as np
import pandas as pd
import pytest

from crm import (build_components, fit_poisson, fit_weibull, level_label,
                          risk_measures, simulate_S, var_tvar, weibull_mean)


def toy():
    return pd.DataFrame({2018: [100.0, 50.0, 10.0], 2019: [90.0, 60.0, 10.0],
                         2020: [95.0, 40.0, 5.0]}, index=["A", "B", "C"])


def test_build_components_toy():
    X, N, S, sev = build_components(toy())
    assert X.loc["A", 2019] == 10 and X.loc["B", 2019] == 0 and X.loc["C", 2019] == 0
    assert X.loc["A", 2020] == 0 and X.loc["B", 2020] == 20 and X.loc["C", 2020] == 5
    assert list(N) == [1, 2]
    assert list(S) == [10, 25]
    assert sorted(sev) == [5, 10, 20]


def test_var_tvar_order_statistic():
    S = np.arange(1, 101, dtype=float)
    var, tvar = var_tvar(S, 0.95)
    assert var == 95 and tvar == pytest.approx(98.0)
    var, tvar = var_tvar(S, 0.999)
    assert var == 100 and tvar == 100


def test_level_label():
    assert [level_label(p) for p in (0.90, 0.95, 0.99, 0.999)] == ["90", "95", "99", "99.9"]


def test_risk_measures_keys():
    out = risk_measures(np.arange(1, 1001, dtype=float))
    assert set(out) == {f"{k}{l}" for k in ("VaR", "TVaR") for l in ("90", "95", "99", "99.9")}


def test_fit_weibull_recovers_parameters():
    rng = np.random.default_rng(1)
    tau, theta = fit_weibull(68_000 * rng.weibull(0.64, 200_000))
    assert tau == pytest.approx(0.64, rel=0.01)
    assert theta == pytest.approx(68_000, rel=0.02)


def test_fit_weibull_rejects_nonpositive():
    with pytest.raises(ValueError):
        fit_weibull([1.0, 0.0, 3.0])


def test_simulate_S_mean_matches_theory():
    rng = np.random.default_rng(2)
    S = simulate_S(400_000, 17.857, 0.6355, 68_245.79, rng)
    assert S.mean() == pytest.approx(17.857 * weibull_mean(0.6355, 68_245.79), rel=0.01)
    assert (S >= 0).all()


def test_replikasi_naskah(P_real):
    X, N, S, sev = build_components(P_real)
    assert len(sev) == 125
    assert list(N) == [26, 18, 20, 17, 18, 16, 10]
    assert S[2019] == pytest.approx(4_706_564.48, abs=1.0)
    assert fit_poisson(N.to_numpy()) == pytest.approx(17.8571, abs=1e-4)
    tau, theta = fit_weibull(sev)
    assert tau == pytest.approx(0.6355, abs=5e-4)
    assert theta == pytest.approx(68_245.7866, rel=1e-3)
