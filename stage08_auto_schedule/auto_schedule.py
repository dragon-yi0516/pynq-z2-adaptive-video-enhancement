"""自动调度闭环：MLP 输出 -> 防抖 -> 帧边界切换可重构阵列。

为什么把这个循环写成独立的 .py，而不是留在 notebook 里：
  * Jupyter 的长 `while True` 会和内核/前端通信抢线程，跑久了容易卡死或
    让输出区来不及刷新，看起来像“板子挂了”。
  * .py 可以后台跑（nohup / &），notebook 只负责显示状态，答辩时更稳。
  * 出问题有日志可查。

用法（板上）：
    python /home/xilinx/jupyter_notebooks/ai_video/stage08_auto_schedule/auto_schedule.py
    python .../auto_schedule.py --duration 120 --log /home/xilinx/sched.log
    python .../auto_schedule.py --no-video     # 只观察，不写 MODE_SEL
    python .../auto_schedule.py --debounce 8 --min-hold 2.0   # 更"稳"，少来回跳
    python .../auto_schedule.py --heartbeat 5  # 每 5 秒写一条「MLP + 特征」进日志（默认 10 秒）

    # notebook 那边已经初始化过、并且开了 HDMI 显示时，用这两个开关：
    python .../auto_schedule.py --no-camera --keep-video --duration 300

为什么需要 --no-camera / --keep-video（都是真机踩出来的）：
  * --no-camera：notebook 那个进程已经把摄像头配好了（253 个寄存器写进传感器，
    写一次就生效、不会丢）。第二个进程再配一遍时，I2C 从机偶尔不应答，
    会抛 "Could not send I2C data"，调度脚本当场退出（2026-10-03 就发生过）。
  * --keep-video：notebook 如果已经用 start_hdmi_passthrough() 打开了 HDMI 显示，
    这里再 stop/start VDMA 通道会把显示通路拆掉 → 屏幕黑。
    带这个开关时脚本不碰 VDMA，只读 MLP_OUTPUT / 写 MODE_SEL。

停止：Ctrl+C
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lib import video_setup as vs          # noqa: E402
from lib import video_path as vp           # noqa: E402
from lib.ai_video_regs import AiVideoRegs  # noqa: E402
from lib import adaptive as adaptive_mod   # noqa: E402  阶段 12 连续参数策略


def parse_args():
    p = argparse.ArgumentParser(description="ai_video 自动调度闭环")
    p.add_argument("--duration", type=float, default=0.0,
                   help="运行秒数，0 表示一直跑到 Ctrl+C")
    p.add_argument("--debounce", type=int, default=3,
                   help="连续多少次读到同一个 MLP 结果才认为稳定（默认 3）")
    p.add_argument("--min-hold", type=float, default=1.5,
                   help="两次切换之间至少间隔多少秒（默认 1.5）。"
                        "真机上 MLP 会在相邻帧之间偶发抖动，只靠 debounce 防不住"
                        "来回跳（实测 1.6 秒里切了 4 次），要再加一道时间闸。")
    p.add_argument("--poll", type=float, default=0.02,
                   help="轮询间隔秒（默认 0.02）")
    p.add_argument("--heartbeat", type=float, default=10.0,
                   help="每多少秒往日志里写一条心跳（含 MLP / 模式 / FRAME_CNT / 特征），"
                        "0 = 关掉。排查「MLP 一直是同一个值」时最有用："
                        "特征不变 = 画面没变，不是代码问题。")
    p.add_argument("--log", default="", help="日志文件路径（可选）")
    p.add_argument("--no-video", action="store_true",
                   help="只观察 MLP 输出，不真正写 MODE_SEL")
    p.add_argument("--adaptive", action="store_true",
                   help="阶段 12 硬件：除了切 MODE_SEL，还按实时特征**连续**写 PARAM，"
                        "让处理强度跟着场景变（而不是三种写死的强度）。"
                        "硬件阶段号 < 12 时会自动退回固定参数模式。")
    p.add_argument("--param", type=int, default=192,
                   help="非 --adaptive 时写一次的固定 PARAM（默认 192，0~255）。"
                        "192 让 mode0 等于阶段 7 的 ×1.5；"
                        "含义见 docs/01_register_map.md。")
    p.add_argument("--no-camera", action="store_true",
                   help="不重新配置摄像头（notebook 那边已经配好了）。"
                        "两个进程抢 I2C 时这一步会失败，失败后脚本会退出。")
    p.add_argument("--keep-video", action="store_true",
                   help="不碰 VDMA 通道：notebook 可能已经用 start_hdmi_passthrough() "
                        "把 HDMI 显示跑起来了，这里再 stop/start 会把屏幕弄黑。")
    p.add_argument("--param-step", type=int, default=2,
                   help="--adaptive 时 PARAM 变化超过这个值才写寄存器（默认 2）。"
                        "避免特征的小抖动被原样写进去、让画面跟着抖。")
    p.add_argument("--confidence", type=float, default=None,
                   help="置信度门限。不指定（默认）= 用 lib/adaptive.py 按当前 "
                        "data/features.csv **逐类**算出来的门限（推荐，重训后自动跟上）。"
                        "给一个正数 = 所有类共用一个数；0 = 关掉门限。"
                        "作用：只有特征离目标类别中心不超过门限时才认这次 MLP 判决 —— "
                        "训练数据中间地带没样本，MLP 会在那里随机跳，"
                        "而特征几乎没变，模式跟着来回切、画面闪。")
    p.add_argument("--no-spatial", action="store_true",
                   help="关掉四象限空间决策，退回纯 MLP。"
                        "默认在阶段 12+ 硬件上开启：u>=--u-hi 时优先逆光补偿，"
                        "u<=--u-lo 时信任 MLP，中间保持当前模式。")
    p.add_argument("--u-hi", type=float, default=None,
                   help="四象限不均匀度上阈值（默认用 lib/adaptive.py 的 0.55）。")
    p.add_argument("--u-lo", type=float, default=None,
                   help="四象限不均匀度下阈值（默认用 lib/adaptive.py 的 0.30）。")
    p.add_argument("--base", default="",
                   help="直接给 axis_video_proc 的 AXI-Lite 基地址。"
                        "注意这个地址**每次重新插 BD 都会变**（重新综合时 Vivado 重新分配），"
                        "最近一次是 0x44A00000；用 07_auto_schedule.ipynb 里那格从 "
                        "ol.ip_dict['axis_video_proc_0']['phys_addr'] 读出来的值最稳。"
                        "给了它就完全不加载 overlay、不碰 VDMA/I2C，只用 MMIO 读写这个 IP 的"
                        "寄存器 —— notebook 那边已经开好显示通路时，这是最安全的跑法。")
    return p.parse_args()


class Logger:
    def __init__(self, path):
        self.fh = open(path, "a", encoding="utf-8") if path else None

    def __call__(self, msg):
        line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
        print(line, flush=True)
        if self.fh:
            self.fh.write(line + "\n")
            self.fh.flush()

    def close(self):
        if self.fh:
            self.fh.close()


def _cnt(regs, name):
    """读诊断计数器；老版 lib 里没有这个函数就返回 -1。"""
    fn = getattr(regs, name, None)
    return fn() if callable(fn) else -1


def fmt_features(regs):
    """三个 MLP 输入特征 (f_luma, f_luma2, f_grad)；读不到返回 None。"""
    try:
        return tuple(regs.mlp_features_from_raw(regs.raw_stats()))
    except Exception:
        return None


def log_state(log, regs, tag):
    """把「现在到底是什么状态」写成一行日志（起步和心跳都用它）。"""
    # 阶段 12 起多打一个 PARAM：这是「连续自适应」有没有在动的直接证据 ——
    # 心跳里 PARAM 跟着特征一起变，说明参数是连续跟的，不是只在切换模式时才动。
    extra = ""
    try:
        if regs.has_param():
            extra = " PARAM=%d" % regs.param()
    except Exception:
        extra = ""
    log("%s：MODE_SEL=%d MLP_OUTPUT=%d FRAME_CNT=%d MLP_START=%d MLP_DONE=%d 特征=%s%s"
        % (tag, regs.mode_sel(), regs.mlp_output(), regs.frame_cnt(),
           _cnt(regs, "mlp_start_cnt"), _cnt(regs, "mlp_done_cnt"),
           fmt_features(regs), extra))


def main():
    args = parse_args()
    log = Logger(args.log)

    # ---- 找到本 IP 的寄存器接口 -------------------------------------------
    base = int(args.base, 0) if args.base else 0
    if base:
        # 最干净的一种跑法：另一个进程已经加载好 overlay、开好显示通路，
        # 这边只用 MMIO 戳我们这个 IP 的寄存器（0x1000 = 4KB 寄存器空间）。
        # 不加载 overlay、不碰 VDMA、不碰 I2C，所以不会和 notebook 抢任何东西。
        from pynq import MMIO

        regs = AiVideoRegs(MMIO(base, 0x1000))
        ol = vdma0 = vdma1 = None
        log("按 --base=0x%X：只用 MMIO 读写 IP 寄存器（不加载 overlay / 不碰 VDMA / 不碰 I2C）"
            % base)
        log("IP 版本 0x%08X (阶段 %d)" % (regs.version(), regs.version_stage()))
        if regs.version_stage() < 7:
            log("警告：当前硬件阶段 < 7，MODE_SEL 不会改变画面")
        log_state(log, regs, "起步状态")
        run_loop(args, log, regs)
        return

    # ---- 加载 overlay + （可选）配置摄像头 ---------------------------------
    # 摄像头寄存器写一次就留在传感器里，所以第二个进程不需要再配一遍；
    # 再配一遍还可能因为 I2C 抢占总线直接抛异常（真机发生过）。
    if args.no_camera:
        log("按 --no-camera：只加载 overlay，不重配摄像头")
        ol = vs.load_overlay(ROOT, verbose=False)
        vdma0, vdma1, mode = vs.init_vdma(ol, verbose=False)
    else:
        try:
            ol, iic, demosaic, vdma0, vdma1, mode = vs.bring_up(ROOT, verbose=False)
        except Exception as e:
            log("警告：初始化摄像头失败（%s）" % e)
            log("      按【摄像头已经配好了】继续：只加载 overlay，不再动 I2C。")
            log("      下次可以直接加 --no-camera 跳过这一步。")
            ol = vs.load_overlay(ROOT, verbose=False)
            vdma0, vdma1, mode = vs.init_vdma(ol, verbose=False)

    regs = AiVideoRegs(ol.axis_video_proc_0)
    log("overlay 版本 0x%08X (阶段 %d)" % (regs.version(), regs.version_stage()))
    if regs.version_stage() < 7:
        log("警告：当前硬件阶段 < 7，MODE_SEL 不会改变画面")

    # ---- 视频流 -----------------------------------------------------------
    if args.keep_video:
        log("按 --keep-video：不动 VDMA 通道（HDMI 显示通路保持原样）")
    else:
        vs.stop_all_channels(vdma0, vdma1)
        # 启动采集，保证视频流经过 IP（统计/推理/处理都需要流量）
        vp.start_capture(vdma0, mode)
        log("视频流已启动，FRAME_CNT=%d" % regs.frame_cnt())

    log_state(log, regs, "起步状态")
    run_loop(args, log, regs)


def run_loop(args, log, regs):
    """读 MLP_OUTPUT -> 防抖 -> 时间闸 -> 帧边界写 MODE_SEL。"""
    last_mlp = -1
    stable = 0
    current_mode = regs.mode_sel()
    switches = 0
    suppressed = 0
    spatial_overrides = 0  # 四象限把 MLP 判决改掉的次数（答辩证据：空间信息真的参与了决策）
    spatial_holds = 0      # 空间处于中间地带、选择保持的次数
    gate_rejects = 0     # 被置信度门限判成"不可信"的次数（答辩证据：中间地带的判决被拒了）
    t0 = time.time()
    last_switch_t = t0 - args.min_hold     # 允许第一次立即切

    # 上一次写下去的 PARAM（-1 = 还没写过）；--param-step 用来防抖
    last_param = -1
    param_step = max(1, int(getattr(args, "param_step", 2)))
    # confidence=None -> 用 lib/adaptive.py 按当前 features.csv 逐类算出的门限
    confidence = getattr(args, "confidence", None)
    if confidence is not None:
        confidence = float(confidence)
    gate_on = (confidence is None) or (confidence > 0)
    # 防御：auto_schedule.py 更新了、但 lib/adaptive.py 忘了拷时，
    # 直接关掉门限并提示，而不是抛 AttributeError 让整轮白跑。
    if gate_on and not hasattr(adaptive_mod, "is_confident"):
        log("警告：lib/adaptive.py 是旧版（没有置信度门限），本次忽略门限。")
        log("      请把 lib/adaptive.py 一起更新到最新版。")
        confidence, gate_on = 0.0, False

    # ---- 阶段 12：连续参数 ------------------------------------------------
    adaptive = bool(getattr(args, "adaptive", False))
    if adaptive and not regs.has_param():
        log("提示：--adaptive 需要阶段 12 以上硬件（当前阶段 %d），"
            "自动退回固定参数模式" % regs.version_stage())
        adaptive = False
    if adaptive and gate_on:
        if confidence is None:
            log("置信度门限（默认规则，按 %s）: 归一化距离 ≤ %.0fσ，且判决类必须是最近类"
                % (getattr(adaptive_mod, "CLASS_STATS_SOURCE", "?"),
                   getattr(adaptive_mod, "NN_SIGMA_MAX", 8.0)))
            tbl = getattr(adaptive_mod, "CONFIDENCE_BY_CLASS", {})
            log("  参考（只有 --confidence 显式给数时才用这份逐类距离门限）: %s"
                % "，".join("%s=%.1f" % (adaptive_mod.CLASS_NAME.get(k, k), v)
                            for k, v in sorted(tbl.items())))
            log("  想强行统一就用 --confidence 25；想关掉就用 --confidence 0")
        else:
            log("置信度门限 = %.0f（所有类共用；0 = 关掉）" % confidence)
    if regs.has_param():
        if adaptive:
            log("按 --adaptive：切换模式时同时按实时特征连续写 PARAM（%s）"
                % adaptive_mod.describe())
        else:
            regs.set_param(int(args.param) & 0xFF)
            log("固定 PARAM = %d（0x%02X）；加 --adaptive 可让强度跟着场景连续变"
                % (int(args.param) & 0xFF, int(args.param) & 0xFF))
    elif args.param != 192:
        log("提示：--param 需要阶段 12 以上硬件，已忽略")

    # ---- 四象限空间决策 --------------------------------------------------
    # 全局三特征分不清“整体偏亮”和“中间暗、四周亮”的逆光；
    # 四象限寄存器 0x38/0x3C 已经在 stage12/13 硬件里，这里只读、不写，
    # 零额外 LUT/DSP。它和 MLP 是互补关系，不是替换关系。
    spatial = ((not getattr(args, "no_spatial", False))
               and regs.has_param()
               and hasattr(adaptive_mod, "decide_spatial"))
    if spatial:
        u_hi_log = getattr(args, "u_hi", None)
        u_lo_log = getattr(args, "u_lo", None)
        if u_hi_log is None:
            u_hi_log = getattr(adaptive_mod, "SPATIAL_U_HI", 0.55)
        if u_lo_log is None:
            u_lo_log = getattr(adaptive_mod, "SPATIAL_U_LO", 0.30)
        log("空间决策：开启（u>=%.2f -> 逆光补偿，u<=%.2f -> 信任 MLP，"
            "中间保持；--no-spatial 可关）"
            % (u_hi_log, u_lo_log))
    else:
        log("空间决策：关闭（--no-spatial，或硬件阶段 < 12，或 adaptive.py 是旧版）")

    # 前 1 秒先读一遍基线，避免刚启动就误切。
    # 流没起来的话这里会超时：记一笔继续跑，别让脚本在这里退出 ——
    # 退出就没有收尾行，日志会被判成"脚本没跑完"（判分依据见 VERIFY.md）。
    try:
        regs.wait_new_frame()
    except TimeoutError as e:
        log("警告：启动时等新帧超时（%s）—— 视频流可能没起来" % e)

    # ---- 诊断用：心跳 / 视频流停了没有 / 画面变了没有 ---------------------
    hb = getattr(args, "heartbeat", 0.0)
    next_hb = t0 + hb if hb else 0.0
    frame_cnt = regs.frame_cnt()
    frame_moved_t = time.time()
    stall_reported = False
    feat = fmt_features(regs)
    feat_since = time.time()
    feat_reported = False

    try:
        while True:
            if args.duration and (time.time() - t0) > args.duration:
                break

            mlp = regs.mlp_output()
            f_dec = fmt_features(regs)

            # ---- 置信度门限：特征离目标类中心太远就当作「没换」------------
            # 实测：特征一直是 (19,1,39) 不动，MLP 却在 0/1 之间跳
            # （因为训练数据里 f1 只有 10/67/109，19 落在没训练过的中间地带）。
            # 这里把不可信的判决直接压成「和当前模式一致」，防抖逻辑自然就不会切。
            if gate_on:
                # threshold=None -> lib/adaptive.py 用逐类门限
                if f_dec is not None and not adaptive_mod.is_confident(f_dec, mlp, confidence):
                    gate_rejects += 1
                    # 只打前 5 次，避免刷屏；这几行就是「门限拒绝了不可信判决」的直接证据
                    if gate_rejects <= 5:
                        log("门限拒绝：MLP 说 %d，但特征 %s 离它那一类太远/不是最近类 -> 保持模式 %d"
                            % (mlp, f_dec, current_mode))
                    mlp = current_mode

            # ---- 四象限空间决策：全局特征之外的第二个判据 -----------------
            # u 大 = 画面明显不均（窗口/侧光），优先 mode 1；
            # u 小 = 照明均匀，信任 MLP；
            # 中间 = 保持当前模式（迟滞），不要凭噪声切。
            quads_now = None
            u_now = None
            param_target = None
            if spatial and f_dec is not None:
                try:
                    quads_now = regs.quads()
                except Exception:
                    quads_now = None
                if quads_now is not None:
                    u_now = adaptive_mod.spatial_unevenness(quads_now)
                    mode_sp, param_sp, why_sp = adaptive_mod.decide_spatial(
                        f_dec, quads_now, mlp,
                        getattr(args, "u_hi", None),
                        getattr(args, "u_lo", None))
                    if mode_sp is None:
                        spatial_holds += 1
                        mlp = current_mode
                    else:
                        if mode_sp != mlp:
                            spatial_overrides += 1
                            if spatial_overrides <= 5:
                                log("空间覆盖：MLP=%d -> 模式=%d（%s）"
                                    % (mlp, mode_sp, why_sp))
                        mlp = mode_sp
                        param_target = param_sp
            if mlp == last_mlp:
                stable += 1
            else:
                last_mlp, stable = mlp, 1

            # ---- 阶段 12：连续参数（不等模式切换，每轮都跟着特征走）--------
            # 之前的实现只在「切换模式」分支里写 PARAM，于是场景变了但 MLP 类别
            # 没变时参数就不动 —— 那不算连续自适应。这里每轮都算一次，
            # 只有和上次差超过 param_step 才真写寄存器（省 AXI 事务、也防抖）。
            if adaptive:
                f_loop = fmt_features(regs)
                if f_loop is not None:
                    # 用 param_for（返回 2 个值）；直接解包 decide() 的 3 个值踩过坑
                    if param_target is None:
                        p_new, _why = adaptive_mod.param_for(f_loop, mlp)
                    else:
                        p_new = param_target
                    if last_param < 0 or abs(p_new - last_param) >= param_step:
                        regs.set_param(p_new)
                        last_param = p_new

            # 防抖：连续 debounce 次同样的结论，且和当前模式不同，才切换
            if stable >= args.debounce and mlp != current_mode:
                if (time.time() - last_switch_t) < args.min_hold:
                    # 时间闸没到：记一笔，但不切。避免 MLP 在两类之间来回抖时
                    # 画面跟着每秒闪好几次。
                    suppressed += 1
                elif args.no_video:
                    log("(仅观察) MLP=%d，当前模式=%d，本应切换" % (mlp, current_mode))
                    current_mode = mlp
                    last_switch_t = time.time()
                    switches += 1
                    stable = 0
                else:
                    # 关键：等帧边界再写，切换点落在两帧之间，不会撕裂。
                    # 超时 = 视频流停了，这次跳过，但不要抛出去：脚本挂掉就没有
                    # 收尾行，日志会被误判成"没跑完"。
                    try:
                        regs.wait_frame_boundary()
                    except TimeoutError as e:
                        log("警告：等帧边界超时（%s），这次切换跳过" % e)
                        stable = 0
                    else:
                        regs.set_mode(mlp)
                        extra = ""
                        if adaptive:
                            if param_target is not None:
                                p_now, p_why = param_target, "空间决策"
                                regs.set_param(p_now)
                                last_param = p_now
                                extra = ", PARAM=%d (%s)" % (p_now, p_why)
                            else:
                                f_now = fmt_features(regs)
                                if f_now is not None:
                                    p_now, p_why = adaptive_mod.param_for(f_now, mlp)
                                    regs.set_param(p_now)
                                    last_param = p_now
                                    extra = ", PARAM=%d (%s)" % (p_now, p_why)
                        log("切换模式 %d -> %d (稳定 %d 次, FRAME_CNT=%d)%s"
                            % (current_mode, mlp, stable, regs.frame_cnt(), extra))
                        current_mode = mlp
                        last_switch_t = time.time()
                        switches += 1
                        stable = 0

            # ---- 诊断：心跳 + 流停了没有 + 画面一直没变 ------------------
            # 为什么要有这几行：板子上出现过「MLP_OUTPUT 一直是 0」的情况，
            # 光看这一行分不清是「画面真的黑」还是「链路卡住」。把特征和
            # FRAME_CNT 一起写进日志，事后翻日志就能定位（见 VERIFY.md）。
            now = time.time()
            if next_hb and now >= next_hb:
                next_hb = now + hb
                log_state(log, regs, "心跳 t=%.1fs MLP=%d 模式=%d"
                          % (now - t0, mlp, current_mode))
                if spatial and u_now is not None:
                    log("  空间 u=%.3f quads=%s"
                        % (u_now, tuple(int(v) for v in quads_now)))

            fc = regs.frame_cnt()
            if fc != frame_cnt:
                frame_cnt, frame_moved_t, stall_reported = fc, now, False
            elif not stall_reported and (now - frame_moved_t) > 2.0:
                stall_reported = True
                log("警告：FRAME_CNT 已经 %.1f 秒没动 —— 视频流停了，MLP 不会再更新"
                    % (now - frame_moved_t))

            f = fmt_features(regs)
            if f is not None:
                if f != feat:
                    feat, feat_since, feat_reported = f, now, False
                elif not feat_reported and (now - feat_since) > max(10.0, 3 * hb if hb else 10.0):
                    feat_reported = True
                    log("提示：特征 %s 已经 %.0f 秒没变 —— 画面没变（镜头挡死 / 全黑），"
                        "MLP 一直同一个值是正常的" % (f, now - feat_since))

            time.sleep(args.poll)
    except KeyboardInterrupt:
        log("收到 Ctrl+C，退出")

    if switches == 0:
        log("提示：这次一次都没切。常见原因：①当前画面被判成的类别就是当前 MODE_SEL"
            "（本来就一致，没啥可切）；②画面全黑 / 没变化，MLP 恒为同一个值 —— "
            "看上面「心跳」行里的特征有没有变。")
    log("共切换 %d 次，因 min_hold(%.1fs) 被挡下 %d 次，"
        "被置信度门限拒绝 %d 次，空间覆盖轮询 %d 次，空间保持轮询 %d 次，运行 %.1f 秒"
        % (switches, args.min_hold, suppressed, gate_rejects,
           spatial_overrides, spatial_holds, time.time() - t0))
    log.close()


if __name__ == "__main__":
    main()
