"""步骤 5：固定强度 vs 连续自适应 —— 同一场景下的画质对比（答辩用的量化证据）。

为什么要有这个脚本
------------------
方案书步骤 5 要回答一句话：**"连续自适应到底带来了什么收益？"**
只讲"PARAM 会变"不够，要把画质指标摆出来。本脚本在**同一个场景**下抓两次帧：

  固定  ：沿用阶段 7 的行为 —— 模式由场景决定，但强度写死 PARAM=192（×1.5）
  自适应：同一个模式，强度由 lib/adaptive.py 按**实时特征**算出来

然后比四个指标（都在 CPU 上算，取多次抓帧的中位数，去掉自动曝光/噪声的偶然性）：

  均值        画面整体亮暗
  std         对比度
  水平差分    清晰度（相邻像素 |Δ|）
  饱和率      打到 255 的像素占比 —— **自适应的核心卖点就是把这个数压下去**

预期结论（阶段 7 实测基线）：固定 mode 0 会把 26.7% 的像素打到饱和；
自适应按亮度反推增益，到目标亮度就回到 ×1.0，所以饱和率应显著下降。

用法（板子上）
--------------
    cd ~/jupyter_notebooks/ai_video_2024.2
    python3 tools/step5_compare.py                 # 三种场景依次来，每场先给 10 秒摆场景
    python3 tools/step5_compare.py --wait 15 --shots 5
    python3 tools/step5_compare.py --only 0        # 只测暗光场景（调试用）

结果既打印成表，也写到 data/step5_compare.csv（可直接贴进报告）。
"""
import argparse
import csv
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from lib import video_setup as vs          # noqa: E402
from lib import video_path as vp           # noqa: E402
from lib import exposure                   # noqa: E402
from lib import adaptive as ad             # noqa: E402
from lib.ai_video_regs import AiVideoRegs  # noqa: E402

# 和采集/演示同一档锁定曝光 —— 单一来源是 lib/exposure.py 的 WORKPOINT
# （不锁的话 AEC/AGC 会改曝光和增益，噪声一变 f_grad 就偏，三个类都不在训练分布里）。
DEMO_EXPOSURE = exposure.WORKPOINT["exposure"]
DEMO_GAIN = exposure.WORKPOINT["gain"]

FIXED_PARAM = 192          # 阶段 7 的固定强度（×1.5），也是 06_mode_manual 里的基线

SCENES = [
    (0, "暗光", "盒子主光源全关 / 拧到最暗档（目标 f_luma≈10）"),
    (1, "逆光", "后壁光板开 + 主光源关 + 黑卡纸剪影（目标 f_luma≈67、对比度最高）"),
    (2, "常规", "主光源中亮 + 对着打印网格/文字卡（目标 f_luma≈109、细节最多）"),
]


def parse_args():
    p = argparse.ArgumentParser(description="固定 vs 自适应 画质对比（方案书步骤 5）")
    p.add_argument("--wait", type=int, default=10, help="每个场景开始前留多少秒摆场景")
    p.add_argument("--shots", type=int, default=3, help="每个条件抓几帧取中位数")
    p.add_argument("--only", type=int, default=-1, help="只测某一个场景（0/1/2）")
    p.add_argument("--out", default=os.path.join(ROOT, "data", "step5_compare.csv"))
    return p.parse_args()


def shoot(regs, vdma0, mode, param, shots):
    """设好 mode/PARAM，等帧边界稳定后抓 shots 帧，返回四指标的中位数。"""
    regs.set_mode(mode)
    regs.set_param(param)
    for _ in range(3):                    # 等 3 帧，确保 mode_active 在帧边界更新
        regs.wait_new_frame()
    rows = []
    for _ in range(max(1, shots)):
        frame = vp.frame_to_rgb(vp.capture_frame(vdma0)).astype(np.float32)
        rows.append((
            float(frame.mean()),
            float(frame.std()),
            float(np.abs(np.diff(frame, axis=1)).mean()),
            100.0 * float((frame >= 255).mean()),
        ))
    med = np.median(np.array(rows), axis=0)
    return {"mean": med[0], "std": med[1], "diff": med[2], "sat": med[3]}


def main():
    args = parse_args()
    ol, iic, demosaic, vdma0, vdma1, mode = vs.bring_up(
        ROOT, manual_exposure=dict(exposure=DEMO_EXPOSURE, gain=DEMO_GAIN))
    vs.stop_all_channels(vdma0, vdma1)
    regs = AiVideoRegs(ol.axis_video_proc_0)
    print("VERSION = 0x%08X (阶段 %d)" % (regs.version(), regs.version_stage()))
    if not regs.has_param():
        print("!! 当前 hardware 阶段 < 12，没有 PARAM 寄存器 —— 这个对比做不了。")
        return 1

    vp.start_capture(vdma0, mode)
    vp.start_hdmi_passthrough(vdma0, vdma1, mode)   # 屏幕上能看见，方便确认场景摆对了
    regs.wait_new_frame()

    print("固定口径 = mode 由场景决定 + PARAM=%d（阶段 7 行为）；"
          "自适应 = 同一模式 + adaptive.param_for() 现场算的 PARAM" % FIXED_PARAM)
    print("曝光已锁定 = %d 行 / 增益 0x%02X（和采集一致）" % (DEMO_EXPOSURE, DEMO_GAIN))

    out_rows = []
    for label, name, hint in SCENES:
        if args.only >= 0 and label != args.only:
            continue
        print()
        print("=" * 74)
        print("【场景 %d %s】请这样摆：%s" % (label, name, hint))
        for i in range(args.wait, 0, -1):
            print("\r  倒计时 %2d 秒……" % i, end="", flush=True)
            time.sleep(1)
        print("\r  开始测量                    ")

        f = regs.mlp_features()
        mlp = regs.mlp_output()
        a = shoot(regs, vdma0, label, FIXED_PARAM, args.shots)
        p_dyn, why = ad.param_for(f, label)
        b = shoot(regs, vdma0, label, p_dyn, args.shots)

        print("  当前特征 f=%s  MLP_OUTPUT=%d（模型和场景一致=%s）"
              % (f, mlp, "是" if mlp == label else "否 ← 先摆好场景再测"))
        print("  %-22s %7s %7s %9s %8s" % ("条件", "均值", "std", "水平差分", "饱和%"))
        print("  %-22s %7.1f %7.1f %9.2f %7.1f%%"
              % ("固定 PARAM=%d" % FIXED_PARAM, a["mean"], a["std"], a["diff"], a["sat"]))
        print("  %-22s %7.1f %7.1f %9.2f %7.1f%%"
              % ("自适应 PARAM=%d" % p_dyn, b["mean"], b["std"], b["diff"], b["sat"]))
        print("    自适应的理由：%s" % why)
        print("    -> 饱和率 %.1f%% -> %.1f%%（%+.1f 个点）"
              % (a["sat"], b["sat"], b["sat"] - a["sat"]))
        out_rows.append((label, name, FIXED_PARAM, a["mean"], a["std"], a["diff"], a["sat"],
                         p_dyn, b["mean"], b["std"], b["diff"], b["sat"], why))

    if out_rows:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["场景", "名称", "固定PARAM", "固定均值", "固定std", "固定差分", "固定饱和%",
                        "自适应PARAM", "自适应均值", "自适应std", "自适应差分", "自适应饱和%", "自适应理由"])
            for r in out_rows:
                w.writerow([r[0], r[1], r[2]] + ["%.2f" % v for v in r[3:7]]
                           + [r[7]] + ["%.2f" % v for v in r[8:12]] + [r[12]])
        print()
        print("已写出:", args.out)
        print()
        print("报告里建议这么写：")
        for r in out_rows:
            print("  %s：固定 PARAM=%d 饱和 %.1f%% -> 自适应 PARAM=%d 饱和 %.1f%%"
                  % (r[1], r[2], r[6], r[7], r[11]))

    # 收尾：模式回到 0、参数回到固定基线，方便下一个 notebook
    regs.set_param(FIXED_PARAM)
    try:
        vs.stop_all_channels(vdma0, vdma1)
    except Exception:
        pass
    print()
    print("收尾完成（模式/参数已复位到 0 / %d）" % FIXED_PARAM)
    return 0


if __name__ == "__main__":
    sys.exit(main())
