"""Link ship detections across dates into tracks.

Scenes are days apart, so only slow/stationary ships (anchored, moored, drifting) can be
linked by position alone. Gating: distance <= --gate_m and similar length. Moving ships
need AIS (or much denser revisits) to be linked; their per-scene heading comes from the
SuperDove band offset instead (see detect_ships.py).
"""
import argparse
import glob
import json
import os

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment


def link(df, gate_m=800.0, len_tol=0.35):
    df = df.sort_values("scene").reset_index(drop=True)
    df["track"] = -1
    next_id = 0
    last = {}  # track id -> row index of its latest detection
    for scene in sorted(df.scene.unique()):
        cur = df.index[df.scene == scene].to_numpy()
        prev = np.array(list(last.values()), dtype=int)
        if len(prev):
            d = np.hypot(df.easting.values[cur, None] - df.easting.values[None, prev],
                         df.northing.values[cur, None] - df.northing.values[None, prev])
            la, lb = df.length_m.values[cur, None], df.length_m.values[None, prev]
            rel = np.abs(la - lb) / np.maximum(la, lb)
            cost = d / gate_m + rel / len_tol
            cost[(d > gate_m) | (rel > len_tol)] = 1e6
            r, c = linear_sum_assignment(cost)
            for i, j in zip(r, c):
                if cost[i, j] < 1e6:
                    df.loc[cur[i], "track"] = df.loc[prev[j], "track"]
        for i in cur:
            if df.loc[i, "track"] < 0:
                df.loc[i, "track"] = next_id
                next_id += 1
            last[df.loc[i, "track"]] = i
    return df


def to_geojson(df, path):
    feats = []
    for t, g in df.groupby("track"):
        g = g.sort_values("scene")
        coords = g[["lon", "lat"]].values.tolist()
        props = dict(track=int(t), n_obs=len(g), scenes=g.scene.tolist(),
                     mean_length_m=round(float(g.length_m.mean()), 1))
        geom = ({"type": "LineString", "coordinates": coords} if len(g) > 1
                else {"type": "Point", "coordinates": coords[0]})
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    with open(path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("det_dir")
    ap.add_argument("--gate_m", type=float, default=800.0)
    a = ap.parse_args()
    df = pd.concat([pd.read_csv(p) for p in glob.glob(os.path.join(a.det_dir, "*_ships.csv"))
                    if os.path.getsize(p) > 0])
    df = link(df, a.gate_m)
    df.to_csv(os.path.join(a.det_dir, "all_detections_tracked.csv"), index=False)
    to_geojson(df, os.path.join(a.det_dir, "tracks.geojson"))
    multi = df.groupby("track").filter(lambda g: len(g) > 1)
    print(f"{len(df)} detections, {df.track.nunique()} tracks, "
          f"{multi.track.nunique()} seen on >1 date")
    print(multi.sort_values(["track", "scene"])[["track", "scene", "lon", "lat", "length_m",
                                                "band_shift_m"]].to_string())
