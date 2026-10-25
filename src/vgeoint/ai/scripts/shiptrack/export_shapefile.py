"""Export detections + tracks to ESRI Shapefiles (WGS84, EPSG:4326).

  ships_points.shp   one point per ship per date, with orientation / heading fields
  ships_boxes.shp    oriented hull boxes (polygons) from the detector
  tracks_lines.shp   same ship across dates (ships seen on >= 2 dates)

DBF field names are limited to 10 characters, see FIELDS below for their meaning.
"""
import argparse
import json
import os

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point, Polygon

FIELDS = """\
ships_points / ships_boxes
  track     ma tau sau khi ghep giua cac ngay (cung so = cung mot tau)
  date      ngay chup (YYYY-MM-DD)
  time_utc  gio chup (UTC)
  scene     ma canh PlanetScope
  conf      do tin cay cua mo hinh (0-1)
  lon, lat  toa do tam tau (WGS84)
  utm_e, utm_n  toa do tam tau (UTM 50N, m)
  length_m, width_m  kich thuoc tau uoc luong tu khung xoay (m)
  axis_deg  huong truc than tau, 0-180 do tinh tu Bac theo chieu kim dong ho.
            Anh 3 m khong phan biet duoc mui/duoi nen chi biet truc, khong biet chieu.
  mov_hdg   huong di chuyen uoc luong tu do lech bang pho SuperDove (0-360 do tu Bac).
            CHUA HIEU CHINH: chi tham khao, can AIS de kiem chung.
  band_sh_m do lech giua nhom bang som/muon (m); lon (> 15 m) co the la tau dang chay
  moving    1 neu band_sh_m > 15 (nghi la dang chay), 0 neu khong
  n_dates   so ngay tau nay xuat hien

tracks_lines
  track     ma tau
  n_obs     so lan quan sat
  dates     cac ngay xuat hien
  first, last  ngay dau / ngay cuoi
  dist_m    khoang cach tu vi tri dau den vi tri cuoi (m)
  bearing   huong dich chuyen tu vi tri dau den vi tri cuoi (0-360 do tu Bac)
  length_m  chieu dai tau trung binh (m)
"""


def bearing_deg(e0, n0, e1, n1):
    return float((np.degrees(np.arctan2(e1 - e0, n1 - n0)) + 360) % 360)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("det_dir", help="folder with all_detections_tracked.csv (link_tracks.py)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--moving_m", type=float, default=15.0)
    a = ap.parse_args()
    out = a.out or os.path.join(a.det_dir, "shapefile")
    os.makedirs(out, exist_ok=True)

    d = pd.read_csv(os.path.join(a.det_dir, "all_detections_tracked.csv"))
    d["date"] = pd.to_datetime(d.scene.str[:8], format="%Y%m%d").dt.strftime("%Y-%m-%d")
    d["time_utc"] = d.scene.str[9:11] + ":" + d.scene.str[11:13] + ":" + d.scene.str[13:15]
    d["n_dates"] = d.groupby("track").scene.transform("nunique")
    d = d.sort_values(["track", "date"]).reset_index(drop=True)

    attrs = pd.DataFrame({
        "track": d.track.astype(int), "date": d.date, "time_utc": d.time_utc, "scene": d.scene,
        "conf": d.conf.round(3), "lon": d.lon, "lat": d.lat,
        "utm_e": d.easting.round(1), "utm_n": d.northing.round(1),
        "length_m": d.length_m, "width_m": d.width_m, "axis_deg": d.axis_deg,
        "mov_hdg": d.motion_heading_deg, "band_sh_m": d.band_shift_m,
        "moving": (d.band_shift_m > a.moving_m).astype(int), "n_dates": d.n_dates.astype(int),
    })

    pts = gpd.GeoDataFrame(attrs, geometry=[Point(x, y) for x, y in zip(d.lon, d.lat)], crs="EPSG:4326")
    pts.to_file(os.path.join(out, "ships_points.shp"), encoding="utf-8")

    boxes = gpd.GeoDataFrame(attrs.copy(), geometry=[Polygon(json.loads(p)) for p in d.poly_lonlat],
                             crs="EPSG:4326")
    boxes.to_file(os.path.join(out, "ships_boxes.shp"), encoding="utf-8")

    rows, geoms = [], []
    for t, g in d.groupby("track"):
        if len(g) < 2:
            continue
        g = g.sort_values("date")
        f, l = g.iloc[0], g.iloc[-1]
        rows.append(dict(track=int(t), n_obs=len(g), dates=",".join(g.date), first=f.date, last=l.date,
                         dist_m=round(float(np.hypot(l.easting - f.easting, l.northing - f.northing)), 1),
                         bearing=round(bearing_deg(f.easting, f.northing, l.easting, l.northing), 1),
                         length_m=round(float(g.length_m.mean()), 1)))
        geoms.append(LineString(zip(g.lon, g.lat)))
    lines = gpd.GeoDataFrame(pd.DataFrame(rows), geometry=geoms, crs="EPSG:4326")
    lines.to_file(os.path.join(out, "tracks_lines.shp"), encoding="utf-8")

    with open(os.path.join(out, "README_fields.txt"), "w", encoding="utf-8") as f:
        f.write(FIELDS)
    print(f"{len(pts)} points, {len(boxes)} boxes, {len(lines)} track lines -> {out}")
