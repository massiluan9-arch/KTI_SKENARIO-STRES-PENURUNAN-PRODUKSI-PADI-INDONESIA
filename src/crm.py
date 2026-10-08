"""Fungsi inti model risiko kolektif: N ~ Poisson, X ~ Weibull, S = X_1 + ... + X_N.

  X_it = max(P_i,t-1 - P_it, 0)    N_t = jumlah provinsi dengan X_it > 0    S_t = sum_i X_it
"""
import math

import numpy as np
import pandas as pd
from scipy import optimize, special

YEARS = list(range(2018, 2026))
LEVELS = (0.90, 0.95, 0.99, 0.999)


def load_production(path, sheet="Produksi"):
    df = pd.read_excel(path, sheet_name=sheet)
    df = df.rename(columns={df.columns[0]: "provinsi"}).set_index("provinsi")
    df.columns = [int(c) for c in df.columns]
    df = df[YEARS].astype(float)
    if len(df) != 34 or df.isna().any().any():
        raise ValueError(f"Data harus 34 provinsi tanpa nilai kosong; didapat {len(df)} baris")
    return df


def build_components(P):
    years = list(P.columns)
    prev = P[years[:-1]].to_numpy()
    cur = P[years[1:]].to_numpy()
    X = pd.DataFrame(np.maximum(prev - cur, 0.0), index=P.index, columns=years[1:])
    N = (X > 0).sum(axis=0).astype(int)
    S = X.sum(axis=0)
    sev = X.to_numpy().ravel()
    return X, N, S, sev[sev > 0]


def fit_poisson(n):
    return float(np.mean(n))


def fit_weibull(x):
    """MLE Weibull (lokasi 0) lewat persamaan profil parameter bentuk."""
    x = np.asarray(x, dtype=float)
    if x.size < 2 or (x <= 0).any():
        raise ValueError("Severitas harus berisi >= 2 nilai positif")
    y = x / x.max()
    ly = np.log(y)

    def g(k):
        w = y ** k
        return (w * ly).sum() / w.sum() - 1.0 / k - ly.mean()

    k = optimize.brentq(g, 0.01, 50.0)
    theta = x.max() * np.mean(y ** k) ** (1.0 / k)
    return float(k), float(theta)


def weibull_mean(tau, theta):
    return float(theta * special.gamma(1.0 + 1.0 / tau))


def simulate_S(M, lam, tau, theta, rng):
    n = rng.poisson(lam, size=M)
    x = theta * rng.weibull(tau, size=int(n.sum()))
    idx = np.repeat(np.arange(M), n)
    return np.bincount(idx, weights=x, minlength=M)


def var_tvar(S, p):
    s = np.sort(np.asarray(S, dtype=float))
    k = math.ceil(round(p * s.size, 9))   # round() mencegah p*M = 95.00000001 menjadi 96
    var = s[k - 1]
    tail = s[s > var]
    tvar = tail.mean() if tail.size else var
    return float(var), float(tvar)


def level_label(p):
    return f"{p * 100:g}"


def risk_measures(S, levels=LEVELS):
    out = {}
    for p in levels:
        var, tvar = var_tvar(S, p)
        out[f"VaR{level_label(p)}"] = var
        out[f"TVaR{level_label(p)}"] = tvar
    return out


QUADRANTS = ("Sentra Kritis", "Penopang Nasional", "Rentan Lokal", "Stabil", "Skala Sangat Kecil")


def _relative_declines(P):
    years = list(P.columns)
    return pd.DataFrame({t: np.maximum(P[t - 1] - P[t], 0.0) / P[t - 1] for t in years[1:]})


def replay_year(P, year, base_year=2025):
    """Penurunan relatif tahun `year` (vs year-1) diterapkan ke produksi `base_year`."""
    rel = np.maximum(P[year - 1] - P[year], 0.0) / P[year - 1]
    return rel * P[base_year]


def worst_relative_decline(P):
    rel = _relative_declines(P)
    return rel.max(axis=1), rel.idxmax(axis=1)


def sentra_serentak(P, provinces, base_year=2025):
    worst, _ = worst_relative_decline(P)
    provinces = list(provinces)
    return worst.loc[provinces] * P.loc[provinces, base_year]


def exceedance_prob(S_sim, s):
    return float(np.mean(np.asarray(S_sim) >= s))


def return_period(prob):
    return math.inf if prob == 0 else 1.0 / prob


def classify_level(s, var90, var95, var99):
    if s >= var99:
        return "Ekstrem"
    if s >= var95:
        return "Tinggi"
    if s >= var90:
        return "Waspada"
    return "Normal"


def priority_matrix(P, X, y_threshold_pct, x_threshold_pct=100 / 34, small_share_pct=0.1):
    """x = porsi total penurunan (%); y = rata-rata kerugian relatif per tahun (% produksi),
    yaitu jumlah % penurunan tahunan dibagi banyaknya tahun (= rata-rata % turun x frekuensi/7)."""
    years = list(X.columns)
    prev = P[[t - 1 for t in years]].to_numpy()
    rel_pct = pd.DataFrame(X.to_numpy() / prev * 100, index=X.index, columns=years)
    x = X.sum(axis=1) / X.to_numpy().sum() * 100
    y = rel_pct.sum(axis=1) / len(years)
    share = P.mean(axis=1) / P.mean(axis=1).sum() * 100

    def quadrant(i):
        hi_x, hi_y = x[i] >= x_threshold_pct, y[i] >= y_threshold_pct
        if hi_x and hi_y:
            return "Sentra Kritis"
        if hi_x:
            return "Penopang Nasional"
        if share[i] < small_share_pct:
            return "Skala Sangat Kecil"
        return "Rentan Lokal" if hi_y else "Stabil"

    out = pd.DataFrame({"porsi_X_pct": x, "kerugian_relatif_pct": y,
                        "jumlah_turun": (X > 0).sum(axis=1), "porsi_produksi_pct": share})
    out["kuadran"] = [quadrant(i) for i in out.index]
    return out.sort_values("porsi_X_pct", ascending=False)


def parameter_bootstrap(lam, tau, theta, n_freq, n_sev, B, M, rng, levels=LEVELS):
    """Parametric bootstrap: data sintetis seukuran data asli -> estimasi ulang -> simulasi S."""
    rows = []
    for _ in range(B):
        lam_b = fit_poisson(rng.poisson(lam, n_freq))
        tau_b, theta_b = fit_weibull(theta * rng.weibull(tau, n_sev))
        row = {"lambda": lam_b, "tau": tau_b, "theta": theta_b}
        row.update(risk_measures(simulate_S(M, lam_b, tau_b, theta_b, rng), levels))
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_band(df, cols):
    return pd.DataFrame({"P2.5": df[cols].quantile(0.025), "median": df[cols].median(),
                         "P97.5": df[cols].quantile(0.975)})
