"""Skenario stres, matriks prioritas provinsi, pita ketidakpastian parameter, dan uji balik level risiko.

Jalankan: python src/skenario.py
Hasil: output/skenario.xlsx dan dua gambar di output/gambar/.
Skrip berhenti bila estimasi ulang tidak cocok dengan hasil analisis.py.
"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import crm
import gambar

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "produksi_padi.xlsx"
PETA = ROOT / "data" / "provinsi_34.geojson"
OUT = ROOT / "output"
FIG = OUT / "gambar"

SEED = 20261004
BASE_YEAR = 2025
SENTRA = ["Sulawesi Selatan", "Jawa Tengah", "Jawa Timur", "Jawa Barat"]
LABELS = ("90", "95", "99", "99.9")

# Hasil analisis.py: parameter final dan rata-rata VaR/TVaR dari 1.000 replikasi x 200.000 skenario
HASIL_UTAMA = {"lambda": 17.8571, "tau": 0.6355, "theta": 68245.7866,
               "VaR90": 2741688.36, "TVaR90": 3302394.69, "VaR95": 3145443.06, "TVaR95": 3682105.01,
               "VaR99": 4011432.18, "TVaR99": 4517708.13, "VaR99.9": 5169799.50, "TVaR99.9": 5661776.56}
# BPS: produksi beras 34,69 juta ton dari 60,21 juta ton GKG pada 2025
RASIO_BERAS_GKG = 34.69 / 60.21

B_PARAM, M_PARAM, M_EXCEED, M_CHECK, R_CHECK = 1000, 50_000, 1_000_000, 200_000, 5


def jt(v, d=2):
    """Juta ton dengan format Indonesia (koma desimal)."""
    s = f"{v / 1e6:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def cek_replikasi(lam, tau, theta, rng):
    masalah = []
    for k, v in (("lambda", lam), ("tau", tau), ("theta", theta)):
        if not math.isclose(v, HASIL_UTAMA[k], rel_tol=1e-3):
            masalah.append(f"{k}: {v:.4f} vs {HASIL_UTAMA[k]}")
    sims = [crm.risk_measures(crm.simulate_S(M_CHECK, lam, tau, theta, rng)) for _ in range(R_CHECK)]
    rata = {k: float(np.mean([s[k] for s in sims])) for k in ("VaR95", "TVaR95", "VaR99", "TVaR99")}
    for k, v in rata.items():
        if abs(v / HASIL_UTAMA[k] - 1) > 0.005:
            masalah.append(f"{k}: {v:,.0f} vs {HASIL_UTAMA[k]:,.0f}")
    if masalah:
        sys.exit("Replikasi gagal, analisis dihentikan:\n  " + "\n  ".join(masalah))


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    P = crm.load_production(DATA)
    X, N, S, sev = crm.build_components(P)
    lam = crm.fit_poisson(N.to_numpy())
    tau, theta = crm.fit_weibull(sev)
    cek_replikasi(lam, tau, theta, rng)
    E_S = lam * crm.weibull_mean(tau, theta)
    prod_base = float(P[BASE_YEAR].sum())
    var = {l: HASIL_UTAMA[f"VaR{l}"] for l in LABELS}
    S_big = crm.simulate_S(M_EXCEED, lam, tau, theta, rng)

    # Skenario stres
    skenario = [(f"Replay {t}", crm.replay_year(P, t, BASE_YEAR)) for t in range(2019, 2025)]
    skenario.append(("Empat sentra serentak", crm.sentra_serentak(P, SENTRA, BASE_YEAR)))
    stres = []
    for nama, loss in skenario:
        s = float(loss.sum())
        p = crm.exceedance_prob(S_big, s)
        stres.append({"skenario": nama, "S_ton": s, "S_juta": jt(s), "persen_produksi_2025": s / prod_base * 100,
                      "peluang_lampaui": p, "periode_ulang_tahun": crm.return_period(p),
                      "level": crm.classify_level(s, var["90"], var["95"], var["99"]),
                      "kontributor_utama": ", ".join(loss.sort_values(ascending=False).head(4).index)})
    tab_stres = pd.DataFrame(stres)
    worst, worst_year = crm.worst_relative_decline(P)
    tab_sentra = pd.DataFrame({"penurunan_terburuk_pct": worst[SENTRA] * 100, "tahun": worst_year[SENTRA],
                               "rugi_basis_2025_ton": crm.sentra_serentak(P, SENTRA, BASE_YEAR)})

    # Matriks prioritas
    y_thr = E_S / float(P.sum(axis=0).mean()) * 100
    matriks = crm.priority_matrix(P, X, y_thr)
    gambar.plot_priority_matrix(matriks, 100 / 34, y_thr, FIG / "matriks_prioritas.png")
    gambar.plot_peta_kuadran(matriks, PETA, FIG / "peta_kuadran.png")

    # Pita ketidakpastian parameter
    boot = crm.parameter_bootstrap(lam, tau, theta, len(N), len(sev), B_PARAM, M_PARAM, rng)
    kolom = [f"{k}{l}" for l in LABELS for k in ("VaR", "TVaR")]
    pita = crm.summarize_band(boot, kolom)

    # Terjemahan ke periode ulang, % produksi, dan setara beras
    terjemahan = []
    for l, p in zip(LABELS, crm.LEVELS):
        v, tv = HASIL_UTAMA[f"VaR{l}"], HASIL_UTAMA[f"TVaR{l}"]
        terjemahan.append({"tingkat": l, "VaR": v, "TVaR": tv, "periode_ulang": 1 / (1 - p),
                           "VaR_persen_produksi": v / prod_base * 100, "TVaR_persen_produksi": tv / prod_base * 100,
                           "VaR_beras": v * RASIO_BERAS_GKG, "TVaR_beras": tv * RASIO_BERAS_GKG})

    # Uji balik level risiko pada S teramati
    backtest = {int(t): crm.classify_level(float(s), var["90"], var["95"], var["99"]) for t, s in S.items()}

    with pd.ExcelWriter(OUT / "skenario.xlsx", engine="openpyxl") as w:
        tab_stres.to_excel(w, sheet_name="stres", index=False)
        tab_sentra.to_excel(w, sheet_name="stres_sentra")
        matriks.to_excel(w, sheet_name="matriks_prioritas")
        pita.to_excel(w, sheet_name="pita_parameter")
        pd.DataFrame(terjemahan).to_excel(w, sheet_name="terjemahan", index=False)
        pd.Series(backtest, name="level").to_excel(w, sheet_name="uji_balik")

    print(tab_stres[["skenario", "S_juta", "periode_ulang_tahun", "level"]].to_string(index=False))
    print(matriks["kuadran"].value_counts().to_string())
    print(pita.apply(lambda c: c.map(jt)).to_string())


if __name__ == "__main__":
    main()
