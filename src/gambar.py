"""Gambar skenario: matriks prioritas dan peta kuadran provinsi."""
import json
import re
from pathlib import Path

import matplotlib
import pandas as pd
from shapely.geometry import shape

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.patches import Polygon as MplPolygon  # noqa: E402

C_MAIN, C_ACC, C_GREY, C_ORANGE = "#2F5D8A", "#C0504D", "#7F7F7F", "#D9822B"
KOMA = mticker.FuncFormatter(lambda v, _: f"{v:g}".replace(".", ","))
WARNA_KUADRAN = {"Sentra Kritis": C_ACC, "Penopang Nasional": C_MAIN, "Rentan Lokal": C_ORANGE,
                 "Stabil": C_GREY, "Skala Sangat Kecil": "#BBBBBB"}
OFFSET_KRITIS = {"Sulawesi Selatan": (10, 14, "right"), "Aceh": (10, 6, "left"), "Banten": (34, -8, "left"),
                 "Kalimantan Selatan": (10, 6, "left")}
OFFSET_PETA = {"Kalimantan Selatan": (-30, -16, "right"), "Sulawesi Selatan": (10, -40, "left"),
               "Aceh": (-12, -20, "right"), "Banten": (0, -16, "center")}
NAMA_KHUSUS_GADM = {"JakartaRaya": "DKI Jakarta", "BangkaBelitung": "Kepulauan Bangka Belitung",
                    "Yogyakarta": "DI Yogyakarta"}


def _finish(fig, path):
    fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_priority_matrix(df, x_thr, y_thr, path):
    """Matriks prioritas; label hanya untuk kuadran Sentra Kritis. Mengembalikan daftar provinsi berlabel."""
    fig, ax = plt.subplots(figsize=(8, 5.6))
    for q in WARNA_KUADRAN:
        sub = df[df["kuadran"] == q]
        if sub.empty:
            continue
        kecil = q == "Skala Sangat Kecil"   # lingkaran kosong agar provinsi berproduksi sangat kecil tetap terlihat
        ax.scatter(sub["porsi_X_pct"], sub["kerugian_relatif_pct"], s=_ukuran(sub["porsi_produksi_pct"]),
                   facecolor="white" if kecil else WARNA_KUADRAN[q], edgecolor="#555555" if kecil else "white",
                   linewidth=1.0 if kecil else 0.6, alpha=1.0 if kecil else 0.85, label=q, zorder=3)
    berlabel = []
    for prov, r in df[df["kuadran"] == "Sentra Kritis"].iterrows():
        dx, dy, ha = OFFSET_KRITIS.get(prov, (7, 4, "left"))
        ax.annotate(prov, (r["porsi_X_pct"], r["kerugian_relatif_pct"]), xytext=(dx, dy),
                    textcoords="offset points", fontsize=10, ha=ha, va="center",
                    arrowprops=dict(arrowstyle="-", lw=0.6, color="#555555", shrinkA=1, shrinkB=4))
        berlabel.append(prov)
    ax.set_xscale("log")
    ax.set_xlim(left=min(0.004, df["porsi_X_pct"].min() * 0.6))
    ax.axvline(x_thr, color="k", ls=":", lw=1)
    ax.axhline(y_thr, color="k", ls=":", lw=1)
    ax.xaxis.set_major_formatter(KOMA)
    ax.yaxis.set_major_formatter(KOMA)
    ax.set_xlabel("Porsi terhadap total penurunan 2019–2025 (%, skala log)", fontsize=11)
    ax.set_ylabel("Rata-rata kerugian relatif per tahun (% produksi)", fontsize=11)
    ax.grid(alpha=0.3, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)
    lg = fig.legend(*ax.get_legend_handles_labels(), loc="lower center", ncol=5, fontsize=9.5, frameon=False,
                    bbox_to_anchor=(0.5, 0.055))
    for h in lg.legend_handles:
        h.set_sizes([45])
    ref = [1, 5, 15]
    tanda = [ax.scatter([], [], s=_ukuran(pd.Series([v])), facecolor="#CCCCCC", edgecolor="#777777") for v in ref]
    fig.legend(tanda, [f"{v}%" for v in ref], loc="lower center", ncol=3, fontsize=9.5, frameon=False,
               bbox_to_anchor=(0.5, -0.01), title="Ukuran lingkaran: porsi produksi nasional", title_fontsize=9.5)
    fig.tight_layout(rect=(0, 0.17, 1, 1))
    _finish(fig, path)
    return berlabel


def _ukuran(porsi):
    return 30 + porsi * 14


def nama_gadm(nama):
    """Nama provinsi GADM 4.1 (mis. 'JawaBarat') -> nama baku naskah ('Jawa Barat')."""
    return NAMA_KHUSUS_GADM.get(nama, re.sub(r"(?<!^)(?=[A-Z])", " ", nama))


def plot_peta_kuadran(df, geojson_path, path):
    """Peta choropleth 34 provinsi menurut kuadran matriks prioritas (label hanya Sentra Kritis)."""
    g = json.loads(Path(geojson_path).read_text(encoding="utf-8"))
    geoms = {nama_gadm(f["properties"]["NAME_1"]): f["geometry"] for f in g["features"]}
    beda = sorted(set(df.index) ^ set(geoms))
    if beda:
        raise ValueError(f"Nama provinsi peta dan data tidak cocok: {beda}")
    fig, ax = plt.subplots(figsize=(10, 4.4))
    for nama, geom in geoms.items():
        q = df.loc[nama, "kuadran"]
        warna = "#E6E6E6" if q == "Skala Sangat Kecil" else WARNA_KUADRAN[q]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            ax.add_patch(MplPolygon(poly[0], closed=True, facecolor=warna, edgecolor="#FFFFFF", linewidth=0.35))
        if q == "Sentra Kritis":
            titik = max((shape(geom).geoms if geom["type"] == "MultiPolygon" else [shape(geom)]),
                        key=lambda s: s.area).representative_point()
            dx, dy, ha = OFFSET_PETA.get(nama, (0, -14, "center"))
            ax.annotate(nama, (titik.x, titik.y), xytext=(dx, dy), textcoords="offset points", ha=ha,
                        fontsize=8.5, arrowprops=dict(arrowstyle="-", lw=0.6, color="#333333"))
    ax.autoscale_view()
    ax.set_aspect("equal")
    ax.axis("off")
    tanda = [Patch(facecolor="#E6E6E6" if q == "Skala Sangat Kecil" else w, edgecolor="#999999", label=q)
             for q, w in WARNA_KUADRAN.items() if q in set(df["kuadran"])]
    ax.legend(handles=tanda, loc="lower left", fontsize=9, frameon=False, title="Kuadran", title_fontsize=9)
    _finish(fig, path)
