"""按提示采集三类特征，写成 data/features.csv（带分布图）。

为什么要有这个脚本
------------------
原来的采集是「手动调好场景 -> 跑一次 regs.collect(label, n=200)」，
结果 data/features.csv 里每类 200 帧**只有 2~18 个不同取值**
（三个静止场景各拍了 200 帧）。训练出来的 MLP 只见过那三个点，
实机落在中间地带时判决就是任意的 —— 实测就是这么翻的车：
f_luma=30 被判成 1，而它离类别 0 的中心（10）比离类别 1（67）更近。

这个脚本逼你「每一类都换几种场景」，采完顺手把分布画出来，
一眼就能看出「这份数据是不是三个点」。

用法（板子上，在 ai_video 目录下）：
    python3 tools/collect_dataset.py                  # 每类 3 轮 x 60 帧（盒子模式）
    python3 tools/collect_dataset.py --per-class 80 --rounds 4
    python3 tools/collect_dataset.py --no-plot        # 环境没有 matplotlib 时
    python3 tools/collect_dataset.py --auto-exposure  # 不用箱子、保留自动曝光

**默认会切手动曝光**（盒子模式，见 docs/04_demo_box.md）：
箱子里调暗灯的时候，自动曝光会把画面亮度顶回去，暗光档根本采不出来。
采完会自动跑一遍 tools/check_features.py 体检：有 FAIL 就别拿去重训。

下面的摆法是按箱子协议写的（目标 f_luma ≈ 10 / 67 / 109）；
不用箱子时自己改 SCENES 里的提示。

采完之后：
    1) 看分布图：三簇要分得开，而且每一簇是「一团」而不是「一个点」；
    2) 重训：03_mlp_train.ipynb -> 04_mlp_quant_export.ipynb；
    3) make_tv.py -> HLS -> bash build_overlay.sh 12
       （权重变了必须重出 bit，否则板上还是旧权重）
"""
import argparse
import os
import sys
import time

# ---- 自动定位工程根目录（和其它脚本一样的套路）--------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lib import video_setup as vs          # noqa: E402
from lib import video_path as vp           # noqa: E402
from lib.ai_video_regs import AiVideoRegs  # noqa: E402
from lib.features_io import write_csv      # noqa: E402
from lib import exposure                   # noqa: E402

# (label, 名字, 每轮提示) —— 每轮换一种摆法，别对着同一个画面拍两次
EXPECT_BAND = {0: (4, 30), 1: (45, 95), 2: (80, 145)}   # 各类 f_luma 的目标带

SCENES = [
    (0, "暗光", [
        "主光源全关、箱盖合上（最暗的一档，目标 f_luma≈10）",
        "主光源全关，把镜头往箱内壁多转一点（内容变了、亮度还是暗）",
        "主光源拧到最暗档（还亮一点点）",
        "主光源全关，换一张有纹理的卡片放进画面",
    ]),
    (1, "逆光", [
        "后壁光板开、主光源关，前面立黑卡纸剪影（目标 f_luma≈67，对比度最高）",
        "后壁光板开，剪影换细一点的（高光面积变大）",
        "后壁光板开 + 主光源拧到最弱，制造半明半暗",
        "剪影前后挪一点，让明暗比例变化",
    ]),
    (2, "常规/细节", [
        "主光源拧到中亮 + 有纹理的靶标（打印网格/文字卡；白纸就用笔画格子或写字）"
        "（目标 f_luma≈109，f_grad 最高）",
        "主光源中亮，换个角度和距离",
        "主光源中亮 + 移动卡片制造细节变化",
        "把另一件有纹理的东西也放进画面",
    ]),
]


def parse_args():
    p = argparse.ArgumentParser(description="ai_video 训练数据采集")
    p.add_argument("--per-class", type=int, default=60,
                   help="每一轮采多少帧（默认 60）")
    p.add_argument("--rounds", type=int, default=3,
                   help="每一类换几种场景（默认 3）")
    p.add_argument("--wait", type=int, default=10,
                   help="每轮开始前留多少秒让你摆场景（默认 10）")
    p.add_argument("--out", default=os.path.join(ROOT, "data", "features.csv"),
                   help="输出 csv（默认 data/features.csv）")
    p.add_argument("--no-plot", action="store_true", help="不画分布图")
    p.add_argument("--no-camera", action="store_true",
                   help="不重配摄像头（已经配好过、或两个进程抢 I2C 时用）")
    p.add_argument("--exposure", type=int, default=exposure.WORKPOINT["exposure"],
                   help="盒子模式下的曝光行数（默认 %d，= 本工程标定的工作点）"
                        % exposure.WORKPOINT["exposure"])
    p.add_argument("--gain", type=lambda s: int(s, 0), default=exposure.WORKPOINT["gain"],
                   help="盒子模式下的增益码，可用 0x 前缀（默认 0x%02X，= 本工程标定的工作点）"
                        % exposure.WORKPOINT["gain"])
    p.add_argument("--auto-exposure", action="store_true",
                   help="不切手动曝光（不用箱子、或要复现旧数据时用）")
    p.add_argument("--no-gate", action="store_true",
                   help="采完不跑 tools/check_features.py 体检")
    p.add_argument("--no-skip", action="store_true",
                   help="亮度不在目标带里也照采（默认会跳过那一轮保护数据）")
    p.add_argument("--no-spatial", action="store_true",
                   help="不写四象限列。阶段 12+ 默认写 round/q_tl/q_tr/q_bl/q_br，"
                        "给 lib/adaptive.py 的空间决策做标定。")
    return p.parse_args()


def run_gate(csv_path):
    """采完立刻体检。FAIL 就别拿去重训 —— 这份数据的毛病就是这个工具在抓的。"""
    import subprocess

    gate = os.path.join(_HERE, "check_features.py")
    if not os.path.exists(gate):
        print("（没找到 %s，跳过体检）" % gate)
        return None
    print()
    print("=" * 70)
    print("数据体检：tools/check_features.py")
    print("=" * 70)
    r = subprocess.run([sys.executable, gate, csv_path])
    if r.returncode == 0:
        print("体检通过 -> 可以进 03_mlp_train.ipynb 重训")
    else:
        print("体检没通过（退出码 %d）-> 按上面的 FAIL 提示把那一类重采；" % r.returncode)
        print("            别急着重训：只在几个点上对的模型，实机落在中间地带就会乱判")
    return r.returncode


def countdown(seconds):
    for i in range(seconds, 0, -1):
        print("\r    倒计时 %2d 秒……" % i, end="", flush=True)
        time.sleep(1)
    print("\r    开始采集！        ")


def plot_distribution(rows, out_png):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        print("（没画图：%s）" % e)
        return

    colors = {0: "tab:blue", 1: "tab:orange", 2: "tab:green"}
    names = {0: "0 dark", 1: "1 backlight", 2: "2 normal"}
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.5))
    pairs = [(0, 1, "f_luma", "f_luma2"),
             (0, 2, "f_luma", "f_grad"),
             (1, 2, "f_luma2", "f_grad")]
    for ax, (i, j, xi, xj) in zip(axes, pairs):
        for lab in (0, 1, 2):
            xs = [r[i] for r in rows if int(r[3]) == lab]
            ys = [r[j] for r in rows if int(r[3]) == lab]
            ax.scatter(xs, ys, s=6, alpha=0.5, c=colors[lab], label=names[lab])
        ax.set_xlabel(xi)
        ax.set_ylabel(xj)
        ax.grid(True, alpha=0.3)
    axes[0].legend()
    fig.suptitle("features distribution (each cluster should be a cloud, not a dot)")
    fig.tight_layout()
    fig.savefig(out_png, dpi=110)
    print("分布图已保存:", out_png)


def main():
    args = parse_args()

    manual = None
    if not args.auto_exposure:
        manual = dict(exposure=args.exposure, gain=args.gain)
        print("盒子模式：手动曝光 exposure=%d 行, gain=0x%02X"
              % (args.exposure, args.gain))
        print("          （要保留自动曝光就加 --auto-exposure）")

    ol, iic, demosaic, vdma0, vdma1, mode = vs.bring_up(
        ROOT, manual_exposure=manual, skip_camera=args.no_camera)
    vs.stop_all_channels(vdma0, vdma1)
    regs = AiVideoRegs(ol.axis_video_proc_0)
    print("VERSION = 0x%08X (阶段 %d)" % (regs.version(), regs.version_stage()))
    spatial = bool(regs.has_param()) and not args.no_spatial
    print("空间列：%s" % ("round/q_tl/q_tr/q_bl/q_br（阶段 12+）"
                          if spatial else "不采（--no-spatial 或硬件阶段 < 12）"))

    vp.start_capture(vdma0, mode)
    regs.wait_new_frame()

    rows = []
    skipped = []
    for label, name, hints in SCENES:
        for r in range(args.rounds):
            hint = hints[r % len(hints)]
            print()
            print("=" * 70)
            print("【类别 %d %s】第 %d/%d 轮" % (label, name, r + 1, args.rounds))
            print("  请这样摆：%s" % hint)
            print("  接下来采 %d 帧（约 %.0f 秒）"
                  % (args.per_class, args.per_class / 30.0))
            print("=" * 70)
            countdown(args.wait)

            # 采前保护：当前亮度不在这一类的目标带里，多半是灯没开/摆法没换，
            # 采下去只会得到一份「三类都贴在噪声底」的脏数据（10-11 就是这么翻的车）。
            cur = regs.mlp_features()[0]
            lo, hi = EXPECT_BAND[label]
            if not (lo <= cur <= hi):
                msg = ("类别 %d（%s）当前 f_luma=%d，不在目标带 %d~%d"
                       % (label, name, cur, lo, hi))
                print("  !! " + msg)
                if args.no_skip:
                    print("     （--no-skip，仍然继续采）")
                else:
                    print("     跳过这一轮（不采脏数据）：把光调到位后重跑；")
                    print("     确认要继续就加 --no-skip")
                    skipped.append(msg)
                    continue

            if spatial:
                got = regs.collect_spatial(
                    label, n=args.per_class, round_idx=r,
                    timeout=90.0, poll_sleep=1e-3, verbose=True)
            else:
                got = regs.collect(label, n=args.per_class, timeout=90.0,
                                   poll_sleep=1e-3, verbose=True)
            rows += got
            f = got[-1][:3]
            print("  本轮到手 %d 帧，最后一帧 f=(%d,%d,%d)"
                  % (len(got), f[0], f[1], f[2]))

    # rows 可能是 4 列（旧格式）或 9 列（含 round/quads）；
    # features_io.write_csv 会按实际长度决定表头，不会把旧流程弄坏。
    write_csv(args.out, rows)
    print()
    print("=" * 70)
    print("采集完成：%d 帧 -> %s" % (len(rows), args.out))
    for lab in (0, 1, 2):
        sel = [r for r in rows if int(r[3]) == lab]
        if not sel:
            continue
        uniq = len(set((r[0], r[1], r[2]) for r in sel))
        m1 = sum(r[0] for r in sel) / len(sel)
        m2 = sum(r[1] for r in sel) / len(sel)
        m3 = sum(r[2] for r in sel) / len(sel)
        print("  label %d: n=%3d  唯一取值 %3d  f均值=(%6.1f,%6.1f,%6.1f)"
              % (lab, len(sel), uniq, m1, m2, m3))
    print("=" * 70)
    print("判据：唯一取值应该接近 n（几十~几百），而不是个位数。")
    print("      某类只有 2~5 个唯一取值 = 那一类还是同一个静止画面，重采。")
    if skipped:
        print()
        print("跳过了 %d 轮（亮度不在目标带里）：" % len(skipped))
        for m in skipped:
            print("  - " + m)
        print("这些类样本会偏少，体检会提醒；调好光重跑一次即可。")

    if not args.no_plot:
        plot_distribution(
            rows, os.path.join(os.path.dirname(args.out), "features_dist.png"))

    print()
    print("下一步：03_mlp_train.ipynb -> 04_mlp_quant_export.ipynb")
    print("        -> make_tv.py -> HLS -> bash build_overlay.sh 12")

    if not args.no_gate:
        run_gate(args.out)

    try:
        vs.stop_all_channels(vdma0, vdma1)
    except Exception:
        pass


if __name__ == "__main__":
    main()
