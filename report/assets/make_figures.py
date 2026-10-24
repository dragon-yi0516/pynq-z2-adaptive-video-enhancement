"""Generate report figures from the measured CSVs.

用法（在有可用 matplotlib 的环境里）：
    python3 report/assets/make_figures.py
    python3 report/assets/make_figures.py --out report/assets

如果 matplotlib 不可用，直接按 report/report_data_sheet.md 的表
在 Excel/PPT 里画；数字不要改。
"""
import argparse
import csv
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

SCENES = ["uniform_dark", "dark_window", "uniform_normal", "normal_backlight"]


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def u_of(row):
    q = [float(row[k]) for k in ("q_tl", "q_tr", "q_bl", "q_br")]
    avg = sum(q) / 4.0
    return (max(q) - min(q)) / avg if avg >= 5 else 0.0


def main():
    p = argparse.ArgumentParser(description="report figures")
    p.add_argument("--out", default=HERE)
    p.add_argument("--hard-pairs", default=os.path.join(ROOT, "data", "hard_pairs.csv"))
    p.add_argument("--live-dir", default=os.path.join(ROOT, "data"))
    args = p.parse_args()

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        print("matplotlib 不可用：%s" % exc)
        print("请按 report/report_data_sheet.md 的表在 Excel/PPT 里画。")
        return 2

    os.makedirs(args.out, exist_ok=True)

    # ---- hard pair ----
    rows = read_rows(args.hard_pairs)
    by_scene = {i: [r for r in rows if int(float(r["round"])) == i]
                for i in range(4)}
    f_mean = [statistics.mean(float(r["f_luma"]) for r in by_scene[i])
              for i in range(4)]
    u_mean = [statistics.mean(u_of(r) for r in by_scene[i])
              for i in range(4)]

    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.bar(SCENES, f_mean, color=["#4c78a8", "#f58518", "#54a24b", "#e45756"])
    ax.set_ylabel("f_luma (mean)")
    ax.set_title("Hard pair: same brightness, different spatial layout")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    p1 = os.path.join(args.out, "hard_pair_f_luma.png")
    fig.savefig(p1, dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.bar(SCENES, u_mean, color=["#4c78a8", "#f58518", "#54a24b", "#e45756"])
    ax.set_ylabel("u = (max-min)/mean")
    ax.set_title("Spatial unevenness u (0.30 / 0.55 thresholds)")
    ax.axhline(0.30, color="gray", ls="--", lw=1, label="u_lo=0.30")
    ax.axhline(0.55, color="black", ls="--", lw=1, label="u_hi=0.55")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    p2 = os.path.join(args.out, "hard_pair_u.png")
    fig.savefig(p2, dpi=150)
    plt.close(fig)

    # 决策分布：MLP vs 空间（用部署权重实际预测，不用期望标签近似）
    import collections
    sys.path.insert(0, ROOT)
    sys.path.insert(0, os.path.join(ROOT, "stage04_mlp_train"))
    from lib import adaptive
    import mlp_common as mc
    with open(os.path.join(ROOT, "weights", "mlp_weights.h"),
              encoding="utf-8") as fh:
        model = mc.from_c_header(fh.read())

    mlp_counts = []
    sp_counts = []
    for i in range(4):
        c_mlp = collections.Counter()
        c_sp = collections.Counter()
        for r in by_scene[i]:
            f = (int(float(r["f_luma"])), int(float(r["f_luma2"])),
                 int(float(r["f_grad"])))
            q = tuple(float(r[k]) for k in ("q_tl", "q_tr", "q_bl", "q_br"))
            mlp = mc.predict_fixed_raw(model, f[0], f[1], f[2])
            c_mlp[mlp] += 1
            m, _, _ = adaptive.decide_spatial(f, q, mlp)
            c_sp["hold" if m is None else int(m)] += 1
        mlp_counts.append(c_mlp)
        sp_counts.append(c_sp)

    labels = ["0", "1", "2", "hold"]
    colors = ["#4c78a8", "#f58518", "#54a24b", "#9d9d9d"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.8), sharey=True)
    for ax, counts, title in ((axes[0], mlp_counts, "MLP label"),
                              (axes[1], sp_counts, "MLP + quadrants")):
        bottom = [0] * 4
        for lab, col in zip(labels, colors):
            def get_count(c, key=lab):
                return c.get("hold", 0) if key == "hold" else c.get(int(key), 0)
            vals = [get_count(counts[i]) for i in range(4)]
            ax.bar(SCENES, vals, bottom=bottom, label=lab, color=col)
            bottom = [b + v for b, v in zip(bottom, vals)]
        ax.set_title(title)
        ax.grid(axis="y", alpha=0.3)
        ax.tick_params(axis="x", labelrotation=15)
    axes[0].legend(fontsize=8)
    fig.tight_layout()
    p3 = os.path.join(args.out, "hard_pair_decisions.png")
    fig.savefig(p3, dpi=150)
    plt.close(fig)

    # ---- live timelines ----
    fig, axes = plt.subplots(2, 2, figsize=(11, 6), sharex=False)
    for i, ax in enumerate(axes.flat):
        path = os.path.join(args.live_dir, "live_scene%d.csv" % i)
        if not os.path.exists(path):
            ax.set_title("scene %d (missing)" % i)
            continue
        lr = read_rows(path)
        t = [float(r["t"]) for r in lr]
        mode = [int(float(r["mode"])) for r in lr]
        ax.step(t, mode, where="post", color="#4c78a8")
        ax.set_ylim(-0.3, 2.3)
        ax.set_yticks([0, 1, 2])
        ax.set_title("scene %d mode" % i)
        ax.grid(alpha=0.3)
    fig.tight_layout()
    p4 = os.path.join(args.out, "live_mode_timeline.png")
    fig.savefig(p4, dpi=150)
    plt.close(fig)

    fig, axes = plt.subplots(2, 2, figsize=(11, 6), sharex=False)
    for i, ax in enumerate(axes.flat):
        path = os.path.join(args.live_dir, "live_scene%d.csv" % i)
        if not os.path.exists(path):
            ax.set_title("scene %d (missing)" % i)
            continue
        lr = read_rows(path)
        t = [float(r["t"]) for r in lr]
        u = [float(r["u"]) for r in lr]
        ax.plot(t, u, color="#f58518")
        ax.axhline(0.30, color="gray", ls="--", lw=1)
        ax.axhline(0.55, color="black", ls="--", lw=1)
        ax.set_title("scene %d u" % i)
        ax.grid(alpha=0.3)
    fig.tight_layout()
    p5 = os.path.join(args.out, "live_u_timeline.png")
    fig.savefig(p5, dpi=150)
    plt.close(fig)

    # ---- fixed vs adaptive saturation ----
    fig, ax = plt.subplots(figsize=(5.5, 3.4))
    ax.bar(["fixed x1.5", "adaptive"], [29.4, 0.4],
           color=["#e45756", "#54a24b"])
    ax.set_ylabel("saturated pixels (%)")
    ax.set_title("Normal scene: 29.4% -> 0.4%")
    ax.grid(axis="y", alpha=0.3)
    for i, v in enumerate([29.4, 0.4]):
        ax.text(i, v + 0.6, "%.1f%%" % v, ha="center")
    fig.tight_layout()
    p6 = os.path.join(args.out, "fixed_vs_adaptive_saturation.png")
    fig.savefig(p6, dpi=150)
    plt.close(fig)

    for pth in (p1, p2, p3, p4, p5, p6):
        print("wrote", pth)
    return 0


if __name__ == "__main__":
    sys.exit(main())
