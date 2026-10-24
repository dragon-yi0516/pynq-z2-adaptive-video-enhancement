"""Jupyter 版失败/边界场景检查。

每个 case 一个 cell：
  0 遮镜头/全黑
  1 均匀白墙
  2 过曝
  3 色偏

每个 case 采 30 帧，记录 f/quads/u/MLP/置信度/空间决策/当前模式；
不强制切模式，目的是看“门限有没有拒绝、会不会乱切”。
"""
import collections
import csv
import glob
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from lib import adaptive             # noqa: E402
import hard_pair_notebook as hp      # noqa: E402


CASES = [
    (0, "lens_covered", "遮镜头/全黑：应门限拒绝或保持，不应乱切"),
    (1, "uniform_wall", "均匀白墙：u 低，应信任 MLP；不要放窗/灯"),
    (2, "overexposed", "过曝：让窗/灯直射或提高增益，观察门限/判决"),
    (3, "color_cast", "色偏：用彩色灯/滤镜，观察是否误判"),
]


def setup(skip_camera=False, use_manual=True, display=False):
    return hp.setup(skip_camera=skip_camera, use_manual=use_manual,
                    display=display)


def preview(regs):
    return hp.preview(regs)


def _mean(vals):
    return sum(vals) / float(len(vals)) if vals else 0.0


def probe(regs, idx, n=30, wait=5, timeout=30.0):
    """采一个失败 case 的 30 帧，记录判决/置信度，不写 MODE_SEL。"""
    cidx, name, hint = CASES[idx]
    print("=" * 74)
    print("Case %d：%s" % (cidx, name))
    print("  " + hint)
    print("=" * 74)
    preview(regs)
    input("准备好后按回车开始采集（想准备多久都行；Ctrl+C 取消）...")
    for i in range(int(wait), 0, -1):
        print("\r    倒计时 %2d 秒……" % i, end="", flush=True)
        time.sleep(1)
    print("\r    开始采集！        ")

    rows = []
    last = regs.frame_cnt()
    t0 = time.time()
    while len(rows) < n and (time.time() - t0) < timeout:
        now = regs.frame_cnt()
        if now != last:
            last = now
            f = regs.mlp_features()
            q = regs.quads()
            mlp = regs.mlp_output()
            u = adaptive.spatial_unevenness(q)
            conf = adaptive.is_confident(f, mlp)
            m, p, why = adaptive.decide_spatial(f, q, mlp)
            rows.append([
                name, f[0], f[1], f[2], q[0], q[1], q[2], q[3],
                round(u, 4), int(mlp), int(bool(conf)),
                -1 if m is None else int(m), why,
                regs.mode_sel(), regs.param(),
            ])
        time.sleep(1e-3)

    path = os.path.join(ROOT, "data", "robust_%s.csv" % name)
    header = ["case", "f_luma", "f_luma2", "f_grad",
              "q_tl", "q_tr", "q_bl", "q_br", "u",
              "mlp", "confident", "decision", "reason", "mode", "param"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)

    f1 = [r[1] for r in rows]
    us = [r[8] for r in rows]
    mlp_c = collections.Counter(r[9] for r in rows)
    dec_c = collections.Counter(r[11] for r in rows)
    conf_n = sum(r[10] for r in rows)
    print("n=%d  f_luma=%.1f  u=%.3f  MLP=%s  confident=%d/%d  decision=%s"
          % (len(rows), _mean(f1), _mean(us), dict(mlp_c),
             conf_n, len(rows), dict(dec_c)))
    print("当前 MODE=%d PARAM=%d（本 probe 不写 MODE_SEL）"
          % (regs.mode_sel(), regs.param()))
    print("已写", path)
    return rows


def summary_all():
    """读 data/robust_*.csv，打印失败场景汇总表。"""
    files = sorted(glob.glob(os.path.join(ROOT, "data", "robust_*.csv")))
    if not files:
        print("还没有 robust_*.csv")
        return []
    print("| case | n | f_luma | u | MLP | confident | decision | mode |")
    print("|---|---|---|---|---|---|---|---|")
    out = []
    for path in files:
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            continue
        n = len(rows)
        f1 = _mean([float(r["f_luma"]) for r in rows])
        u = _mean([float(r["u"]) for r in rows])
        mlp = collections.Counter(r["mlp"] for r in rows)
        dec = collections.Counter(r["decision"] for r in rows)
        conf = sum(int(r["confident"]) for r in rows)
        mode = collections.Counter(r["mode"] for r in rows)
        print("| %s | %d | %.1f | %.3f | %s | %d/%d | %s | %s |"
              % (os.path.basename(path), n, f1, u,
                 dict(mlp), conf, n, dict(dec), dict(mode)))
        out.append({"file": path, "n": n, "f_luma": f1, "u": u,
                    "mlp": dict(mlp), "confident": conf,
                    "decision": dict(dec), "mode": dict(mode)})
    return out


def cleanup(ol, vdma0, vdma1):
    return hp.cleanup(ol, vdma0, vdma1)
