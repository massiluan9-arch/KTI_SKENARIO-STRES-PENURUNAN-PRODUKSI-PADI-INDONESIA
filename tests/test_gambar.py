import json

import pandas as pd
import pytest

import gambar as gt


def _df():
    return pd.DataFrame({"porsi_X_pct": [14.8, 12.0, 0.6, 0.01], "kerugian_relatif_pct": [4.6, 2.2, 5.0, 15.5],
                         "jumlah_turun": [4, 4, 3, 4], "porsi_produksi_pct": [9.3, 17.6, 0.4, 0.001],
                         "kuadran": ["Sentra Kritis", "Penopang Nasional", "Rentan Lokal", "Skala Sangat Kecil"]},
                        index=["Sulawesi Selatan", "Jawa Timur", "Maluku", "Kepulauan Riau"])


def test_nama_gadm():
    assert gt.nama_gadm("JawaBarat") == "Jawa Barat"
    assert gt.nama_gadm("KepulauanRiau") == "Kepulauan Riau"
    assert gt.nama_gadm("JakartaRaya") == "DKI Jakarta"
    assert gt.nama_gadm("BangkaBelitung") == "Kepulauan Bangka Belitung"
    assert gt.nama_gadm("Yogyakarta") == "DI Yogyakarta"


def test_matriks_hanya_label_sentra_kritis(tmp_path):
    berlabel = gt.plot_priority_matrix(_df(), 2.94, 3.07, tmp_path / "m.png")
    assert berlabel == ["Sulawesi Selatan"]


def _geojson(tmp_path, names):
    feats = [{"type": "Feature", "properties": {"NAME_1": n},
              "geometry": {"type": "MultiPolygon", "coordinates": [[[[i, 0], [i + 1, 0], [i + 1, 1], [i, 1], [i, 0]]]]}}
             for i, n in enumerate(names)]
    p = tmp_path / "g.geojson"
    p.write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")
    return p


def test_peta_kuadran(tmp_path):
    gj = _geojson(tmp_path, ["SulawesiSelatan", "JawaTimur", "Maluku", "KepulauanRiau"])
    out = tmp_path / "peta.png"
    gt.plot_peta_kuadran(_df(), gj, out)
    assert out.exists() and out.stat().st_size > 10_000


def test_peta_kuadran_nama_tidak_cocok(tmp_path):
    gj = _geojson(tmp_path, ["SulawesiSelatan", "Atlantis"])
    with pytest.raises(ValueError):
        gt.plot_peta_kuadran(_df(), gj, tmp_path / "x.png")
