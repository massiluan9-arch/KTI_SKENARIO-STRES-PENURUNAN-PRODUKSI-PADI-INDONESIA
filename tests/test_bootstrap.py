import numpy as np
import pandas as pd
import pytest

from crm import parameter_bootstrap, summarize_band


def test_parameter_bootstrap_shape():
    rng = np.random.default_rng(3)
    df = parameter_bootstrap(17.857, 0.6355, 68_245.79, 7, 125, B=20, M=5_000, rng=rng)
    assert len(df) == 20
    assert {"lambda", "tau", "theta", "VaR95", "TVaR99.9"} <= set(df.columns)
    assert np.isfinite(df.to_numpy()).all()
    assert (df["TVaR95"] >= df["VaR95"]).all()


def test_summarize_band():
    df = pd.DataFrame({"VaR95": np.arange(1, 1001, dtype=float)})
    band = summarize_band(df, ["VaR95"])
    assert band.loc["VaR95", "P2.5"] == pytest.approx(np.percentile(np.arange(1, 1001), 2.5))
    assert band.loc["VaR95", "median"] == pytest.approx(500.5)
