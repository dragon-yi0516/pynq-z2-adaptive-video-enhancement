"""Jupyter 版 hard-pair 采集助手。

配合 tools/collect_hard_pairs.ipynb 使用：
    每个场景一个 cell，cell 先打印当前 f_luma/quads/u，
    等你按回车再开始采集，给你时间摆灯/摆卡。

所有数据仍然写到 data/hard_pairs_sceneN.csv，最后合并成
data/hard_pairs.csv，格式和 collect_hard_pairs.py 完全一致。
"""
import csv
import glob
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lib import video_setup as vs          # noqa: E402
from lib import video_path as vp           # noqa: E402
from lib import exposure                   # noqa: E402
from lib import adaptive                   # noqa: E402
from lib.ai_video_regs import AiVideoRegs  # noqa: E402
from lib.features_io import write_csv      # noqa: E402


# (round, 名字, 期望 label, pair, f_luma 目标带, 摆法提示)
SCENES = [
    (0, "uniform_dark", 0, 0, (5, 35),
     "均匀暗场：灰卡/白墙/棋盘，目标 f_luma 10~30；不要只遮黑镜头"),
    (1, "dark_window", 1, 0, (5, 35),
     "暗场+亮窗/灯：房间仍暗，但让窗/灯进入画面；目标 f_luma 仍 10~30"),
    (2, "uniform_normal", 2, 1, (80, 110),
     "均匀正常光：灰卡/白墙/纹理卡，目标 f_luma 90~100；不要放窗/灯"),
    (3, "normal_backlight", 1, 1, (80, 110),
     "正常亮度+逆光：窗/灯进入画面，主体背光；目标 f_luma 仍 90~100"),
]


def setup(skip_camera=False, use_manual=True, display=False):
    """加载 overlay、配置摄像头/VDMA、启动采集。返回 (ol, regs, vdma0, vdma1)。"""
    manual = None
    if use_manual:
        manual = dict(exposure=exposure.WORKPOINT["exposure"],
                      gain=exposure.WORKPOINT["gain"])
        print("手动曝光：%d 行 / 0x%02X（和训练数据同一工作点）"
              % (manual["exposure"], manual["gain"]))

    ol, iic, demosaic, vdma0, vdma1, mode = vs.bring_up(
        ROOT, manual_exposure=manual, skip_camera=skip_camera)
    vs.stop_all_channels(vdma0, vdma1)
    regs = AiVideoRegs(ol.axis_video_proc_0)
    print("VERSION = 0x%08X (阶段 %d)"
          % (regs.version(), regs.version_stage()))
    if not regs.has_param():
        raise RuntimeError(
            "需要阶段 12+ 的四象限寄存器；请在 overlay/ 里放 stage12/13 的 bit。")

    if display:
        # 注意：start_hdmi_passthrough 会停掉再启动四个通道并 tie 起来；
        # 它本身已经启动采集，不要再在后面调 start_capture（会把显示停掉）。
        vp.start_hdmi_passthrough(vdma0, vdma1, mode)
        print("HDMI 显示已启动（VDMA0→VDMA1→HDMI，直通）")
    else:
        vp.start_capture(vdma0, mode)
        print("视频流已启动（仅采集；HDMI 不亮是正常的）")
    regs.wait_new_frame()
    print("视频流已启动；下面先跑 preview cell 看当前 f_luma/u")
    return ol, regs, vdma0, vdma1


def preview(regs):
    """打印当前特征/四象限/u/MLP/模式，给摆场景用。可反复运行。"""
    f = regs.mlp_features()
    q = regs.quads()
    u = adaptive.spatial_unevenness(q)
    luma = f[0] / 0.879
    print("f=(%d, %d, %d)  luma≈%.1f  quads=%s  u=%.3f  MLP=%d  MODE=%d  PARAM=%d"
          % (f[0], f[1], f[2], luma, tuple(int(v) for v in q), u,
             regs.mlp_output(), regs.mode_sel(), regs.param()))
    return f, q, u


def _mean(vals):
    return sum(vals) / float(len(vals)) if vals else 0.0


def _save_scene(idx, rows):
    path = os.path.join(ROOT, "data", "hard_pairs_scene%d.csv" % idx)
    write_csv(path, rows)
    print("已写", path, "（%d 帧）" % len(rows))
    return path


def collect_scene(regs, idx, n=60, wait=10, force=False, timeout=120.0):
    """采集一个场景。

    流程：
      1. 打印场景提示和当前 preview；
      2. 如果当前 f_luma 不在目标带，默认拒绝（force=True 可强行采）；
      3. 等你按回车（Jupyter 里会给一个输入框，想准备多久都行）；
      4. 倒计时 wait 秒；
      5. 采 n 帧，写 data/hard_pairs_scene<idx>.csv；
      6. 自动合并到 data/hard_pairs.csv。
    """
    scene = SCENES[idx]
    ridx, name, label, pair, band, hint = scene
    print("=" * 72)
    print("场景 %d：%s（pair %d，期望 label=%d）" % (ridx, name, pair, label))
    print("  " + hint)
    print("  目标 f_luma 带：%d~%d" % band)
    print("=" * 72)
    f, q, u = preview(regs)
    lo, hi = band
    if not (lo <= f[0] <= hi) and not force:
        print("!! 当前 f_luma=%d 不在 %d~%d。" % (f[0], lo, hi))
        print("   先摆场景/调灯，再跑一次这个 cell；")
        print("   确实要强行采就传 force=True。")
        return []

    input("准备好后按回车开始采集（想准备多久都行；Ctrl+C 取消）...")
    for i in range(wait, 0, -1):
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
    merge_and_print()
    return rows


def merge():
    """把 data/hard_pairs_scene*.csv 合并成 data/hard_pairs.csv。"""
    files = sorted(glob.glob(os.path.join(ROOT, "data", "hard_pairs_scene*.csv")))
    if not files:
        print("没有找到 hard_pairs_scene*.csv")
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
    out = os.path.join(ROOT, "data", "hard_pairs.csv")
    write_csv(out, rows)
    return rows


def merge_and_print():
    rows = merge()
    if not rows:
        return rows
    print("合并后 data/hard_pairs.csv：%d 帧，场景 %s"
          % (len(rows), sorted(set(r[4] for r in rows))))
    for pair in (0, 1):
        a = [r for r in rows if r[4] == pair * 2]
        b = [r for r in rows if r[4] == pair * 2 + 1]
        if not a or not b:
            continue
        fa = _mean([r[0] for r in a])
        fb = _mean([r[0] for r in b])
        ua = _mean([adaptive.spatial_unevenness(r[5:9]) for r in a])
        ub = _mean([adaptive.spatial_unevenness(r[5:9]) for r in b])
        print("pair %d：f_luma %.1f vs %.1f（差 %.1f）；u %.3f vs %.3f（差 %.3f）"
              % (pair, fa, fb, abs(fa - fb), ua, ub, abs(ua - ub)))
    return rows


def evaluate():
    """调用 tools/eval_spatial.py 打印空间决策表。"""
    csv_path = os.path.join(ROOT, "data", "hard_pairs.csv")
    if not os.path.exists(csv_path):
        print("还没有 data/hard_pairs.csv；先跑场景 cell")
        return 1
    script = os.path.join(ROOT, "tools", "eval_spatial.py")
    return subprocess.call([sys.executable, script, "--csv", csv_path])


def cleanup(ol, vdma0, vdma1):
    """停止 VDMA 并释放 overlay。"""
    try:
        vs.stop_all_channels(vdma0, vdma1)
    except Exception as exc:
        print("stop channels:", exc)
    try:
        vs.shut_down(ol)
    except Exception as exc:
        print("shut_down:", exc)
    print("已释放 VDMA/overlay")
