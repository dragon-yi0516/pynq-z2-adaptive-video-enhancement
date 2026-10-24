"""采集“同亮度、不同空间布局”的 hard pair，验证四象限决策。

这不是替代 collect_dataset.py，而是补它缺的那类数据：
原来的三类数据是按亮度分开的，MLP 只用亮度就能分到 98.5%；
hard pair 把两个场景的 f_luma 调到同一带内，只让空间布局不同，
用来证明“四象限真的参与了决策”，而不是只看全局亮度。

用法（板子上，工程根目录）：
    python3 tools/collect_hard_pairs.py
    python3 tools/collect_hard_pairs.py --per-scene 60 --wait 10
    python3 tools/collect_hard_pairs.py --auto-exposure   # 不用盒子时

采完：
    python3 tools/eval_spatial.py --csv data/hard_pairs.csv

输出 data/hard_pairs.csv（9 列，和 features.csv 兼容）：
    f_luma,f_luma2,f_grad,label,round,q_tl,q_tr,q_bl,q_br

round 是场景编号（0~3），label 是该场景“希望”的类别：
    0 均匀暗场      -> 0
    1 暗场+亮窗     -> 1（逆光）
    2 均匀中亮      -> 2
    3 中亮+逆光     -> 1
"""
import argparse
import os
import sys
import time

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


# (round, 名字, 期望 label, pair, 目标 f_luma 带, 摆法提示)
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


def parse_args():
    p = argparse.ArgumentParser(description="采集 hard pair（同亮度、不同空间布局）")
    p.add_argument("--per-scene", type=int, default=60,
                   help="每个场景采多少帧（默认 60）")
    p.add_argument("--wait", type=int, default=10,
                   help="每个场景开始前的摆场景时间（默认 10 秒）")
    p.add_argument("--out", default=os.path.join(ROOT, "data", "hard_pairs.csv"),
                   help="输出 CSV（默认 data/hard_pairs.csv）")
    p.add_argument("--no-camera", action="store_true",
                   help="不重配摄像头（notebook 已经配好时用）")
    p.add_argument("--auto-exposure", action="store_true",
                   help="不切手动曝光（不用盒子时用；但两个场景的亮度更难对齐）")
    p.add_argument("--exposure", type=int, default=exposure.WORKPOINT["exposure"],
                   help="手动曝光行数（默认 %d）" % exposure.WORKPOINT["exposure"])
    p.add_argument("--gain", type=lambda s: int(s, 0),
                   default=exposure.WORKPOINT["gain"],
                   help="手动增益码（默认 0x%02X）" % exposure.WORKPOINT["gain"])
    p.add_argument("--no-skip", action="store_true",
                   help="亮度不在目标带里也照采")
    return p.parse_args()


def countdown(seconds):
    for i in range(seconds, 0, -1):
        print("\r    倒计时 %2d 秒……" % i, end="", flush=True)
        time.sleep(1)
    print("\r    开始采集！        ")


def mean(vals):
    return sum(vals) / float(len(vals)) if vals else 0.0


def main():
    args = parse_args()
    manual = None
    if not args.auto_exposure:
        manual = dict(exposure=args.exposure, gain=args.gain)
        print("手动曝光：%d 行 / 0x%02X（两个场景必须用同一档）"
              % (args.exposure, args.gain))

    if args.no_camera:
        print("--no-camera：不重配摄像头，沿用 notebook 已经写好的寄存器。")

    ol, iic, demosaic, vdma0, vdma1, mode = vs.bring_up(
        ROOT, manual_exposure=manual, skip_camera=args.no_camera)
    vs.stop_all_channels(vdma0, vdma1)
    regs = AiVideoRegs(ol.axis_video_proc_0)
    print("VERSION = 0x%08X (阶段 %d)" % (regs.version(), regs.version_stage()))
    if not regs.has_param():
        raise RuntimeError("hard pair 需要阶段 12+ 的四象限寄存器；"
                           "请先加载 stage12_adaptive/stage13_split 的 overlay。")

    vp.start_capture(vdma0, mode)
    regs.wait_new_frame()

    rows = []
    for ridx, name, label, pair, band, hint in SCENES:
        print()
        print("=" * 72)
        print("场景 %d：%s（pair %d，期望 label=%d）" % (ridx, name, pair, label))
        print("  " + hint)
        print("  目标 f_luma 带：%d~%d" % band)
        print("=" * 72)
        countdown(args.wait)

        cur = regs.mlp_features()[0]
        lo, hi = band
        if not (lo <= cur <= hi):
            print("  !! 当前 f_luma=%d 不在 %d~%d；先调灯光/摆法" % (cur, lo, hi))
            if not args.no_skip:
                print("     跳过这个场景（加 --no-skip 可强行采）")
                continue

        got = regs.collect_spatial(
            label, n=args.per_scene, round_idx=ridx,
            timeout=120.0, poll_sleep=1e-3, verbose=True)
        rows += got
        f1 = [r[0] for r in got]
        us = [adaptive.spatial_unevenness(r[5:9]) for r in got]
        print("  到手 %d 帧：f_luma=%.1f±%.1f  u=%.3f"
              % (len(got), mean(f1),
                 (sum((x - mean(f1)) ** 2 for x in f1) / len(f1)) ** 0.5,
                 mean(us)))

    write_csv(args.out, rows)
    print()
    print("=" * 72)
    print("已写 %s：%d 帧" % (args.out, len(rows)))

    # 按 pair 检查“同亮度、不同空间布局”
    for pair in (0, 1):
        a = [r for r in rows if r[4] == pair * 2]
        b = [r for r in rows if r[4] == pair * 2 + 1]
        if not a or not b:
            print("pair %d：数据不全，跳过对比" % pair)
            continue
        fa = mean([r[0] for r in a])
        fb = mean([r[0] for r in b])
        ua = mean([adaptive.spatial_unevenness(r[5:9]) for r in a])
        ub = mean([adaptive.spatial_unevenness(r[5:9]) for r in b])
        print("pair %d：f_luma %.1f vs %.1f（差 %.1f）；u %.3f vs %.3f（差 %.3f）"
              % (pair, fa, fb, abs(fa - fb), ua, ub, abs(ua - ub)))
        if abs(fa - fb) > 10:
            print("  !! 两个场景亮度差 >10：先把 f_luma 调到同一带内")
        if abs(ua - ub) < 0.20:
            print("  !! 两个场景 u 差 <0.20：亮窗/灯没有落进单个象限，"
                  "把光源挪到画面的上/下/左/右一侧")

    print()
    print("下一步：python3 tools/eval_spatial.py --csv %s" % args.out)

    try:
        vs.stop_all_channels(vdma0, vdma1)
    except Exception:
        pass


if __name__ == "__main__":
    main()
