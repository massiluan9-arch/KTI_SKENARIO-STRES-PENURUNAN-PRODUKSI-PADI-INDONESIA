"""Estimasi VaR dan TVaR penurunan produksi padi 34 provinsi dengan model risiko kolektif.

Jalankan: python src/analisis.py
Hasil: output/hasil_analisis.xlsx dan gambar di output/gambar/.
Setiap blok "# %%" juga dapat dijalankan sebagai sel.

Notasi:
  P_it : produksi padi provinsi i tahun t (ton GKG), i = 1..34, t = 2018..2025
  X_it : max(P_i,t-1 - P_it, 0), severitas penurunan absolut (ton GKG)
  N_t  : jumlah provinsi dengan P_it < P_i,t-1, t = 2019..2025
  S_t  : sum_i X_it, agregat penurunan produksi tahun t (ton GKG)
  Model: S = X_1 + ... + X_N, X_j iid, independen terhadap N.
"""
# %% Impor dan konfigurasi
import re
import sys
import warnings
from datetime import datetime
from itertools import permutations
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from scipy import optimize, special, stats
from scipy.optimize import brentq

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "produksi_padi.xlsx"
OUTPUT_DIR = ROOT / "output"
FIG_DIR = OUTPUT_DIR / "gambar"
SHEET_NAME = 0
YEARS = list(range(2018, 2026))
N_PROV_TARGET = 34                   # jumlah provinsi setelah harmonisasi
UNIT = "ton GKG"
SOURCE_NOTE = "Sumber: BPS (diolah)"
FIG_DPI = 300

SEED = 20261004                      # seed induk
ALPHA = 0.05                         # taraf signifikansi GOF & uji independensi
B_BOOT = 1000                        # replikasi parametric bootstrap GOF
LEVELS = [0.90, 0.95, 0.99, 0.999]   # tingkat kepercayaan VaR/TVaR
M_GRID = [10_000, 25_000, 50_000, 100_000, 200_000]   # kandidat jumlah skenario
R_PILOT = 100                        # replikasi pilot untuk cek konvergensi
REL_MCE_TOL = 0.01                   # batas MCE relatif (1%) untuk seluruh VaR/TVaR
M_LONG = 1_000_000                   # rantai panjang untuk grafik estimasi berjalan
R_REP = 1000                         # replikasi akhir untuk MCE
R_SENS = 100                         # replikasi untuk analisis sensitivitas


# Total nasional rilis BPS (juta ton GKG); hanya untuk validasi, data tidak diubah
BPS_NATIONAL_TOTAL_JUTA_TON = {
    2018: 59.20, 2019: 54.60, 2020: 54.65, 2021: 54.42,
    2022: 54.75, 2023: 53.98, 2024: 53.14, 2025: 60.21,
}
NATIONAL_TOL_JUTA_TON = 0.01         # selisih maksimum yang ditoleransi (pembulatan)

# Referensi wilayah (34 provinsi, urutan kode BPS)
PROVINSI_34 = [
    "Aceh", "Sumatera Utara", "Sumatera Barat", "Riau", "Jambi",
    "Sumatera Selatan", "Bengkulu", "Lampung", "Kepulauan Bangka Belitung",
    "Kepulauan Riau", "DKI Jakarta", "Jawa Barat", "Jawa Tengah",
    "DI Yogyakarta", "Jawa Timur", "Banten", "Bali", "Nusa Tenggara Barat",
    "Nusa Tenggara Timur", "Kalimantan Barat", "Kalimantan Tengah",
    "Kalimantan Selatan", "Kalimantan Timur", "Kalimantan Utara",
    "Sulawesi Utara", "Sulawesi Tengah", "Sulawesi Selatan",
    "Sulawesi Tenggara", "Gorontalo", "Sulawesi Barat", "Maluku",
    "Maluku Utara", "Papua Barat", "Papua",
]

# Provinsi hasil pemekaran 2022 -> provinsi induk
# (UU 14/2022 Papua Selatan, UU 15/2022 Papua Tengah, UU 16/2022 Papua Pegunungan,
#  UU 29/2022 Papua Barat Daya)
PEMEKARAN_KE_INDUK = {
    "Papua Selatan": "Papua",
    "Papua Tengah": "Papua",
    "Papua Pegunungan": "Papua",
    "Papua Barat Daya": "Papua Barat",
}

# Variasi penulisan nama provinsi -> nama baku
ALIAS_PROVINSI = {
    "nanggroe aceh darussalam": "Aceh",
    "nad": "Aceh",
    "sumut": "Sumatera Utara",
    "sumbar": "Sumatera Barat",
    "sumsel": "Sumatera Selatan",
    "bangka belitung": "Kepulauan Bangka Belitung",
    "kep bangka belitung": "Kepulauan Bangka Belitung",
    "babel": "Kepulauan Bangka Belitung",
    "kep riau": "Kepulauan Riau",
    "kepri": "Kepulauan Riau",
    "dki jakarta": "DKI Jakarta",
    "d k i jakarta": "DKI Jakarta",
    "jakarta": "DKI Jakarta",
    "daerah khusus ibukota jakarta": "DKI Jakarta",
    "daerah khusus jakarta": "DKI Jakarta",
    "di yogyakarta": "DI Yogyakarta",
    "d i yogyakarta": "DI Yogyakarta",
    "daerah istimewa yogyakarta": "DI Yogyakarta",
    "yogyakarta": "DI Yogyakarta",
    "diy": "DI Yogyakarta",
    "jabar": "Jawa Barat",
    "jateng": "Jawa Tengah",
    "jatim": "Jawa Timur",
    "ntb": "Nusa Tenggara Barat",
    "ntt": "Nusa Tenggara Timur",
    "kalbar": "Kalimantan Barat",
    "kalteng": "Kalimantan Tengah",
    "kalsel": "Kalimantan Selatan",
    "kaltim": "Kalimantan Timur",
    "kaltara": "Kalimantan Utara",
    "sulut": "Sulawesi Utara",
    "sulteng": "Sulawesi Tengah",
    "sulsel": "Sulawesi Selatan",
    "sultra": "Sulawesi Tenggara",
    "sulbar": "Sulawesi Barat",
    "malut": "Maluku Utara",
}
# Baris agregat di file sumber: dibuang, dipakai untuk cek silang
BARIS_AGREGAT = {"indonesia", "total", "nasional", "jumlah"}

# Gaya plot
plt.rcParams.update({
    "figure.dpi": 110, "savefig.dpi": FIG_DPI, "font.size": 10,
    "axes.titlesize": 11, "axes.labelsize": 10, "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.3,
    "font.family": "DejaVu Sans",
})
C_MAIN, C_ACC, C_GREY = "#2F5D8A", "#C0504D", "#7F7F7F"

FIG_DIR.mkdir(parents=True, exist_ok=True)
sys.stdout.reconfigure(encoding="utf-8")   # konsol Windows (cp1252) tidak bisa menulis τ, ρ, dll.

VALIDATION_LOG = []


class DataValidationError(Exception):
    """Dilempar bila struktur/isi data tidak memenuhi syarat analisis."""


def log_ok(msg):
    VALIDATION_LOG.append(("OK", msg))
    print(f"[OK]      {msg}")


def log_info(msg):
    VALIDATION_LOG.append(("INFO", msg))
    print(f"[INFO]    {msg}")


def log_warn(msg):
    VALIDATION_LOG.append(("WARNING", msg))
    warnings.warn(msg, stacklevel=2)
    print(f"[WARNING] {msg}")


def fail(msg):
    VALIDATION_LOG.append(("ERROR", msg))
    print(f"[ERROR]   {msg}")
    raise DataValidationError(msg)


def fmt_ton(x, dec=2):
    """Format angka gaya Indonesia: 1.234.567,89"""
    s = f"{x:,.{dec}f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


# %% Muat data
def load_excel(path, sheet=SHEET_NAME):
    raw = pd.read_excel(path, sheet_name=sheet, header=0)
    raw = raw.dropna(how="all").dropna(axis=1, how="all")  # buang baris/kolom kosong total
    log_info(f"File dibaca: {Path(path).name} | sheet={sheet} | dimensi mentah {raw.shape}")
    return raw


raw_df = load_excel(DATA_FILE)


# %% Preprocessing dan validasi
def _norm_key(name):
    """Kunci pencocokan nama: huruf kecil, tanpa tanda baca, spasi tunggal."""
    s = str(name).strip().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


CANON_LOOKUP = {_norm_key(p): p for p in PROVINSI_34 + list(PEMEKARAN_KE_INDUK)}
CANON_LOOKUP.update({_norm_key(k): v for k, v in ALIAS_PROVINSI.items()})
CANON_LOOKUP.update({_norm_key("Prov. " + p): p for p in PROVINSI_34})
CANON_LOOKUP.update({_norm_key("Provinsi " + p): p for p in PROVINSI_34})


def _parse_year(col):
    """Ubah header kolom (2018, 2018.0, '2018', 'Tahun 2018') menjadi int, atau None."""
    m = re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", str(col))
    return int(m.group(0)) if m else None


def to_long(raw):
    """Terima format wide (Provinsi | 2018 | ... | 2025) atau long (Provinsi | Tahun | Produksi)."""
    cols = list(raw.columns)
    prov_col = next((c for c in cols if _norm_key(c) in {"provinsi", "province", "prov", "wilayah"}), None)
    if prov_col is None:
        prov_col = cols[0]
        log_warn(f"Kolom provinsi tidak berlabel jelas; kolom pertama '{prov_col}' dipakai sebagai provinsi.")

    year_cols = {c: _parse_year(c) for c in cols if c != prov_col and _parse_year(c) is not None}
    lower = {_norm_key(c): c for c in cols}
    if year_cols:                                   # format wide
        unrecognized = [c for c in cols if c != prov_col and c not in year_cols]
        if unrecognized:
            log_warn(f"Kolom non-tahun diabaikan: {unrecognized}")
        long = raw[[prov_col] + list(year_cols)].melt(
            id_vars=prov_col, var_name="tahun_raw", value_name="produksi_raw")
        long["tahun"] = long["tahun_raw"].map(year_cols)
        fmt = "wide"
    elif "tahun" in lower and any(k in lower for k in ("produksi", "produksi ton")):
        pcol = lower.get("produksi", lower.get("produksi ton"))
        long = raw[[prov_col, lower["tahun"], pcol]].copy()
        long.columns = [prov_col, "tahun_raw", "produksi_raw"]
        long["tahun"] = long["tahun_raw"].map(_parse_year)
        fmt = "long"
    else:
        fail("Struktur tidak dikenali. Harus wide (Provinsi + kolom tahun) "
             "atau long (Provinsi, Tahun, Produksi).")
    long = long.rename(columns={prov_col: "provinsi_raw"})
    log_ok(f"Format data terdeteksi: {fmt}")
    return long[["provinsi_raw", "tahun", "produksi_raw"]]


def validate_structure(long):
    df = long.copy()

    # (a) Tahun
    years_found = sorted(df["tahun"].dropna().unique().astype(int))
    missing_years = sorted(set(YEARS) - set(years_found))
    extra_years = sorted(set(years_found) - set(YEARS))
    if missing_years:
        fail(f"Tahun tidak lengkap. Tidak ditemukan: {missing_years}")
    if extra_years:
        log_warn(f"Tahun di luar periode {YEARS[0]}-{YEARS[-1]} diabaikan: {extra_years}")
        df = df[df["tahun"].isin(YEARS)]
    log_ok(f"Tahun lengkap: {YEARS[0]}-{YEARS[-1]} ({len(YEARS)} tahun)")

    # (b) Nilai numerik (tanpa mengubah angka sumber)
    df["produksi"] = pd.to_numeric(df["produksi_raw"], errors="coerce")
    bad = df[df["produksi"].isna() & df["produksi_raw"].notna()]
    if len(bad):
        fail("Nilai produksi non-numerik ditemukan:\n" + bad.to_string(index=False))

    # (c) Nama provinsi -> baku
    df["provinsi_raw"] = df["provinsi_raw"].astype(str).str.strip()
    df["key"] = df["provinsi_raw"].map(_norm_key)
    agg_rows = df[df["key"].isin(BARIS_AGREGAT)]
    national_from_file = None
    if len(agg_rows):
        log_warn("Baris agregat (mis. 'Indonesia') ditemukan dan dikeluarkan; dipakai untuk cek silang.")
        national_from_file = agg_rows.groupby("tahun")["produksi"].sum()
        df = df[~df["key"].isin(BARIS_AGREGAT)]
    df["provinsi"] = df["key"].map(CANON_LOOKUP)
    unknown = sorted(df.loc[df["provinsi"].isna(), "provinsi_raw"].unique())
    if unknown:
        fail(f"Nama provinsi tidak dikenali (tambahkan ke ALIAS_PROVINSI bila hanya beda penulisan): {unknown}")
    renamed = (df.loc[df["provinsi_raw"] != df["provinsi"], ["provinsi_raw", "provinsi"]]
               .drop_duplicates())
    if len(renamed):
        log_info("Standardisasi nama provinsi:\n" + renamed.to_string(index=False))
    else:
        log_ok("Seluruh nama provinsi sudah sesuai penamaan baku.")

    # (d) Duplikasi provinsi-tahun
    dup = df[df.duplicated(["provinsi", "tahun"], keep=False)].sort_values(["provinsi", "tahun"])
    if len(dup):
        identical = dup.groupby(["provinsi", "tahun"])["produksi"].nunique(dropna=False).max() == 1
        if identical:
            log_warn("Baris provinsi duplikat dengan nilai identik ditemukan; satu baris dipertahankan:\n"
                     + dup[["provinsi_raw", "tahun", "produksi"]].to_string(index=False))
            df = df.drop_duplicates(["provinsi", "tahun"])
        else:
            fail("Provinsi duplikat dengan nilai BERBEDA ditemukan:\n"
                 + dup[["provinsi_raw", "tahun", "produksi"]].to_string(index=False))
    else:
        log_ok("Tidak ada duplikasi provinsi-tahun.")

    # (e) Kelengkapan provinsi induk & missing value
    present = set(df["provinsi"])
    missing_prov = sorted(set(PROVINSI_34) - present)
    if missing_prov:
        fail(f"Provinsi tidak lengkap. Tidak ditemukan: {missing_prov}")
    core = df[df["provinsi"].isin(PROVINSI_34)]
    na_core = core[core["produksi"].isna()]
    if len(na_core):
        fail("Missing value pada provinsi (34 provinsi acuan) - TIDAK diimputasi, periksa sumber:\n"
             + na_core[["provinsi", "tahun"]].to_string(index=False))
    log_ok(f"Tidak ada missing value pada {len(PROVINSI_34)} provinsi acuan.")

    # (f) Nilai negatif / nol
    if (df["produksi"] < 0).any():
        fail("Nilai produksi negatif ditemukan:\n"
             + df.loc[df["produksi"] < 0, ["provinsi", "tahun", "produksi"]].to_string(index=False))
    zeros = df[df["produksi"] == 0]
    if len(zeros):
        log_warn("Produksi bernilai 0 ditemukan (periksa sumber):\n"
                 + zeros[["provinsi", "tahun"]].to_string(index=False))
    log_ok("Tidak ada nilai produksi negatif.")

    return df[["provinsi_raw", "provinsi", "tahun", "produksi"]], national_from_file


long_raw = to_long(raw_df)
long_valid, national_from_file = validate_structure(long_raw)
print(f"\nJumlah baris valid: {len(long_valid)} | provinsi unik: {long_valid['provinsi'].nunique()}")


def harmonize_regions(df):
    """
    Harmonisasi 38 -> 34 provinsi: produksi provinsi pemekaran 2022 dijumlahkan
    ke provinsi induk. Ini BUKAN imputasi; tidak ada nilai yang diduga.
    Sel kosong provinsi pemekaran (tahun sebelum provinsi tersebut tercatat
    terpisah) berarti produksinya masih tercatat di provinsi induk.
    """
    df = df.copy()
    df["provinsi_34"] = df["provinsi"].replace(PEMEKARAN_KE_INDUK)
    pem = df[df["provinsi"].isin(PEMEKARAN_KE_INDUK)]
    if len(pem) == 0:
        log_ok("Data sudah dalam 34 provinsi (tidak ada baris provinsi pemekaran); "
               "harmonisasi tidak mengubah angka.")
    else:
        contrib = (pem.pivot(index="provinsi", columns="tahun", values="produksi")
                   .reindex(columns=YEARS))   # NaN = belum tercatat terpisah
        log_info("Kontribusi provinsi pemekaran yang digabung ke provinsi induk (ton):\n"
                 + contrib.to_string())
        for (child, parent) in PEMEKARAN_KE_INDUK.items():
            yrs_child = set(pem.loc[(pem["provinsi"] == child) & pem["produksi"].notna(), "tahun"])
            if yrs_child:
                log_info(f"{child} -> {parent}: tercatat terpisah pada tahun {sorted(yrs_child)}")
        log_warn("Pastikan provinsi induk pada tahun tersebut TIDAK sudah memuat produksi "
                 "provinsi pemekaran (hindari double counting).")
    out = (df.groupby(["provinsi_34", "tahun"], as_index=False)["produksi"]
             .sum(min_count=1)
             .rename(columns={"provinsi_34": "provinsi"}))
    return out


def build_P(long34):
    P = (long34.pivot(index="provinsi", columns="tahun", values="produksi")
               .reindex(index=PROVINSI_34, columns=YEARS))
    if P.shape != (N_PROV_TARGET, len(YEARS)):
        fail(f"Dimensi P {P.shape} != ({N_PROV_TARGET}, {len(YEARS)})")
    if P.isna().any().any():
        fail("Missing value setelah harmonisasi:\n" + P[P.isna().any(axis=1)].to_string())
    log_ok(f"Matriks produksi P siap: {P.shape[0]} provinsi x {P.shape[1]} tahun ({UNIT}).")
    return P


long34 = harmonize_regions(long_valid)
P = build_P(long34)

# Cek silang total nasional (tanpa mengubah data)
national_total = P.sum(axis=0)
if national_from_file is not None:
    diff = (national_total - national_from_file.reindex(YEARS)).abs()
    if (diff > 1).any():
        log_warn("Jumlah 34 provinsi berbeda dengan baris agregat di file:\n" + diff.to_string())
    else:
        log_ok("Jumlah 34 provinsi = baris agregat pada file.")
if BPS_NATIONAL_TOTAL_JUTA_TON:
    ref = pd.Series(BPS_NATIONAL_TOTAL_JUTA_TON).reindex(YEARS)
    calc = (national_total / 1e6).round(2)
    gap = (calc - ref).abs()
    if (gap > NATIONAL_TOL_JUTA_TON + 1e-9).any():
        log_warn("Total nasional berbeda dari angka rilis BPS yang dikonfigurasi:\n"
                 + pd.DataFrame({"hitung": calc, "BPS": ref, "selisih": gap}).to_string())
    else:
        log_ok("Total nasional 34 provinsi sesuai angka rilis BPS (juta ton GKG, 2 desimal).")


# %% Pembentukan N, X, S
def build_components(P):
    years_t = YEARS[1:]                                   # 2019..2025
    D = pd.DataFrame({t: P[t - 1] - P[t] for t in years_t})   # D_it = P_i,t-1 - P_it
    X_full = D.clip(lower=0)                              # X_it = max(D_it, 0)
    I = (D > 0).astype(int)                               # indikator penurunan
    ties = int((D == 0).sum().sum())
    if ties:
        log_warn(f"{ties} pasangan provinsi-tahun tanpa perubahan (D_it = 0); tidak dihitung sebagai penurunan.")

    N = I.sum(axis=0).rename("N")                         # N_t
    S = X_full.sum(axis=0).rename("S_ton")                # S_t

    panel = pd.DataFrame({
        "provinsi": np.repeat(P.index.values, len(years_t)),
        "tahun": np.tile(years_t, len(P)),
    })
    panel["P_sebelum_ton"] = [P.loc[p, t - 1] for p, t in zip(panel["provinsi"], panel["tahun"])]
    panel["P_ton"] = [P.loc[p, t] for p, t in zip(panel["provinsi"], panel["tahun"])]
    panel["D_ton"] = panel["P_sebelum_ton"] - panel["P_ton"]
    panel["turun"] = (panel["D_ton"] > 0).astype(int)
    panel["X_ton"] = panel["D_ton"].clip(lower=0)

    sev = (panel.loc[panel["turun"] == 1, ["provinsi", "tahun", "P_sebelum_ton", "P_ton", "X_ton"]]
           .sort_values(["tahun", "provinsi"]).reset_index(drop=True))

    nat = P.sum(axis=0)
    annual = pd.DataFrame({
        "tahun": years_t,
        "N": N.values,
        "S_ton": S.values,
        "rata2_X_ton": [X_full[t][X_full[t] > 0].mean() if N[t] > 0 else np.nan for t in years_t],
        "maks_X_ton": [X_full[t].max() for t in years_t],
        "produksi_nasional_ton": nat[years_t].values,
        "perubahan_nasional_ton": (nat[years_t].values - nat[[t - 1 for t in years_t]].values),
    })

    assert int(N.sum()) == len(sev), "Jumlah N tidak sama dengan banyaknya observasi X > 0"
    assert np.isclose(S.sum(), sev["X_ton"].sum()), "Jumlah S tidak sama dengan jumlah X"
    assert (sev["X_ton"] > 0).all()
    assert annual["N"].between(0, len(P)).all()
    log_ok(f"N_t terbentuk untuk {len(years_t)} tahun ({years_t[0]}-{years_t[-1]}); "
           f"total kejadian penurunan = {len(sev)} (= banyaknya observasi X).")
    return D, X_full, N, S, panel, sev, annual


D, X_full, N, S, panel, sev, annual = build_components(P)


# %% Statistik deskriptif dan plot eksplorasi
def describe_series(x, name, ddof=1):
    x = pd.Series(x, dtype=float).dropna()
    q1, q3 = x.quantile([0.25, 0.75])
    out = {
        "variabel": name, "n": len(x), "rata_rata": x.mean(), "median": x.median(),
        "minimum": x.min(), "Q1": q1, "Q3": q3, "IQR": q3 - q1, "maksimum": x.max(),
        "varians": x.var(ddof=ddof), "simpangan_baku": x.std(ddof=ddof),
        "koef_variasi": x.std(ddof=ddof) / x.mean() if x.mean() != 0 else np.nan,
    }
    if len(x) >= 3:
        out["skewness"] = x.skew()
    if len(x) >= 4:
        out["excess_kurtosis"] = x.kurt()
    return out


# Produksi agregat nasional
nat = P.sum(axis=0)
tab_nasional = pd.DataFrame({
    "tahun": YEARS,
    "produksi_ton": nat.values,
    "produksi_juta_ton": (nat / 1e6).round(2).values,
    "perubahan_ton": nat.diff().values,
    "perubahan_persen": (nat.pct_change() * 100).round(2).values,
})
desc_nasional = pd.DataFrame([describe_series(nat, "Produksi nasional (ton)")])

# Frekuensi N (7 observasi tahunan)
desc_N = describe_series(N, "N (provinsi/tahun)")
mean_N, var_N, n_N = desc_N["rata_rata"], desc_N["varians"], desc_N["n"]
desc_N["indeks_dispersi_var_per_mean"] = var_N / mean_N
# Uji indeks dispersi (eksploratif; daya uji rendah karena n kecil)
chi2_disp = (n_N - 1) * var_N / mean_N
desc_N["stat_chi2_dispersi"] = chi2_disp
desc_N["pvalue_dua_sisi_dispersi"] = 2 * min(stats.chi2.cdf(chi2_disp, n_N - 1),
                                            stats.chi2.sf(chi2_disp, n_N - 1))
# Pembanding momen (bukan fitting): varians yang tersirat bila N ~ Bin(34, p=mean/34)
p_bar = mean_N / N_PROV_TARGET
desc_N["proporsi_rata2_provinsi_turun"] = p_bar
desc_N["varians_tersirat_binomial_m34"] = N_PROV_TARGET * p_bar * (1 - p_bar)
desc_N = pd.DataFrame([desc_N])

# Severitas X (hanya X_it > 0)
x = sev["X_ton"]
desc_X = describe_series(x, "X (ton)")
desc_X.update({
    "P90": x.quantile(0.90), "P95": x.quantile(0.95), "P99": x.quantile(0.99),
    "rasio_mean_median": x.mean() / x.median(),
    "rata2_lnX": np.log(x).mean(), "sd_lnX": np.log(x).std(ddof=1),
    "skewness_lnX": np.log(x).skew(),
    "porsi_10persen_kejadian_terbesar": x.nlargest(int(np.ceil(0.10 * len(x)))).sum() / x.sum(),
})
desc_X = pd.DataFrame([desc_X])

# Agregat S
desc_S = pd.DataFrame([describe_series(S, "S (ton)")])

# Ringkasan per provinsi (heterogenitas skala)
tab_prov = pd.DataFrame({
    "rata2_produksi_ton": P.mean(axis=1),
    "sd_produksi_ton": P.std(axis=1, ddof=1),
    "jumlah_tahun_turun": (D > 0).sum(axis=1),
    "total_X_ton": X_full.sum(axis=1),
    "maks_X_ton": X_full.max(axis=1),
})
tab_prov["cv_produksi"] = tab_prov["sd_produksi_ton"] / tab_prov["rata2_produksi_ton"]
tab_prov["porsi_total_X"] = tab_prov["total_X_ton"] / tab_prov["total_X_ton"].sum()
tab_prov = tab_prov.sort_values("total_X_ton", ascending=False)

# Mean excess function empiris e(u) = E[X - u | X > u]
def mean_excess(x, thresholds):
    x = np.sort(np.asarray(x, float))
    return np.array([(x[x > u] - u).mean() if (x > u).sum() >= 3 else np.nan for u in thresholds])

u_grid = np.quantile(x, np.linspace(0, 0.95, 60))
me_vals = mean_excess(x, u_grid)

pd.set_option("display.float_format", lambda v: f"{v:,.4f}")
print("=== Produksi agregat nasional ===");      print(tab_nasional.to_string(index=False))
print("=== Statistik deskriptif N ===");          print(desc_N.T.to_string(header=False))
print("\n=== Statistik deskriptif X (ton) ===");  print(desc_X.T.to_string(header=False))
print("\n=== Statistik deskriptif S (ton) ===");  print(desc_S.T.to_string(header=False))
print("\n=== 10 provinsi dengan total X terbesar ===")
print(tab_prov.head(10)[["rata2_produksi_ton", "jumlah_tahun_turun", "total_X_ton", "porsi_total_X"]].to_string())


def add_source(fig, text=SOURCE_NOTE):
    fig.text(0.01, 0.005, text, ha="left", va="bottom", fontsize=7.5, color=C_GREY, style="italic")


def save(fig, name):
    path = FIG_DIR / name
    fig.savefig(path, bbox_inches="tight")
    print(f"Tersimpan: {path}")
    plt.close(fig)


juta = mticker.FuncFormatter(lambda v, _: f"{v / 1e6:,.1f}".replace(".", ","))
ribu = mticker.FuncFormatter(lambda v, _: f"{v / 1e3:,.0f}".replace(",", "."))
years_t = YEARS[1:]

# Gambar 01: produksi nasional & perubahan tahunan
fig, ax = plt.subplots(1, 2, figsize=(11, 4))
ax[0].plot(YEARS, nat.values, marker="o", color=C_MAIN)
for t, v in zip(YEARS, nat.values):
    ax[0].annotate(f"{v / 1e6:.2f}".replace(".", ","), (t, v), textcoords="offset points",
                   xytext=(0, 6), ha="center", fontsize=8)
ax[0].yaxis.set_major_formatter(juta)
ax[0].set(title="(a) Produksi padi nasional (34 provinsi)", xlabel="Tahun",
          ylabel="Produksi (juta ton GKG)")
chg = tab_nasional["perubahan_persen"].values[1:]
ax[1].bar(years_t, chg, color=[C_ACC if c < 0 else C_MAIN for c in chg])
for t, c in zip(years_t, chg):
    ax[1].annotate(f"{c:.2f}%".replace(".", ","), (t, c), textcoords="offset points",
                   xytext=(0, 4 if c >= 0 else -11), ha="center", fontsize=8)
ax[1].axhline(0, color="k", lw=0.8)
ax[1].set(title="(b) Perubahan produksi nasional terhadap tahun sebelumnya",
          xlabel="Tahun", ylabel="Perubahan (%)")
fig.suptitle("Produksi Padi Nasional 2018–2025", fontweight="bold")
add_source(fig); fig.tight_layout(rect=(0, 0.03, 1, 1)); save(fig, "01_produksi_nasional.png")

# Gambar 02: frekuensi N_t
fig, ax = plt.subplots(figsize=(7, 4))
bars = ax.bar(years_t, N.values, color=C_MAIN)
ax.bar_label(bars, fontsize=9)
ax.axhline(mean_N, color=C_ACC, ls="--", label=f"Rata-rata = {mean_N:.2f}".replace(".", ","))
ax.axhline(N_PROV_TARGET, color=C_GREY, ls=":", label=f"Batas atas = {N_PROV_TARGET} provinsi")
ax.set(title="Frekuensi N: Jumlah Provinsi yang Mengalami Penurunan Produksi Padi",
       xlabel="Tahun", ylabel="Jumlah provinsi", ylim=(0, N_PROV_TARGET + 3))
ax.legend(loc="upper right", fontsize=8)
add_source(fig); fig.tight_layout(rect=(0, 0.03, 1, 1)); save(fig, "02_frekuensi_N.png")

# Gambar 03: distribusi severitas X (skala asli & log)
fig, ax = plt.subplots(1, 2, figsize=(11, 4))
ax[0].hist(x, bins=25, color=C_MAIN, edgecolor="white")
ax[0].axvline(x.mean(), color=C_ACC, ls="--", label=f"Rata-rata = {fmt_ton(x.mean(), 0)} ton")
ax[0].axvline(x.median(), color="k", ls=":", label=f"Median = {fmt_ton(x.median(), 0)} ton")
ax[0].xaxis.set_major_formatter(ribu)
ax[0].set(title="(a) Histogram X (skala asli)", xlabel="Severitas X (ribu ton GKG)",
          ylabel="Frekuensi (kejadian)")
ax[0].legend(fontsize=8)
bins_log = np.logspace(np.floor(np.log10(x.min())), np.ceil(np.log10(x.max())), 25)
ax[1].hist(x, bins=bins_log, color=C_MAIN, edgecolor="white")
ax[1].set_xscale("log")
ax[1].axvline(x.median(), color="k", ls=":")
ax[1].set(title="(b) Histogram X (sumbu log10)", xlabel="Severitas X (ton GKG, skala log)",
          ylabel="Frekuensi (kejadian)")
fig.suptitle(f"Distribusi Severitas Penurunan Produksi X (n = {len(x)} kejadian, {years_t[0]}–{years_t[-1]})",
             fontweight="bold")
add_source(fig); fig.tight_layout(rect=(0, 0.03, 1, 1)); save(fig, "03_distribusi_X.png")

# Gambar 04: boxplot (log) & ECDF
fig, ax = plt.subplots(1, 2, figsize=(11, 4))
data_by_year = [X_full[t][X_full[t] > 0].values for t in years_t]
ax[0].boxplot(data_by_year, showmeans=True,
              meanprops=dict(marker="D", markerfacecolor=C_ACC, markeredgecolor=C_ACC, markersize=4))
ax[0].set_xticks(range(1, len(years_t) + 1), years_t)
ax[0].set_yscale("log")
ax[0].set(title="(a) Sebaran X per tahun", xlabel="Tahun", ylabel="Severitas X (ton GKG, skala log)")
xs = np.sort(x.values); ecdf = np.arange(1, len(xs) + 1) / len(xs)
ax[1].step(xs, ecdf, where="post", color=C_MAIN)
ax[1].set_xscale("log")
ax[1].set(title="(b) Fungsi distribusi empiris (ECDF) X", xlabel="Severitas X (ton GKG, skala log)",
          ylabel="F̂(x)")
fig.suptitle("Sebaran Severitas X menurut Tahun dan ECDF", fontweight="bold")
add_source(fig); fig.tight_layout(rect=(0, 0.03, 1, 1)); save(fig, "04_boxplot_ecdf_X.png")

# Gambar 05: diagnostik ekor (mean excess, QQ eksponensial, log-log survival)
fig, ax = plt.subplots(1, 3, figsize=(14, 4))
ax[0].plot(u_grid, me_vals, marker=".", color=C_MAIN)
ax[0].xaxis.set_major_formatter(ribu); ax[0].yaxis.set_major_formatter(ribu)
ax[0].set(title="(a) Mean excess plot e(u)", xlabel="Ambang u (ribu ton)", ylabel="e(u) (ribu ton)")
n = len(xs); pp = (np.arange(1, n + 1) - 0.5) / n
q_exp = stats.expon.ppf(pp, scale=x.mean())       # kuantil eksponensial berpusat pada rata-rata (momen)
ax[1].scatter(q_exp, xs, s=10, color=C_MAIN)
lim = max(q_exp.max(), xs.max())
ax[1].plot([0, lim], [0, lim], color=C_ACC, ls="--", lw=1, label="Garis y = x")
ax[1].xaxis.set_major_formatter(ribu); ax[1].yaxis.set_major_formatter(ribu)
ax[1].set(title="(b) QQ plot terhadap eksponensial", xlabel="Kuantil eksponensial (ribu ton)",
          ylabel="Kuantil empiris X (ribu ton)")
ax[1].legend(fontsize=8)
surv = 1 - (np.arange(1, n + 1) - 0.5) / n
ax[2].loglog(xs, surv, marker=".", ls="none", color=C_MAIN)
ax[2].set(title="(c) Log-log plot fungsi survival", xlabel="Severitas X (ton, skala log)",
          ylabel="1 − F̂(x) (skala log)")
fig.suptitle("Diagnostik Ekor Distribusi Severitas X", fontweight="bold")
add_source(fig); fig.tight_layout(rect=(0, 0.03, 1, 1)); save(fig, "05_diagnostik_ekor_X.png")

# Gambar 06: agregat S_t
fig, ax = plt.subplots(figsize=(7, 4))
bars = ax.bar(years_t, S.values, color=C_MAIN)
ax.bar_label(bars, labels=[f"{v / 1e6:.2f}".replace(".", ",") for v in S.values], fontsize=8)
ax.yaxis.set_major_formatter(juta)
ax.set(title="Agregat Penurunan Produksi S per Tahun", xlabel="Tahun", ylabel="S (juta ton GKG)")
add_source(fig); fig.tight_layout(rect=(0, 0.03, 1, 1)); save(fig, "06_agregat_S.png")

# Gambar 07: skala produksi vs severitas (heterogenitas)
fig, ax = plt.subplots(figsize=(7, 4.5))
ax.scatter(sev["P_sebelum_ton"], sev["X_ton"], s=14, color=C_MAIN, alpha=0.8)
ax.set_xscale("log"); ax.set_yscale("log")
rho, p_rho = stats.spearmanr(sev["P_sebelum_ton"], sev["X_ton"])
ax.set(title="Produksi Tahun Sebelumnya vs Severitas X",
       xlabel="Produksi tahun sebelumnya P(i,t−1) (ton GKG, skala log)",
       ylabel="Severitas X (ton GKG, skala log)")
ax.text(0.02, 0.95, f"Spearman ρ = {rho:.3f}".replace(".", ","), transform=ax.transAxes, va="top", fontsize=9)
add_source(fig); fig.tight_layout(rect=(0, 0.03, 1, 1)); save(fig, "07_skala_vs_X.png")
log_info(f"Korelasi Spearman P(t-1) vs X: rho = {rho:.4f} (eksploratif)")

# Gambar 08: heatmap X provinsi x tahun
fig, ax = plt.subplots(figsize=(8, 9))
H = X_full.loc[tab_prov.index]                      # urut menurut total X
im = ax.imshow(np.log10(H.replace(0, np.nan)), aspect="auto", cmap="Blues")
ax.set_xticks(range(len(years_t)), years_t); ax.set_yticks(range(len(H)), H.index, fontsize=7.5)
ax.grid(False)
cb = fig.colorbar(im, ax=ax, shrink=0.6); cb.set_label("log10 X (ton GKG); putih = tidak turun")
ax.set(title="Peta Severitas X Provinsi × Tahun", xlabel="Tahun", ylabel="Provinsi (urut total X)")
add_source(fig); fig.tight_layout(rect=(0, 0.02, 1, 1)); save(fig, "08_heatmap_X.png")

# Gambar 09: hubungan N_t dan rata-rata X_t (eksplorasi awal independensi)
fig, ax = plt.subplots(figsize=(6, 4))
ax.scatter(annual["N"], annual["rata2_X_ton"], color=C_MAIN)
for _, r in annual.iterrows():
    ax.annotate(int(r["tahun"]), (r["N"], r["rata2_X_ton"]), xytext=(4, 3),
                textcoords="offset points", fontsize=8)
ax.yaxis.set_major_formatter(ribu)
ax.set(title="Frekuensi N dan Rata-rata Severitas X per Tahun", xlabel="N (provinsi)",
       ylabel="Rata-rata X (ribu ton GKG)")
add_source(fig); fig.tight_layout(rect=(0, 0.03, 1, 1)); save(fig, "09_N_vs_rata2X.png")

# Gambar final: panel gabungan tanpa judul utama
FIG_RC = {"font.size": 12, "axes.titlesize": 12, "axes.labelsize": 11.5,
          "xtick.labelsize": 10.5, "ytick.labelsize": 10.5, "legend.fontsize": 10}
with plt.rc_context(FIG_RC):
    fig, ax = plt.subplots(1, 2, figsize=(9.5, 3.3))
    ax[0].plot(YEARS, nat.values, marker="o", color=C_MAIN)
    for t, v in zip(YEARS, nat.values):
        ax[0].annotate(f"{v / 1e6:.2f}".replace(".", ","), (t, v), textcoords="offset points",
                       xytext=(0, 6), ha="center", fontsize=9.5)
    ax[0].yaxis.set_major_formatter(juta)
    ax[0].set(title="(a) Produksi padi nasional", xlabel="Tahun", ylabel="Produksi (juta ton GKG)")
    ax[0].set_ylim(nat.min() * 0.97, nat.max() * 1.03)
    bars = ax[1].bar(years_t, N.values, color=C_MAIN)
    ax[1].bar_label(bars, fontsize=9.5)
    ax[1].axhline(mean_N, color=C_ACC, ls="--", label=f"Rata-rata = {mean_N:.2f}".replace(".", ","))
    ax[1].set(title="(b) Frekuensi penurunan N", xlabel="Tahun", ylabel="Jumlah provinsi",
              ylim=(0, N_PROV_TARGET))
    ax[1].legend(fontsize=9.5, loc="upper right")
    fig.tight_layout(); save(fig, "produksi_dan_frekuensi.png")

    fig, ax = plt.subplots(1, 3, figsize=(10.5, 3.4))
    ax[0].hist(x, bins=bins_log, color=C_MAIN, edgecolor="white"); ax[0].set_xscale("log")
    ax[0].axvline(x.median(), color="k", ls=":", label="Median")
    ax[0].axvline(x.mean(), color=C_ACC, ls="--", label="Rata-rata")
    ax[0].legend(fontsize=9.5)
    ax[0].set(title="(a) Histogram X (sumbu log)", xlabel="X (ton GKG)", ylabel="Frekuensi (kejadian)")
    ax[1].plot(u_grid, me_vals, marker=".", color=C_MAIN)
    ax[1].xaxis.set_major_formatter(ribu); ax[1].yaxis.set_major_formatter(ribu)
    ax[1].set(title="(b) Mean excess plot", xlabel="Ambang u (ribu ton)", ylabel="e(u) (ribu ton)")
    ax[2].scatter(q_exp, xs, s=10, color=C_MAIN)
    ax[2].plot([0, lim], [0, lim], color=C_ACC, ls="--", lw=1)
    ax[2].xaxis.set_major_formatter(ribu); ax[2].yaxis.set_major_formatter(ribu)
    ax[2].set(title="(c) QQ plot eksponensial", xlabel="Kuantil eksponensial (ribu ton)",
              ylabel="Kuantil empiris X (ribu ton)")
    fig.tight_layout(); save(fig, "severitas.png")


# %% Kandidat distribusi
# Kandidat ditetapkan dari karakteristik eksplorasi; tidak ada kandidat yang dibuang diam-diam.
cand_reason = []
disp_idx = float(desc_N["indeks_dispersi_var_per_mean"].iloc[0])
cand_reason.append(f"N: indeks dispersi = {disp_idx:.3f}; p dua sisi uji dispersi = "
                   f"{float(desc_N['pvalue_dua_sisi_dispersi'].iloc[0]):.3f} -> Poisson (equi), "
                   f"Binomial Negatif (over), Binomial m={N_PROV_TARGET} (under, batas fisik) diuji.")
cv_x = float(desc_X["koef_variasi"].iloc[0])
cand_reason.append(f"X: CV = {cv_x:.3f} (>1 -> eksponensial tidak memadai); skewness = "
                   f"{float(desc_X['skewness'].iloc[0]):.3f}; skewness ln X = "
                   f"{float(desc_X['skewness_lnX'].iloc[0]):.3f} -> Gamma, Weibull, Lognormal, "
                   f"Log-logistic, Lomax (2 parameter).")
FREQ_CANDIDATES = ["Poisson", "Binomial Negatif", "Binomial"]
SEV_CANDIDATES = ["Gamma", "Weibull", "Lognormal", "Log-logistic", "Lomax"]
SEV_FALLBACK = ["Burr XII"]          # dipakai HANYA jika seluruh kandidat utama ditolak
for r in cand_reason:
    log_info(r)


# %% Estimasi maximum likelihood
def freq_logpmf(name, k, par):
    k = np.asarray(k)
    if name == "Poisson":
        return stats.poisson.logpmf(k, par["lambda"])
    if name == "Binomial":
        return stats.binom.logpmf(k, N_PROV_TARGET, par["p"])
    if name == "Binomial Negatif":
        return stats.nbinom.logpmf(k, par["r"], par["p"])
    raise ValueError(name)


def freq_cdf(name, k, par):
    if name == "Poisson":
        return stats.poisson.cdf(k, par["lambda"])
    if name == "Binomial":
        return stats.binom.cdf(k, N_PROV_TARGET, par["p"])
    if name == "Binomial Negatif":
        return stats.nbinom.cdf(k, par["r"], par["p"])
    raise ValueError(name)


def freq_rvs(name, par, size, rng):
    if name == "Poisson":
        return rng.poisson(par["lambda"], size)
    if name == "Binomial":
        return rng.binomial(N_PROV_TARGET, par["p"], size)
    if name == "Binomial Negatif":
        return rng.negative_binomial(par["r"], par["p"], size)
    raise ValueError(name)


def freq_moments(name, par):
    if name == "Poisson":
        return par["lambda"], par["lambda"]
    if name == "Binomial":
        m, p = N_PROV_TARGET, par["p"]
        return m * p, m * p * (1 - p)
    r, p = par["r"], par["p"]
    return r * (1 - p) / p, r * (1 - p) / p ** 2


def fit_freq(name, k):
    """MLE. NB memakai profil likelihood: untuk r tertentu, p_hat = r / (r + mean)."""
    k = np.asarray(k, float)
    m = k.mean()
    boundary = False
    if name == "Poisson":
        par, npar = {"lambda": m}, 1
    elif name == "Binomial":
        par, npar = {"p": m / N_PROV_TARGET}, 1
    elif name == "Binomial Negatif":
        def nll(logr):
            r = np.exp(logr)
            return -stats.nbinom.logpmf(k, r, r / (r + m)).sum()
        res = optimize.minimize_scalar(nll, bounds=(-6, 18), method="bounded",
                                       options={"xatol": 1e-10})
        r = float(np.exp(res.x))
        boundary = res.x > 17.5            # r -> tak hingga: batas Poisson
        par, npar = {"r": r, "p": r / (r + m)}, 2
    else:
        raise ValueError(name)
    ll = float(freq_logpmf(name, k, par).sum())
    return {"dist": name, "par": par, "k": npar, "loglik": ll, "boundary": bool(boundary)}


# Severitas: numpy murni agar cepat untuk bootstrap
SEV_SPEC = {
    # nama: (nama parameter, fungsi logpdf(x, *par), fungsi cdf(x, *par), fungsi rvs(rng, n, *par))
    "Gamma": (("alpha", "theta"),
              lambda x, a, t: (a - 1) * np.log(x) - x / t - a * np.log(t) - special.gammaln(a),
              lambda x, a, t: special.gammainc(a, x / t),
              lambda g, n, a, t: g.gamma(a, t, n)),
    "Weibull": (("tau", "theta"),
                lambda x, c, t: np.log(c) - np.log(t) + (c - 1) * np.log(x / t) - (x / t) ** c,
                lambda x, c, t: -np.expm1(-(x / t) ** c),
                lambda g, n, c, t: t * g.weibull(c, n)),
    "Lognormal": (("mu", "sigma"),
                  lambda x, mu, s: -np.log(x * s * np.sqrt(2 * np.pi)) - (np.log(x) - mu) ** 2 / (2 * s * s),
                  lambda x, mu, s: special.ndtr((np.log(x) - mu) / s),
                  lambda g, n, mu, s: g.lognormal(mu, s, n)),
    "Log-logistic": (("gamma", "theta"),
                     lambda x, c, t: np.log(c) - np.log(t) + (c - 1) * np.log(x / t) - 2 * np.log1p((x / t) ** c),
                     lambda x, c, t: 1.0 / (1.0 + (x / t) ** (-c)),
                     lambda g, n, c, t: t * (1.0 / g.random(n) - 1.0) ** (-1.0 / c)),
    "Lomax": (("alpha", "theta"),
              lambda x, a, t: np.log(a) - np.log(t) - (a + 1) * np.log1p(x / t),
              lambda x, a, t: -np.expm1(-a * np.log1p(x / t)),
              lambda g, n, a, t: t * np.expm1(-np.log1p(-g.random(n)) / a)),
    "Burr XII": (("c", "k", "theta"),
                 lambda x, c, k, t: (np.log(c) + np.log(k) - np.log(t) + (c - 1) * np.log(x / t)
                                     - (k + 1) * np.log1p((x / t) ** c)),
                 lambda x, c, k, t: -np.expm1(-k * np.log1p((x / t) ** c)),
                 lambda g, n, c, k, t: t * np.expm1(-np.log1p(-g.random(n)) / k) ** (1.0 / c)),
}
SCALE_PARAM = {"Gamma": 1, "Weibull": 1, "Lognormal": None, "Log-logistic": 1, "Lomax": 1, "Burr XII": 2}


def _start(name, y):
    m, v, ly = y.mean(), y.var(), np.log(y)
    if name == "Gamma":
        return [m * m / v, v / m]
    if name == "Weibull":
        return [1.0 / max(ly.std(), 0.3), m]
    if name == "Log-logistic":
        return [np.pi / (np.sqrt(3) * ly.std()), np.exp(np.median(ly))]
    if name == "Lomax":
        return [2.5, 1.5 * m]
    if name == "Burr XII":
        return [1.0, 1.0, m]
    raise ValueError(name)


def fit_sev(name, x, start=None):
    """MLE pada data terskala y = x / s (stabil numerik), lalu parameter skala dikembalikan.
    start: parameter awal (skala asli) -> dipakai sebagai warm start pada bootstrap."""
    x = np.asarray(x, float)
    names, logpdf, _, _ = SEV_SPEC[name]
    if name == "Lognormal":                       # MLE bentuk tertutup
        lx = np.log(x)
        mu, s = lx.mean(), lx.std(ddof=0)
        par = (mu, s)
    else:
        sc = np.median(x)
        y = x / sc

        def nll(lp):
            val = -np.sum(logpdf(y, *np.exp(lp)))
            return val if np.isfinite(val) else 1e300

        if start is not None:
            st = np.array(start, float); st[SCALE_PARAM[name]] /= sc
            trials = (np.log(st),)
        else:
            x0 = np.log(np.maximum(_start(name, y), 1e-6))
            trials = (x0, x0 + 0.5, x0 - 0.5)
        best = None
        for trial in trials:
            r1 = optimize.minimize(nll, trial, method="Nelder-Mead",
                                   options={"xatol": 1e-9, "fatol": 1e-11, "maxiter": 20000})
            r2 = optimize.minimize(nll, r1.x, method="L-BFGS-B")
            r = r2 if r2.fun <= r1.fun else r1
            if best is None or r.fun < best.fun:
                best = r
        p = np.exp(best.x)
        p[SCALE_PARAM[name]] *= sc
        par = tuple(float(v) for v in p)
    ll = float(np.sum(logpdf(x, *par)))
    return {"dist": name, "par": dict(zip(names, par)), "par_tuple": par, "k": len(names), "loglik": ll}


def sev_cdf(name, x, par):
    return SEV_SPEC[name][2](np.asarray(x, float), *par)


def sev_rvs(name, par, n, rng):
    return SEV_SPEC[name][3](rng, n, *par)


def sev_moments(name, par):
    """E[X] dan Var[X] teoretis (inf bila tidak ada)."""
    if name == "Gamma":
        a, t = par; return a * t, a * t * t
    if name == "Weibull":
        c, t = par
        m1 = t * special.gamma(1 + 1 / c); m2 = t * t * special.gamma(1 + 2 / c)
        return m1, m2 - m1 ** 2
    if name == "Lognormal":
        mu, s = par
        return np.exp(mu + s * s / 2), (np.exp(s * s) - 1) * np.exp(2 * mu + s * s)
    if name == "Log-logistic":
        c, t = par
        b = np.pi / c
        m1 = t * b / np.sin(b) if c > 1 else np.inf
        m2 = t * t * 2 * b / np.sin(2 * b) if c > 2 else np.inf
        return m1, (m2 - m1 ** 2) if np.isfinite(m2) else np.inf
    if name == "Lomax":
        a, t = par
        m1 = t / (a - 1) if a > 1 else np.inf
        v = t * t * a / ((a - 1) ** 2 * (a - 2)) if a > 2 else np.inf
        return m1, v
    if name == "Burr XII":
        c, k, t = par
        m1 = t * special.beta(1 + 1 / c, k - 1 / c) * k if c * k > 1 else np.inf
        m2 = t * t * special.beta(1 + 2 / c, k - 2 / c) * k if c * k > 2 else np.inf
        return m1, (m2 - m1 ** 2) if np.isfinite(m2) else np.inf
    raise ValueError(name)


N_obs = annual["N"].to_numpy()
X_obs = sev["X_ton"].to_numpy()
freq_fit = {d: fit_freq(d, N_obs) for d in FREQ_CANDIDATES}
sev_fit = {d: fit_sev(d, X_obs) for d in SEV_CANDIDATES}

# Pemeriksaan silang MLE dengan scipy.stats.fit (hanya validasi, tidak mengubah hasil)
_chk = {"Gamma": stats.gamma, "Weibull": stats.weibull_min, "Log-logistic": stats.fisk, "Lomax": stats.lomax}
for d, dist in _chk.items():
    sp = dist.fit(X_obs, floc=0)
    ll_sp = dist.logpdf(X_obs, *sp).sum()
    if ll_sp > sev_fit[d]["loglik"] + 1e-3:
        log_warn(f"MLE {d}: scipy memberi log-likelihood lebih tinggi ({ll_sp:.4f} > {sev_fit[d]['loglik']:.4f}).")
    else:
        log_ok(f"MLE {d} konsisten dengan scipy.stats.fit (selisih loglik {sev_fit[d]['loglik'] - ll_sp:+.2e}).")
for d in FREQ_CANDIDATES:
    print(d, freq_fit[d]["par"], round(freq_fit[d]["loglik"], 4))
for d in SEV_CANDIDATES:
    print(d, {k: round(v, 6) for k, v in sev_fit[d]["par"].items()}, round(sev_fit[d]["loglik"], 4))


# %% Parametric bootstrap goodness-of-fit
def ks_cvm_stat(name, x, par):
    """Statistik KS dan Cramér–von Mises untuk distribusi kontinu."""
    xs = np.sort(x); n = len(xs)
    u = sev_cdf(name, xs, par)
    i = np.arange(1, n + 1)
    ks = max(np.max(i / n - u), np.max(u - (i - 1) / n))
    cvm = 1 / (12 * n) + np.sum((u - (2 * i - 1) / (2 * n)) ** 2)
    return ks, cvm


def discrete_ks(name, k, par, kmax=None):
    """KS diskret: sup_x |F_n(x) - F(x)| pada titik-titik tumpuan bilangan bulat."""
    k = np.asarray(k)
    if kmax is None:
        kmax = N_PROV_TARGET if name == "Binomial" else max(int(k.max()) * 3, 100)
    grid = np.arange(0, kmax + 1)
    Fn = np.searchsorted(np.sort(k), grid, side="right") / len(k)
    return float(np.max(np.abs(Fn - freq_cdf(name, grid, par))))


def gof_freq(name, k, B, rng):
    fit = freq_fit[name]
    t_obs = discrete_ks(name, k, fit["par"])
    t_b = np.empty(B)
    for b in range(B):
        kb = freq_rvs(name, fit["par"], len(k), rng)
        fb = fit_freq(name, kb)                      # fit ulang di setiap bootstrap
        t_b[b] = discrete_ks(name, kb, fb["par"])
    return {"KS": t_obs, "p_KS": (1 + np.sum(t_b >= t_obs - 1e-12)) / (B + 1)}


def gof_sev(name, x, B, rng, fits):
    fit = fits[name]
    ks0, cvm0 = ks_cvm_stat(name, x, fit["par_tuple"])
    ks_b = np.empty(B); cvm_b = np.empty(B)
    for b in range(B):
        xb = sev_rvs(name, fit["par_tuple"], len(x), rng)
        fb = fit_sev(name, xb, start=fit["par_tuple"])   # fit ulang di setiap bootstrap
        ks_b[b], cvm_b[b] = ks_cvm_stat(name, xb, fb["par_tuple"])
    return {"KS": ks0, "CvM": cvm0,
            "p_KS": (1 + np.sum(ks_b >= ks0)) / (B + 1),
            "p_CvM": (1 + np.sum(cvm_b >= cvm0)) / (B + 1)}


ss_gof = np.random.SeedSequence(SEED).spawn(2)
rng_gof_N = np.random.default_rng(ss_gof[0])
rng_gof_X = np.random.default_rng(ss_gof[1])
t0 = datetime.now()
gof_N = {d: gof_freq(d, N_obs, B_BOOT, rng_gof_N) for d in FREQ_CANDIDATES}
gof_X = {d: gof_sev(d, X_obs, B_BOOT, rng_gof_X, sev_fit) for d in SEV_CANDIDATES}
log_info(f"Bootstrap GOF selesai ({B_BOOT} replikasi per kandidat) dalam {(datetime.now() - t0).seconds} detik.")

# Fallback: hanya bila seluruh kandidat severitas utama ditolak
if all(min(g["p_KS"], g["p_CvM"]) < ALPHA for g in gof_X.values()):
    log_warn("Seluruh kandidat severitas utama ditolak; mencoba distribusi fallback: " + ", ".join(SEV_FALLBACK))
    for d in SEV_FALLBACK:
        sev_fit[d] = fit_sev(d, X_obs)
        gof_X[d] = gof_sev(d, X_obs, B_BOOT, rng_gof_X, sev_fit)
        SEV_CANDIDATES.append(d)


# %% AIC, AICc, BIC dan distribusi final
def info_criteria(ll, k, n):
    aic = 2 * k - 2 * ll
    aicc = aic + (2 * k * (k + 1) / (n - k - 1) if n - k - 1 > 0 else np.inf)
    bic = k * np.log(n) - 2 * ll
    return aic, aicc, bic


rows = []
for d in FREQ_CANDIDATES:
    f = freq_fit[d]; aic, aicc, bic = info_criteria(f["loglik"], f["k"], len(N_obs))
    rows.append({"distribusi": d, **{f"par_{k}": v for k, v in f["par"].items()}, "k": f["k"],
                 "loglik": f["loglik"], "AIC": aic, "AICc": aicc, "BIC": bic,
                 "KS": gof_N[d]["KS"], "p_KS": gof_N[d]["p_KS"], "batas_parameter": f["boundary"]})
tab_fit_N = pd.DataFrame(rows)
tab_fit_N["lolos_GOF"] = tab_fit_N["p_KS"] >= ALPHA

rows = []
for d in SEV_CANDIDATES:
    f = sev_fit[d]; aic, aicc, bic = info_criteria(f["loglik"], f["k"], len(X_obs))
    rows.append({"distribusi": d, "parameter": f["par"], "k": f["k"], "loglik": f["loglik"],
                 "AIC": aic, "AICc": aicc, "BIC": bic, "KS": gof_X[d]["KS"], "p_KS": gof_X[d]["p_KS"],
                 "CvM": gof_X[d]["CvM"], "p_CvM": gof_X[d]["p_CvM"]})
tab_fit_X = pd.DataFrame(rows)
tab_fit_X["lolos_GOF"] = (tab_fit_X["p_KS"] >= ALPHA) & (tab_fit_X["p_CvM"] >= ALPHA)


def choose(tab):
    ok = tab[tab["lolos_GOF"]]
    if ok.empty:
        log_warn("Tidak ada kandidat yang lolos GOF; dipilih AICc terkecil dari seluruh kandidat.")
        ok = tab
    ok = ok.sort_values(["AICc", "BIC"])
    return ok.iloc[0]["distribusi"], (ok.iloc[1]["distribusi"] if len(ok) > 1 else None)


for tab in (tab_fit_N, tab_fit_X):
    tab["dAICc"] = tab["AICc"] - tab.loc[tab["lolos_GOF"], "AICc"].min() if tab["lolos_GOF"].any() \
        else tab["AICc"] - tab["AICc"].min()
    tab["peringkat_AICc"] = tab["AICc"].rank(method="min").astype(int)

FREQ_FINAL, FREQ_RUNNER = choose(tab_fit_N)
SEV_FINAL, SEV_RUNNER = choose(tab_fit_X)
par_N = freq_fit[FREQ_FINAL]["par"]
par_X = sev_fit[SEV_FINAL]["par_tuple"]
log_ok(f"Distribusi final: N ~ {FREQ_FINAL} {par_N}; X ~ {SEV_FINAL} {sev_fit[SEV_FINAL]['par']}")
print(tab_fit_N.round(4).to_string(index=False))
print(tab_fit_X.drop(columns="parameter").round(4).to_string(index=False))


# %% Uji independensi N dan X
# Unit pertukaran adalah tahun: N_t satu nilai per tahun, sedangkan X_it bergerombol di dalam tahun.
# Uji memakai permutasi eksak label N antartahun (7! = 5.040), sehingga struktur gerombol X tetap
# utuh dan p-value tidak bergantung pada asumsi asimtotik.
years_N = annual["tahun"].to_numpy()
N_by_year = dict(zip(years_N, N_obs))
x_year = sev["tahun"].to_numpy()


def kendall_event(nvec):
    m = dict(zip(years_N, nvec))
    return stats.kendalltau(X_obs, np.array([m[t] for t in x_year])).statistic


def spearman_year(nvec):
    med = sev.groupby("tahun")["X_ton"].median().reindex(years_N).to_numpy()
    return stats.spearmanr(nvec, med).statistic


perm_list = np.array(list(permutations(N_obs)))
tau_obs = kendall_event(N_obs)
rho_obs = spearman_year(N_obs)
tau_perm = np.array([kendall_event(p) for p in perm_list])
rho_perm = np.array([spearman_year(p) for p in perm_list])
p_tau = np.mean(np.abs(tau_perm) >= abs(tau_obs) - 1e-12)
p_rho = np.mean(np.abs(rho_perm) >= abs(rho_obs) - 1e-12)
kw = stats.kruskal(*[g["X_ton"].to_numpy() for _, g in sev.groupby("tahun")])
tab_indep = pd.DataFrame([
    {"uji": "Kendall τ-b ($X_{it}$ terhadap $N_t$), permutasi eksak antartahun", "statistik": tau_obs,
     "p_value": p_tau, "n_permutasi": len(perm_list)},
    {"uji": "Spearman ($N_t$ terhadap median $X_{it}$ per tahun), permutasi eksak", "statistik": rho_obs,
     "p_value": p_rho, "n_permutasi": len(perm_list)},
    {"uji": "Kruskal–Wallis (kesamaan sebaran $X$ antartahun)", "statistik": kw.statistic,
     "p_value": kw.pvalue, "n_permutasi": np.nan},
])
tab_indep["keputusan_alpha_0_05"] = np.where(tab_indep["p_value"] < ALPHA, "Tolak H0", "Gagal tolak H0")
print(tab_indep.to_string(index=False))


# %% Model risiko kolektif
EN, VN = freq_moments(FREQ_FINAL, par_N)
EX, VX = sev_moments(SEV_FINAL, par_X)
ES_theory = EN * EX
VS_theory = EN * VX + VN * EX ** 2 if np.isfinite(VX) else np.inf
p_N_gt_34 = 1 - freq_cdf(FREQ_FINAL, N_PROV_TARGET, par_N)
p_N_0 = float(np.exp(freq_logpmf(FREQ_FINAL, 0, par_N)))
log_info(f"E[N]={EN:.4f}, Var[N]={VN:.4f}, E[X]={EX:,.2f}, Var[X]={VX:,.2f}")
log_info(f"E[S] teoretis = {ES_theory:,.2f} ton; SD[S] teoretis = {np.sqrt(VS_theory):,.2f} ton")
log_info(f"P(N > {N_PROV_TARGET}) di bawah model = {p_N_gt_34:.3e}; P(N = 0) = {p_N_0:.3e}")


def simulate_S(M, rng, fN=FREQ_FINAL, pN=None, fX=SEV_FINAL, pX=None):
    """
    Simulasi Monte Carlo LANGSUNG model risiko kolektif untuk M skenario tahunan:
      1) N_j ~ distribusi frekuensi final
      2) bila N_j = 0 maka S_j = 0
      3) X_j1..X_jN_j ~ iid distribusi severitas final (ton), independen dari N_j
      4) S_j = X_j1 + ... + X_jN_j
    Seluruh X dibangkitkan sekaligus lalu dijumlahkan per skenario (np.bincount),
    ekuivalen dengan loop per skenario tetapi jauh lebih cepat.
    """
    pN = par_N if pN is None else pN
    pX = par_X if pX is None else pX
    Nsim = freq_rvs(fN, pN, M, rng)
    total = int(Nsim.sum())
    Xsim = sev_rvs(fX, pX, total, rng)
    idx = np.repeat(np.arange(M), Nsim)
    return np.bincount(idx, weights=Xsim, minlength=M), Nsim


# Uji kebenaran implementasi: momen simulasi besar vs momen teoretis
_S_chk, _N_chk = simulate_S(1_000_000, np.random.default_rng(SEED + 99))
log_info(f"Cek implementasi (M=1.000.000): mean S simulasi = {_S_chk.mean():,.2f} vs teoretis {ES_theory:,.2f} "
         f"(selisih {100 * (_S_chk.mean() / ES_theory - 1):+.3f}%); mean N = {_N_chk.mean():.4f}")
if abs(_S_chk.mean() / ES_theory - 1) > 0.01:
    log_warn("Rata-rata S simulasi menyimpang > 1% dari E[S] teoretis; periksa implementasi.")


# %% Monte Carlo dan cek konvergensi
def var_tvar(S, levels=LEVELS):
    """VaR_p = inf{s : F_M(s) >= p} = S_(ceil(pM)); TVaR_p = E[S | S > VaR_p]."""
    s = np.sort(S); M = len(s)
    out = {}
    for p in levels:
        v = s[int(np.ceil(p * M)) - 1]
        tail = s[s > v]
        out[f"VaR_{p}"] = v
        out[f"TVaR_{p}"] = tail.mean() if len(tail) else v
    return out


MEASURES = [f"VaR_{p}" for p in LEVELS] + [f"TVaR_{p}" for p in LEVELS]
conv_rows = []
ss_conv = np.random.SeedSequence(SEED + 1)
for M in M_GRID:
    rngs = [np.random.default_rng(s) for s in ss_conv.spawn(R_PILOT)]
    est = pd.DataFrame([var_tvar(simulate_S(M, g)[0]) for g in rngs])
    rel = (est.std(ddof=1) / est.mean())
    conv_rows.append({"M": M, **{f"relMCE_{k}": rel[k] for k in MEASURES}, "maks_relMCE": rel.max()})
    print(f"M={M:>7}: maks MCE relatif = {100 * rel.max():.3f}%")
tab_conv = pd.DataFrame(conv_rows)
ok_M = tab_conv[tab_conv["maks_relMCE"] <= REL_MCE_TOL]
M_FINAL = int(ok_M["M"].min()) if len(ok_M) else int(tab_conv["M"].max())
if not len(ok_M):
    log_warn(f"Tidak ada M pada grid dengan MCE relatif <= {REL_MCE_TOL:.1%}; dipakai M terbesar.")
log_ok(f"Jumlah skenario per simulasi dipilih M = {M_FINAL:,} (aturan: MCE relatif seluruh VaR/TVaR "
       f"<= {REL_MCE_TOL:.1%} pada {R_PILOT} replikasi pilot).")

# Satu rantai panjang untuk grafik estimasi berjalan
S_long, _ = simulate_S(M_LONG, np.random.default_rng(SEED + 2))
checkpoints = np.unique(np.round(np.logspace(3, np.log10(M_LONG), 40)).astype(int))
running = pd.DataFrame([{"M": m, **var_tvar(S_long[:m])} for m in checkpoints])


# %% VaR dan TVaR (satu simulasi utama)
S_main, N_main = simulate_S(M_FINAL, np.random.default_rng(SEED + 3))
main_est = var_tvar(S_main)
for k in MEASURES:
    print(f"{k:<11} = {main_est[k]:>16,.2f} ton")


# %% Replikasi simulasi
t0 = datetime.now()
rep_rows = []
ss_rep = np.random.SeedSequence(SEED + 4)
S_OBS_MAX = float(annual["S_ton"].max())            # agregat teramati terbesar (tahun 2019)
for r, s in enumerate(ss_rep.spawn(R_REP)):
    S_r, N_r = simulate_S(M_FINAL, np.random.default_rng(s))
    rep_rows.append({"replikasi": r + 1, **var_tvar(S_r), "mean_S": S_r.mean(), "median_S": np.median(S_r),
                     "sd_S": S_r.std(ddof=1), "P_S_0": np.mean(S_r == 0),
                     "P_S_ge_maks_obs": np.mean(S_r >= S_OBS_MAX), "maks_N": N_r.max(),
                     "P_N_gt_34": np.mean(N_r > N_PROV_TARGET)})
reps = pd.DataFrame(rep_rows)
log_info(f"{R_REP} replikasi x {M_FINAL:,} skenario selesai dalam {(datetime.now() - t0).seconds} detik.")


# %% Monte Carlo Error dan interval ketidakpastian Monte Carlo
def summarize(col):
    v = reps[col]
    return {"ukuran": col, "rata_rata": v.mean(), "median": v.median(), "MCE": v.std(ddof=1),
            "MCE_relatif_persen": 100 * v.std(ddof=1) / v.mean() if v.mean() != 0 else np.nan,
            "P2_5": v.quantile(0.025), "P97_5": v.quantile(0.975)}


tab_risk = pd.DataFrame([summarize(c) for c in MEASURES])
tab_S_sim = pd.DataFrame([summarize(c) for c in ["mean_S", "median_S", "sd_S", "P_S_0", "P_S_ge_maks_obs"]])
print(tab_risk.round(2).to_string(index=False))
print(tab_S_sim.to_string(index=False))

# Sensitivitas: distribusi peringkat kedua menurut AICc
sens_rows = []
combos = [("Model final", FREQ_FINAL, SEV_FINAL)]
if SEV_RUNNER:
    combos.append(("Severitas peringkat 2", FREQ_FINAL, SEV_RUNNER))
if FREQ_RUNNER:
    combos.append(("Frekuensi peringkat 2", FREQ_RUNNER, SEV_FINAL))
ss_sens = np.random.SeedSequence(SEED + 5)
for (lab, fN, fX), s in zip(combos, ss_sens.spawn(len(combos))):
    rngs = [np.random.default_rng(q) for q in s.spawn(R_SENS)]
    est = pd.DataFrame([var_tvar(simulate_S(M_FINAL, g, fN, freq_fit[fN]["par"], fX,
                                            sev_fit[fX]["par_tuple"])[0]) for g in rngs]).mean()
    sens_rows.append({"skenario": lab, "frekuensi": fN, "severitas": fX, **est.to_dict()})
tab_sens = pd.DataFrame(sens_rows)
print(tab_sens.round(0).to_string(index=False))


# %% Gambar final
LV = {0.90: "90%", 0.95: "95%", 0.99: "99%", 0.999: "99,9%"}

with plt.rc_context(FIG_RC):
    # Gambar kesesuaian distribusi N dan X
    fig, ax = plt.subplots(1, 3, figsize=(11, 3.5))
    ks_grid = np.arange(0, N_PROV_TARGET + 1)
    Fn = np.searchsorted(np.sort(N_obs), ks_grid, side="right") / len(N_obs)
    ax[0].step(ks_grid, Fn, where="post", color="k", lw=1.6, label="Empiris")
    for d, ls in zip(FREQ_CANDIDATES, ["-", "--", ":"]):
        ax[0].step(ks_grid, freq_cdf(d, ks_grid, freq_fit[d]["par"]), where="post", ls=ls, label=d)
    ax[0].set(title="(a) CDF frekuensi N", xlabel="N (provinsi)", ylabel="F(n)", xlim=(5, 32))
    ax[0].legend(fontsize=8.5)
    xg = np.logspace(np.log10(X_obs.min() * 0.8), np.log10(X_obs.max() * 1.2), 300)
    xs_ = np.sort(X_obs); ec = np.arange(1, len(xs_) + 1) / len(xs_)
    ax[1].step(xs_, ec, where="post", color="k", lw=1.6, label="Empiris")
    for d in SEV_CANDIDATES:
        ax[1].plot(xg, sev_cdf(d, xg, sev_fit[d]["par_tuple"]), lw=1.1, label=d)
    ax[1].set_xscale("log")
    ax[1].set(title="(b) CDF severitas X", xlabel="X (ton GKG, skala log)", ylabel="F(x)")
    ax[1].legend(fontsize=8)
    pp_ = (np.arange(1, len(xs_) + 1) - 0.5) / len(xs_)

    def sev_ppf(d, q, par):
        return np.array([brentq(lambda z: sev_cdf(d, z, par) - qq, 1e-9, 1e9) for qq in q])
    qx = sev_ppf(SEV_FINAL, pp_, par_X)
    ax[2].scatter(qx, xs_, s=10, color=C_MAIN)
    lim2 = [min(qx.min(), xs_.min()) * 0.8, max(qx.max(), xs_.max()) * 1.2]
    ax[2].plot(lim2, lim2, color=C_ACC, ls="--", lw=1)
    ax[2].set_xscale("log"); ax[2].set_yscale("log")
    ax[2].set(title=f"(c) QQ plot {SEV_FINAL}", xlabel="Kuantil teoretis (ton)", ylabel="Kuantil empiris (ton)")
    fig.tight_layout(); save(fig, "kecocokan_distribusi.png")

    # Gambar konvergensi
    fig, ax = plt.subplots(1, 2, figsize=(10.5, 3.6))
    for p, c in zip([0.95, 0.99, 0.999], [C_MAIN, "#4F9D69", C_ACC]):
        ax[0].plot(running["M"], running[f"VaR_{p}"] / 1e6, color=c, label=f"VaR {LV[p]}")
        ax[0].plot(running["M"], running[f"TVaR_{p}"] / 1e6, color=c, ls="--", label=f"TVaR {LV[p]}")
    ax[0].axvline(M_FINAL, color=C_GREY, ls=":", lw=1)
    ax[0].set_xscale("log")
    ax[0].set(title="(a) Estimasi berjalan satu rantai simulasi", xlabel="Jumlah skenario M (skala log)",
              ylabel="Juta ton GKG")
    ax[0].legend(fontsize=8, ncol=2)
    for m, c, ls in [("VaR_0.99", "#4F9D69", "-"), ("TVaR_0.99", "#4F9D69", "--"),
                     ("VaR_0.999", C_ACC, "-"), ("TVaR_0.999", C_ACC, "--")]:
        ax[1].plot(tab_conv["M"], 100 * tab_conv[f"relMCE_{m}"], marker="o", color=c, ls=ls,
                   label=m.replace("_0.999", " 99,9%").replace("_0.99", " 99%"))
    ax[1].axhline(100 * REL_MCE_TOL, color=C_GREY, ls=":", lw=1)
    ax[1].set_xscale("log")
    ax[1].set(title=f"(b) MCE relatif ({R_PILOT} replikasi pilot)", xlabel="Jumlah skenario M (skala log)",
              ylabel="MCE relatif (%)")
    ax[1].legend(fontsize=8)
    fig.tight_layout(); save(fig, "konvergensi.png")

    # Gambar distribusi S hasil simulasi
    fig, ax = plt.subplots(1, 2, figsize=(10.5, 3.6))
    ax[0].hist(S_main / 1e6, bins=120, color=C_MAIN, alpha=0.85, density=True)
    for p, c in zip([0.95, 0.99, 0.999], ["#4F9D69", "#E0A33A", C_ACC]):
        ax[0].axvline(tab_risk.set_index("ukuran").loc[f"VaR_{p}", "rata_rata"] / 1e6, color=c, lw=1.2,
                      label=f"VaR {LV[p]}")
    ax[0].plot(annual["S_ton"] / 1e6, np.zeros(len(annual)), "k|", ms=14, mew=1.5, label="$S_t$ teramati")
    ax[0].set(title="(a) Distribusi agregat S (satu simulasi)", xlabel="S (juta ton GKG)", ylabel="Densitas")
    ax[0].legend(fontsize=8)
    xl = np.arange(len(LEVELS))
    for kind, c, mk in [("VaR", C_MAIN, "o"), ("TVaR", C_ACC, "s")]:
        r_ = tab_risk.set_index("ukuran").loc[[f"{kind}_{p}" for p in LEVELS]]
        ax[1].errorbar(xl, r_["rata_rata"] / 1e6,
                       yerr=[(r_["rata_rata"] - r_["P2_5"]) / 1e6, (r_["P97_5"] - r_["rata_rata"]) / 1e6],
                       color=c, marker=mk, capsize=4, label=f"{kind} (rata-rata, P2,5–P97,5)")
    ax[1].axhline(S_OBS_MAX / 1e6, color="k", ls=":", lw=1, label="$S_t$ teramati terbesar")
    ax[1].set_xticks(xl, [LV[p] for p in LEVELS])
    ax[1].set(title=f"(b) VaR dan TVaR dari {R_REP:,} replikasi".replace(",", "."),
              xlabel="Tingkat kepercayaan", ylabel="Juta ton GKG")
    ax[1].legend(fontsize=8)
    fig.tight_layout(); save(fig, "distribusi_agregat.png")


# %% Simpan hasil
def export_all():
    P_long = (P.reset_index().melt(id_vars="provinsi", var_name="tahun", value_name="produksi_ton")
                .sort_values(["provinsi", "tahun"]))
    sheets = {
        "01_produksi_34prov_2018_2025_wide": P.reset_index(),
        "01_produksi_34prov_2018_2025_long": P_long,
        "02_panel_perubahan_produksi": panel,
        "03_frekuensi_N_agregat_S": annual,
        "04_severitas_X": sev,
        "05_produksi_nasional": tab_nasional,
        "06_fitting_N": tab_fit_N,
        "07_fitting_X": tab_fit_X.assign(parameter=tab_fit_X["parameter"].astype(str)),
        "08_uji_independensi": tab_indep,
        "09_konvergensi_M": tab_conv,
        "10_estimasi_berjalan": running,
        "11_replikasi_VaR_TVaR": reps,
        "12_ringkasan_VaR_TVaR_MCE": tab_risk,
        "13_ringkasan_S_simulasi": tab_S_sim,
        "14_sensitivitas": tab_sens,
        "15_ringkasan_provinsi": tab_prov.reset_index(),
    }
    with pd.ExcelWriter(OUTPUT_DIR / "hasil_analisis.xlsx", engine="openpyxl") as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name[:31], index=False)
        pd.concat([desc_nasional, desc_N, desc_X, desc_S], ignore_index=True).T \
          .to_excel(w, sheet_name="statistik_deskriptif", header=False)
        tab_prov.reset_index().to_excel(w, sheet_name="ringkasan_provinsi", index=False)
        pd.DataFrame(VALIDATION_LOG, columns=["status", "pesan"]).to_excel(w, sheet_name="log", index=False)
    print(f"\nHasil tersimpan di '{OUTPUT_DIR}'.")


export_all()
n_warn = sum(1 for s_, _ in VALIDATION_LOG if s_ == "WARNING")
print(f"Selesai. Peringatan: {n_warn}. N ~ {FREQ_FINAL}, X ~ {SEV_FINAL}, M = {M_FINAL:,}, R = {R_REP:,}.")
