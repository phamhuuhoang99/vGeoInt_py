"""Overview map of linked tracks (UTM 50N): one colour per date, lines join the same ship."""
import argparse
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("det_dir")
    a = ap.parse_args()
    d = pd.read_csv(os.path.join(a.det_dir, "all_detections_tracked.csv"))
    d["date"] = d.scene.str[:8]
    fig, axes = plt.subplots(1, 2, figsize=(16, 7.5), gridspec_kw={"width_ratios": [1.3, 1]})
    colors = dict(zip(sorted(d.date.unique()), ["#1f77b4", "#d62728", "#2ca02c", "#9467bd"]))
    for ax, zoom in zip(axes, [False, True]):
        for t, g in d.groupby("track"):
            if len(g) > 1:
                g = g.sort_values("date")
                ax.plot(g.easting, g.northing, "-", color="0.4", lw=1, zorder=1)
        for date, g in d.groupby("date"):
            ax.scatter(g.easting, g.northing, s=18, color=colors[date], label=date, zorder=2)
            moving = g[g.band_shift_m > 15]
            ax.quiver(moving.easting, moving.northing,
                      moving.band_shift_m * 0 + 1, moving.band_shift_m * 0,
                      angles=90 - moving.motion_heading_deg, scale=30 if not zoom else 15,
                      color=colors[date], width=0.003, zorder=3)
        ax.set_aspect("equal")
        ax.ticklabel_format(useOffset=False, style="plain")
        ax.set_xlabel("Easting (m, UTM 50N)")
        ax.set_ylabel("Northing (m)")
        ax.grid(alpha=0.3)
        if zoom:
            m = d.groupby("track").filter(lambda g: len(g) > 1)
            ax.set_xlim(m.easting.min() - 800, m.easting.max() + 800)
            ax.set_ylim(m.northing.min() - 800, m.northing.max() + 800)
            ax.set_title("Khu neo: cùng một tàu qua các ngày (đường xám)")
            for t, g in m.groupby("track"):
                ax.annotate(str(t), (g.easting.iloc[0], g.northing.iloc[0]), fontsize=7,
                            xytext=(3, 3), textcoords="offset points")
        else:
            ax.set_title("Tất cả tàu phát hiện (YOLO-OBB v2); mũi tên = tàu đang chạy")
            ax.legend(title="Ngày")
    plt.tight_layout()
    plt.savefig(os.path.join(a.det_dir, "tracks_overview.png"), dpi=130)
