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
它有两条必需：**要 root**（加载 overlay 要写 /dev/mem）+ **要用 PYNQ 那个 venv 的 python**
（系统解释器里没有 pynq）。Jupyter 的内核两条都满足，所以就在内核里跑。

**推荐：同一个内核、同进程调用。三档可以一档一格分开跑，也可以一次跑完。**

准备（一格，只跑一次）：

    import sys
    sys.path.insert(0, "/home/xilinx/jupyter_notebooks/ai_video_2024.2")
    import tools.step5_compare as s5

然后三格，每格一档 —— 摆好一档、测一档，再调下一档的灯（每格约 30 秒）：

    s5.main(["--only", "0", "--wait", "10", "--shots", "3"])   # 暗光
    s5.main(["--only", "1", "--wait", "10", "--shots", "3"])   # 逆光
    s5.main(["--only", "2", "--wait", "10", "--shots", "3"])   # 常规

CSV 是**合并**写的：三格跑完，data/step5_compare.csv 里就是完整的三行，
不会互相覆盖（单独重测某一档时，也只换掉那一行）。想看合并后的表：

    s5.report()

想一口气跑完（连续三个倒计时）也可以：`s5.main(["--wait", "10", "--shots", "3"])`。
**要跑第二次就再点一次运行**：脚本会把已经加载好的 overlay 留在本进程里，
第二次不再重新下载 bitstream，所以同一个内核里连跑多少次都不会崩。

**为什么不建议 subprocess —— "为什么第二次就跑不了"**
本脚本要**独占** PL：下载 bitstream、起 VDMA 抓帧、写 I2C 配摄像头。
而 PYNQ 的 PL 是整块下载的，**同一时刻只能有一个"PL 主人"**：

* 内核里**已经**跑过别的 overlay（05/06/07/13 里任何一格都会 `bring_up()`）→
  内核就是 PL 主人；这时再 `subprocess.run([...step5_compare.py...])`，
  新进程又下载一次同一块 bitstream → 两边抢硬件 → **SIGSEGV**。
  Python 侧只能看到 `CompletedProcess(..., returncode=-11)`，没有别的报错信息，
  看着就像"这个脚本跑不了第二次"；
* 就算那个独立进程已经退出，它的 VDMA 也可能还挂在 DDR 上，
  下一个进程下载/重配时照样踩到 —— 这就是 `-11` 的另一半来源。

所以两条路，选一条：

1. **同进程**跑（推荐，见上面的三行）—— 天然只有一个 PL 主人，可反复跑；
2. 坚持用 `subprocess` 跑的话，**每次跑之前先 `Kernel → Restart Kernel`**
   （把内核手里的 overlay/DMA 清掉），且那一格跑完之前别再运行别的 notebook 格。

**不要**在 SSH 终端里跑：不加 `sudo` 会报 `Root permissions required`；
加了 `sudo` 又会因为环境被清空而报 `No Devices Found`（XRT / PL server 的环境变量没了）。
终端里要硬凑得自己 source XRT 环境并对上 PL server —— 不值得。

**打断 / 报错怎么办**

* **中途按了『停止』**：脚本被 KeyboardInterrupt 打断，剩下的通道开着 —— 下一次运行会先停干净。
  读数或画面看着不对，就 `Kernel → Restart Kernel` 再跑，不用重启板子。
* **`RuntimeError: Allocate failed: 4294967295`**（从 `vdma.readchannel.start()` 抛出来的）：
  这是 XRT 分不出 DMA 缓冲了，跟脚本逻辑无关，也就是"跑几次就不能跑"的那个毛病。
  把它逼到这个状态的三条路：反复 SIGKILL/『停止』采集脚本、同一个进程里反复下载 bitstream、
  一次开机跑太多轮采集（每轮要几十 MB 的连续缓冲）。

  处理顺序（**别一报错就重启板子**）：

  1. 脚本自己会先停通道再试一次；
  2. **把其它 notebook 的内核关掉**（Jupyter 左侧点本子 → Shut Down Kernel）——
     每个内核都占着自己那一份 DMA 缓冲，只有内核进程退出、驱动才会回收；
     看有几个：`pgrep -af ipykernel`；
  3. 本 notebook `Kernel → Restart Kernel`，从上往下重跑；
  4. 还不行：终端 `bash tools/pl_cleanup.sh` 看证据，然后 `sudo reboot`。

  ⚠ 注意：**`release()` 不是急救手段**。实测两次"free 完之后再分配"更容易失败
  （2026-10-14 自助重下、2026-10-15 release 后换内核），所以它现在的定位只有两个：
  把 PL 让给别的进程之前；以及演示收工时。

常用参数：

    --wait 10                每个场景倒计时多少秒给你摆位（默认就是 10 秒）
    --shots 3                每个条件抓几帧取中位数（默认 3）
    --only 0                 只测暗光场景（调试用；0/1/2 对应 暗光/逆光/常规）
    --reload                 强制重新下载 bitstream（**少用**：同一进程二次下载最容易 Allocate failed）

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

# 摆位容差：f 离该场景的目标中心（data/features.csv 的类均值）多远算"没摆到位"。
# 20 和 tools/box_calibration.ipynb 的判定线一致（最近的一对中心才隔 39.4）。
SCENE_TOL = 20.0

SCENES = [
    (0, "暗光", "盒子主光源全关 / 拧到最暗档（目标 f=(10, 0, 17)）"),
    (1, "逆光", "后壁光板开 + 主光源关 + 黑卡纸剪影（目标 f=(66, 45, 21)：亮暗并存，"
             "但画面别带纹理 —— 光板要柔光、别露出灯珠或条纹，f_grad 一超过 25 就会被判成常规）"),
    (2, "常规", "主光源中亮 + 对着打印网格/文字卡（目标 f=(96, 69, 30)）"),
]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="固定 vs 自适应 画质对比（方案书步骤 5）")
    p.add_argument("--wait", type=int, default=10, help="每个场景开始前留多少秒摆场景")
    p.add_argument("--shots", type=int, default=3, help="每个条件抓几帧取中位数")
    p.add_argument("--only", type=int, default=-1, help="只测某一个场景（0/1/2）")
    p.add_argument("--out", default=os.path.join(ROOT, "data", "step5_compare.csv"))
    p.add_argument("--reload", action="store_true",
                   help="强制重新下载 bitstream（默认复用本进程已加载的 overlay）")
    return p.parse_args(argv)


# 进程内的 PL 缓存：同一个 Jupyter 内核里第二次调用 main() 时**复用**，不再下载 bitstream。
# 二次下载 = 两个"PL 主人"抢同一块硬件 = SIGSEGV（子进程返回码 -11）。
_PL_CACHE = None

# 上一次调用有没有干净跑完。被 KeyboardInterrupt（Jupyter 的"停止"按钮）打断时为 True ——
# 那种情况下 PL 里可能还留着没停下来的 DMA，复用它是危险的，所以下一次强制重下 bitstream。
_PL_DIRTY = False


def _acquire_pl(reload_bit=False, verbose=True):
    """拿到 (ol, iic, demosaic, vdma0, vdma1, mode)，并保证 VDMA 通道是停的。

    第一次调用做完整 bring_up（下载 bitstream + 配摄像头 + 锁曝光）；
    同一个进程里再调用就复用这份资源，只把曝光重新锁一遍（幂等，很便宜）。
    """
    global _PL_CACHE
    if _PL_DIRTY and not reload_bit:
        # 这里**故意不重新下载 bitstream**：同一个进程里二次下载 bitstream，
        # XRT 很容易给不出新的 DMA 缓冲（实测报 Allocate failed: 4294967295）。
        # 被打断留下的只是"通道还开着"，下面 stop_all_channels 就够收拾了。
        print("[PL] 注意：上一次这一格是被『停止』打断的 —— 先把 VDMA 通道停干净再继续。")
        print("     如果读数/画面看着不对，请 Kernel → Restart Kernel 之后重跑这一格。")
    if _PL_CACHE is not None and not reload_bit:
        ol, iic, demosaic, vdma0, vdma1, mode = _PL_CACHE
        vs.stop_all_channels(vdma0, vdma1)          # 上一轮可能还开着采集
        exposure.set_manual(iic, exposure=DEMO_EXPOSURE, gain=DEMO_GAIN)
        print("[PL] 复用本进程已加载的 overlay（未重新下载 bitstream）")
        return _PL_CACHE
    if _PL_CACHE is not None:                        # --reload：先把旧的停干净
        try:
            vs.stop_all_channels(_PL_CACHE[3], _PL_CACHE[4])
        except Exception:
            pass
        _PL_CACHE = None
    _PL_CACHE = vs.bring_up(ROOT,
                            manual_exposure=dict(exposure=DEMO_EXPOSURE, gain=DEMO_GAIN),
                            verbose=verbose)
    return _PL_CACHE


def release(verbose=True):
    """清理：停通道 + 释放 overlay / DMA 缓冲 + 清掉进程内缓存。

    ⚠ **它不是你遇到分配失败时的急救手段** —— 实测（2026-10-15）release() 之后
    换个内核重新分配，照样报 `Allocate failed`。那种情况的处理阶梯是：
    关掉其它 notebook 的内核 → Restart Kernel → `bash tools/pl_cleanup.sh` → reboot。

    什么时候用 release()：

    * **要把 PL 让给别的进程之前**（另一个 notebook、后台调度脚本）；
    * 演示/实验收工，想把这格恢复成"刚开内核"的状态。

    用法（Jupyter 一格，一秒就完事）：

        import tools.step5_compare as s5
        s5.release()

    效果：VDMA 通道全停、overlay 的 DMA 缓冲还回去、缓存清空、`gc.collect()`。
    下一次 `main()` 会**重新下载 bitstream** —— 等于把这格从头开始。
    """
    global _PL_CACHE, _PL_DIRTY
    had = _PL_CACHE is not None
    if had:
        ol, iic, demosaic, vdma0, vdma1, mode = _PL_CACHE
        try:
            vs.stop_all_channels(vdma0, vdma1)          # 先停通道，再还缓冲（顺序不能反）
        except Exception:
            pass
        try:
            ol.free()                    # 把 overlay 分配的 DMA 缓冲还给 XRT
        except Exception:
            pass                         # 老版本 PYNQ 没有 free() 也无所谓，GC 会收
    _PL_CACHE = None
    _PL_DIRTY = False
    import gc
    gc.collect()                                        # 让 ~Overlay 真的被回收
    if verbose:
        print("[PL] 已清理：VDMA 通道已停、overlay/DMA 缓冲已释放、缓存已清空。"
              if had else "[PL] 没有本进程加载过的 overlay —— 没什么可清的。")
        print("     下一次运行会重新下载 bitstream（相当于回到'刚开内核'的状态）。")
    return had


# ---------------------------------------------------------------------------
# CSV：支持"一档一格分开跑"，所以要能"读旧表 → 换掉本档那一行 → 写回"。
# 不然跑第三格时会把前两格的结果覆盖掉，最后 CSV 里只剩一行。
# ---------------------------------------------------------------------------
CSV_FIELDS = ["场景", "名称", "固定PARAM", "固定均值", "固定std", "固定差分", "固定饱和%",
              "自适应PARAM", "自适应均值", "自适应std", "自适应差分", "自适应饱和%",
              "自适应理由", "摆位", "mode0固定饱和%", "mode0自适应PARAM", "mode0自适应饱和%"]


def _read_csv_rows(path):
    """读回已有的 CSV，返回 {场景号: 一行 dict}。文件不存在/格式不对就返回空。"""
    rows = {}
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                rows[int(r["场景"])] = r
    except Exception:
        pass
    return rows


def _write_csv_rows(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        w.writeheader()
        for k in sorted(rows):
            w.writerow(rows[k])


def _row_of(label, name, a, p_dyn, b, why, off, a0, p0, b0):
    """把一次测量的结果整理成 CSV 的一行。"""
    ok = (off == off) and off <= SCENE_TOL
    return {
        "场景": label, "名称": name, "固定PARAM": FIXED_PARAM,
        "固定均值": "%.2f" % a["mean"], "固定std": "%.2f" % a["std"],
        "固定差分": "%.2f" % a["diff"], "固定饱和%": "%.2f" % a["sat"],
        "自适应PARAM": p_dyn, "自适应均值": "%.2f" % b["mean"],
        "自适应std": "%.2f" % b["std"], "自适应差分": "%.2f" % b["diff"],
        "自适应饱和%": "%.2f" % b["sat"], "自适应理由": why,
        "摆位": "OK" if ok else "偏差%.0f" % off,
        "mode0固定饱和%": "%.2f" % a0["sat"], "mode0自适应PARAM": p0,
        "mode0自适应饱和%": "%.2f" % b0["sat"],
    }


def report(csv_path=None, verbose=True):
    """把 CSV 读回来打印成一张表（三格分次跑完之后看这个）。

        s5.report()

    顺带告诉你还差哪一档没测、摆位是否达标 —— 只有「摆位 = OK」的行才能进报告。
    """
    path = csv_path or os.path.join(ROOT, "data", "step5_compare.csv")
    rows = _read_csv_rows(path)
    if not rows:
        print("!! %s 里还没有数据 —— 先跑一次 s5.main([...])。" % path)
        return {}
    if not verbose:
        return rows

    def pct(v):
        try:
            return "%.1f%%" % float(v)
        except Exception:
            return str(v)

    names = dict((l, n) for l, n, _ in SCENES)
    print("来自 %s（%d/3 档）" % (path, len(rows)))
    print("  %-6s %-8s %-22s %-22s"
          % ("档位", "摆位", "固定 → 自适应（饱和率）", "mode0：固定 → 自适应"))
    for label in sorted(rows):
        r = rows[label]
        print("  %-6s %-8s %-22s %-22s"
              % (names.get(label, label), r["摆位"],
                 "%s → %s" % (pct(r["固定饱和%"]), pct(r["自适应饱和%"])),
                 "%s → %s" % (pct(r["mode0固定饱和%"]), pct(r["mode0自适应饱和%"]))))
    print()
    print("报告里建议这么写：")
    for label in sorted(rows):
        r = rows[label]
        print("  %s：固定 PARAM=%s 饱和 %s%% -> 自适应 PARAM=%s 饱和 %s%%"
              % (r["名称"], r["固定PARAM"], r["固定饱和%"], r["自适应PARAM"], r["自适应饱和%"]))
        print("        mode0 增益：固定 ×1.5 饱和 %s%% -> 自适应 PARAM=%s 饱和 %s%%"
              % (r["mode0固定饱和%"], r["mode0自适应PARAM"], r["mode0自适应饱和%"]))
    todo = [l for l, n, h in SCENES if l not in rows]
    bad = [rows[l]["名称"] for l in sorted(rows) if rows[l]["摆位"] != "OK"]
    if todo:
        print()
        print("还差 %d 档没测：%s → 下一格 s5.main(['--only', '%d', '--wait', '10', '--shots', '3'])"
              % (len(todo), "、".join(names[l] for l in todo), todo[0]))
    if bad:
        print()
        print("!! %s 的摆位不在容差内 —— 这几行的数字别进报告。" % "、".join(bad))
    elif not todo:
        print()
        print("三档齐、摆位全 OK → 这张表可以直接进报告。")
    return rows


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


def main(argv=None):
    global _PL_DIRTY
    args = parse_args(argv)
    try:
        ol, iic, demosaic, vdma0, vdma1, mode = _acquire_pl(reload_bit=args.reload)
    except RuntimeError as exc:
        # PYNQ 在"环境不对"时会抛 No Devices Found —— 九成是在 SSH 终端里跑了。
        if "No Devices" in str(exc):
            print("!! 找不到 PYNQ 设备。这个脚本要在 **Jupyter 的 notebook 里（同进程）**跑：")
            print("   import sys; sys.path.insert(0, '%s')" % ROOT)
            print("   import tools.step5_compare as s5")
            print("   s5.main(['--wait', '10', '--shots', '3'])")
            print("   （SSH 终端里：不加 sudo 会缺 root 权限；加了 sudo 又会因为环境被清空而找不到设备）")
            return 1
        raise
    except EnvironmentError as exc:
        # 最常见的两种：① 没 sudo（加载 overlay 要写 /dev/mem）；② 用错解释器（系统 python 没 pynq）。
        if "Root permissions" in str(exc) or "Permission" in str(exc):
            print("!! 加载 overlay 需要 root。请改用：")
            print("   sudo /usr/local/share/pynq-venv/bin/python3 %s %s"
                  % (os.path.abspath(__file__), " ".join(sys.argv[1:])))
            print("   更好的做法：直接在 Jupyter 的 notebook 里跑（内核本来就是 root + 环境齐全）")
            return 1
        raise
    vs.stop_all_channels(vdma0, vdma1)
    _PL_DIRTY = True        # 从这里开始算"跑到一半"：中途被 Ctrl-C / 停止，就保持脏标记
    regs = AiVideoRegs(ol.axis_video_proc_0)
    print("VERSION = 0x%08X (阶段 %d)" % (regs.version(), regs.version_stage()))
    if not regs.has_param():
        print("!! 当前 hardware 阶段 < 12，没有 PARAM 寄存器 —— 这个对比做不了。")
        return 1

    def _start_streams():
        """起采集 + 起 HDMI 直通，返回 regs。抛 RuntimeError 就让调用方处理。"""
        vp.start_capture(vdma0, mode)
        vp.start_hdmi_passthrough(vdma0, vdma1, mode)   # 屏幕上能看见，方便确认场景摆对了
        r = AiVideoRegs(ol.axis_video_proc_0)
        r.wait_new_frame()
        return r

    try:
        regs = _start_streams()
    except RuntimeError as exc:
        if "Allocate failed" not in str(exc):
            raise
        # XRT 分不出 DMA 缓冲（返回无效 BO 0xFFFFFFFF）—— "跑几次就不行"就是这一条。
        # 只做一件便宜的事：把通道停干净再试一次。
        # **故意不 ol.free() / 不重下 bitstream**：实测这两件事之后再分配更容易失败
        # （2026-10-14 自助重下失败；2026-10-15 release() 之后换个内核分配也失败）。
        print("!! XRT 分不出 DMA 缓冲了（Allocate failed: 4294967295）—— 先停通道再试一次……")
        try:
            vs.stop_all_channels(vdma0, vdma1)
        except Exception:
            pass
        try:
            regs = _start_streams()
        except RuntimeError as exc2:
            print("!! 还是分不出来（%s）。" % exc2)
            print(vp.ALLOCATE_FAIL_LADDER)
            return 1

    print("固定口径 = mode 由场景决定 + PARAM=%d（阶段 7 行为）；"
          "自适应 = 同一模式 + adaptive.param_for() 现场算的 PARAM" % FIXED_PARAM)
    print("曝光已锁定 = %d 行 / 增益 0x%02X（和采集一致）" % (DEMO_EXPOSURE, DEMO_GAIN))
    # 把这回生效的参数打出来：改倒计时/抓帧数要写在这一格调用里的 s5.main([...])，
    # 不是改脚本默认值 —— 命令行参数会盖掉默认值（踩过一次：cell 里写着 --wait 5，却以为改了默认值）
    print("每个场景摆位倒计时 = %d 秒，每个条件抓 %d 帧（要改就改这一格里的 s5.main([...])）"
          % (args.wait, args.shots))

    # 一档一格分开跑时，先把已有结果读回来，本档测完只替换本档那一行。
    out_rows = _read_csv_rows(args.out) if args.only >= 0 else {}
    for label, name, hint in SCENES:
        if args.only >= 0 and label != args.only:
            continue
        print()
        print("=" * 74)
        if args.only >= 0:
            print("【本格只测场景 %d %s】（另两档的记录保留在 CSV 里）" % (label, name))
        else:
            print("【场景 %d %s】" % (label, name))
        print("  摆位要求：%s" % hint)
        # 终端里用 \r 原地刷新；Jupyter 里 \r 会变成一堆行，那边就一秒一行。
        tty = sys.stdout.isatty()
        for i in range(args.wait, 0, -1):
            if tty:
                print("\r  倒计时 %2d 秒……" % i, end="", flush=True)
            else:
                print("  倒计时 %2d 秒……" % i, flush=True)
            time.sleep(1)
        print("\r  开始测量                    " if tty else "  开始测量")

        f = regs.mlp_features()
        mlp = regs.mlp_output()
        a = shoot(regs, vdma0, label, FIXED_PARAM, args.shots)
        p_dyn, why = ad.param_for(f, label)
        b = shoot(regs, vdma0, label, p_dyn, args.shots)
        # 再追一组 mode 0（增益）的对照。为什么必须单独测：
        # **过曝只会发生在"增益"这一路**，而 mode 0 只在暗光档才会被选中 ——
        # 常规/逆光档用的是 mode 1/2（补偿/锐化），压根不会把像素打到 255，
        # 光看上面两行会误以为"自适应没带来什么"。报告里那条 26.7% 基线
        # 就是"mode 0 + 固定 ×1.5 + 常规亮度画面"（阶段 7 实测），得用同样口径测出来才能比。
        a0 = shoot(regs, vdma0, 0, FIXED_PARAM, args.shots)
        p0, why0 = ad.param_for(f, 0)
        b0 = shoot(regs, vdma0, 0, p0, args.shots)

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
        print("  %-22s %7.1f %7.1f %9.2f %7.1f%%"
              % ("mode0 固定 ×1.5", a0["mean"], a0["std"], a0["diff"], a0["sat"]))
        print("  %-22s %7.1f %7.1f %9.2f %7.1f%%"
              % ("mode0 自适应 PARAM=%d" % p0, b0["mean"], b0["std"], b0["diff"], b0["sat"]))
        print("    -> mode0 增益这一路：饱和率 %.1f%% -> %.1f%%（%+.1f 个点）｜%s"
              % (a0["sat"], b0["sat"], b0["sat"] - a0["sat"], why0))
        # 摆位自检：这场景的 f 有没有落在训练分布里。
        # 不查这一条，最容易出的岔子是"灯没调到采集时那一档，却把数字抄进报告"——
        # 表现是 MLP_OUTPUT 判错档、固定档也不过曝（饱和率全是 0），看着还挺像样。
        target = ad.CLASS_MEAN.get(label)
        off = ((f[0] - target[0]) ** 2 + (f[1] - target[1]) ** 2
               + (f[2] - target[2]) ** 2) ** 0.5 if target else float("nan")
        if off == off and off > SCENE_TOL:
            print("    ⚠ 摆位没到位：f 离目标中心 %s 有 %.0f（容差 %.0f）"
                  % (tuple(round(v, 1) for v in target), off, SCENE_TOL))
            print("      这一行的数字**不要进报告** —— 先调灯/摆位（照着 docs/04_demo_box.md 第 4 节，")
            print("      或跑 tools/box_calibration.ipynb 的 observe() 边调边看），再重跑这一格。")
        out_rows[label] = _row_of(label, name, a, p_dyn, b, why, off, a0, p0, b0)

    if out_rows:
        _write_csv_rows(args.out, out_rows)
        print()
        print("已写出:", args.out)
        report(args.out)                     # 打印合并后的表 + 还差哪档 + 报告措辞

    # 收尾：模式/参数回到基线、通道全停。**故意不 ol.free()** ——
    # overlay 留在本进程里，下一轮 _acquire_pl() 直接复用，不必二次下载 bitstream。
    regs.set_param(FIXED_PARAM)
    try:
        vs.stop_all_channels(vdma0, vdma1)
    except Exception:
        pass
    print()
    print("收尾完成（模式/参数复位到 0 / %d，VDMA 通道已停，overlay 保留在本进程）" % FIXED_PARAM)
    todo = [l for l, n, h in SCENES if l not in out_rows]
    names = dict((l, n) for l, n, _ in SCENES)
    if todo:
        print("下一格直接跑：s5.main(['--only', '%d', '--wait', '10', '--shots', '3'])   # %s"
              % (todo[0], names[todo[0]]))
    else:
        print("三档都测完了：想复看结果就 s5.report()；想把 PL 让给别的进程就先 s5.release()。")
    print("提示：同一格想再跑一遍 —— 直接再运行一次就行（复用已加载的 overlay，不重下 bitstream）。")
    print("      被『停止』打断过的话，脚本会自己重新下载 bitstream 复位 DMA。")
    _PL_DIRTY = False
    return 0


if __name__ == "__main__":
    sys.exit(main())
