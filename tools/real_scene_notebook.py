"""Jupyter 版真实场景 holdout 采集。

三个真实场景，一个场景一个 cell：
  0 real_dark       真实暗角/低光（有纹理，不要遮黑）
  1 real_backlight  真实窗边逆光（窗/灯在画面里）
  2 real_normal     真实室内正常光（有纹理，避免窗/灯直射）

采完写 data/real_scene_sceneN.csv，合并成 data/real_scene.csv；
然后用 eval_holdout.py 算部署权重的 acc/混淆矩阵（不重训）。
"""
import csv
import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from lib import adaptive             # noqa: E402
from lib.features_io import write_csv  # noqa: E402
import hard_pair_notebook as hp      # noqa: E402


# (round, 名字, 期望 label, f_luma 目标带, 摆法提示)
SCENES = [
    (0, "real_dark", 0, (4, 40),
     "真实暗角/低光：房间关灯/只留远处弱光；画面里放有纹理的物体"),
    (1, "real_backlight", 1, (40, 105),
     "真实窗边逆光：窗/灯进入画面，主体背光；尽量让整体亮度和正常光接近"),
    (2, "real_normal", 2, (80, 145),
     "真实室内正常光：有纹理的桌面/墙面；避免窗/灯直射镜头"),
]


def setup(skip_camera=False, use_manual=True, display=False):
    """复用 hard_pair_notebook 的 overlay/摄像头/VDMA 初始化。"""
    return hp.setup(skip_camera=skip_camera, use_manual=use_manual,
                    display=display)


def preview(regs):
    return hp.preview(regs)


def _mean(vals):
    return sum(vals) / float(len(vals)) if vals else 0.0


def _save_scene(idx, rows):
    path = os.path.join(ROOT, "data", "real_scene_scene%d.csv" % idx)
    write_csv(path, rows)
    print("已写", path, "（%d 帧）" % len(rows))
    return path


def collect_scene(regs, idx, n=40, wait=8, force=False, timeout=120.0):
    """采集一个真实场景；out-of-band 默认拒绝，force=True 强行采。"""
    ridx, name, label, band, hint = SCENES[idx]
    print("=" * 74)
    print("场景 %d：%s（期望 label=%d）" % (ridx, name, label))
    print("  " + hint)
    print("  目标 f_luma 带：%d~%d" % band)
    print("=" * 74)
    f, q, u = preview(regs)
    lo, hi = band
    if not (lo <= f[0] <= hi) and not force:
        print("!! 当前 f_luma=%d 不在 %d~%d。" % (f[0], lo, hi))
        print("   调灯光/距离后重跑本 cell；确实要强行采就传 force=True。")
        return []

    input("准备好后按回车开始采集（想准备多久都行；Ctrl+C 取消）...")
    for i in range(int(wait), 0, -1):
        print("\r    倒计时 %2d 秒……" % i, end="", flush=True)
        time.sleep(1)
    print("\r    开始采集！        ")

    rows = regs.collect_spatial(
        label, n=n, round_idx=ridx, timeout=timeout,
        poll_sleep=1e-3, verbose=True)
    _save_scene(ridx, rows)

    f1 = [r[0] for r in rows]
    us = [adaptive.spatial_unevenness(r[5:9]) for r in rows]
    print("本场景：n=%d  f_luma=%.1f±%.1f  u=%.3f"
          % (len(rows), _mean(f1),
             (sum((x - _mean(f1)) ** 2 for x in f1) / len(f1)) ** 0.5,
             _mean(us)))
    merge()
    return rows


def merge():
    """合并 data/real_scene_scene*.csv -> data/real_scene.csv。"""
    files = sorted(glob.glob(os.path.join(ROOT, "data", "real_scene_scene*.csv")))
    if not files:
        print("没有找到 real_scene_scene*.csv")
        return []
    rows = []
    for path in files:
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                rows.append([
                    int(float(r["f_luma"])), int(float(r["f_luma2"])),
                    int(float(r["f_grad"])), int(float(r["label"])),
                    int(float(r["round"])),
                    int(float(r["q_tl"])), int(float(r["q_tr"])),
                    int(float(r["q_bl"])), int(float(r["q_br"])),
                ])
    rows.sort(key=lambda x: (x[4], x[0]))
    out = os.path.join(ROOT, "data", "real_scene.csv")
    write_csv(out, rows)
    print("合并后 data/real_scene.csv：%d 帧，场景 %s"
          % (len(rows), sorted(set(r[4] for r in rows))))
    return rows


def evaluate():
    """用部署权重评估真实场景（不重训）。"""
    csv_path = os.path.join(ROOT, "data", "real_scene.csv")
    if not os.path.exists(csv_path):
        print("还没有 data/real_scene.csv；先跑场景 cell")
        return 1
    script = os.path.join(ROOT, "tools", "eval_holdout.py")
    return subprocess.call([sys.executable, script, "--csv", csv_path])


def cleanup(ol, vdma0, vdma1):
    return hp.cleanup(ol, vdma0, vdma1)
