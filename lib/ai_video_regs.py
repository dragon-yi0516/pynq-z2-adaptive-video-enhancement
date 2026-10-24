"""ai_video 自定义 IP 的寄存器封装。

设计原则：
1. 本模块不 import pynq，所以在 PC 上用普通 Python 就能导入、单元测试。
   板子上把 PYNQ 的 DefaultIP 对象传进来即可。
2. 地址常量与 docs/01_register_map.md 一一对应，改一处必须同时改另一处。
"""
import math
import time

# ---------------------------------------------------------------------------
# 寄存器偏移（权威定义见 docs/01_register_map.md）
# ---------------------------------------------------------------------------
MLP_OUTPUT = 0x00
MODE_SEL = 0x04
STATUS = 0x08
VERSION = 0x0C
LUMA_SUM = 0x10
LUMA_SQ_SUM = 0x14
GRAD_SUM = 0x18
FRAME_CNT = 0x1C
VBLANK_CNT = 0x20
LUMA_SQ_SUM_HI = 0x24
PIXEL_CNT = 0x28
# 诊断用：MLP 握手计数（阶段 6 修订 02 起）。用来定位「MLP_OUTPUT 一直是 0」
MLP_START_CNT = 0x2C
MLP_DONE_CNT = 0x30

# ---- 阶段 12 新增 ----------------------------------------------------------
# PARAM：三个处理模式共用的**连续强度参数**（0~255），帧边界生效。
#   含义（详见 stage12_adaptive/hdl/axis_video_proc.v 的注释）：
#     mode 0 增益     倍数 = PARAM/128；128=×1.0，192=×1.5，255=×1.99
#     mode 1 对比拉伸 最多 ±(PARAM*127/512) 灰度；128→±32，255→±63
#     mode 2 锐化     强度 = PARAM/256；0=直通，128=|Δ|/2，255≈|Δ|
PARAM = 0x34
# 四象限亮度统计（读到的是该象限 sumY >> 16，16 位）
QUAD_TL_TR = 0x38      # [31:16]=右上  [15:0]=左上
QUAD_BL_BR = 0x3C      # [31:16]=右下  [15:0]=左下

# 阶段 12 的 HDL 版本号（VERSION 最低字节 = 阶段号）
STAGE_ADAPTIVE = 12

# 阶段 13：分屏输出（屏幕左半 = 原始、右半 = 处理后的同一区域）。
# 开关借用 MODE_SEL 的 bit7 —— bit7 不参与模式选择（mode 仍取 [1:0]），
# 所以加它不影响原有功能，也不用新增寄存器。
STAGE_SPLIT = 13
SPLIT_BIT = 0x80

# VERSION 寄存器编码：0x0001_RRSS
#   高 16 位 = 家族号 0x0001；RR = 修订号；SS = 阶段号
#   例：0x0001_0206 = 家族1 修订02 阶段6
# 这样在 Jupyter 里一眼就能看出板子上跑的是哪一版硬件，
# 避免“改了 HDL 却忘了重新生成 bitstream”这种最常见的事故。
VERSION_FAMILY = 0x00010000
VERSION_MASK = 0xFFFF0000
EXPECTED_VERSION = VERSION_FAMILY   # 向后兼容的别名

STATUS_DONE = 1 << 0
STATUS_VBLANK = 1 << 1
STATUS_STATS_OK = 1 << 2

# ---------------------------------------------------------------------------
# MLP 输入的三个特征怎么来的（重要，必须和 HDL/HLS 完全一致）
#
# FPGA 里“零成本”能做的只有加法和移位。所以 MLP 的输入就用三个累加值右移得到。
# 1280x720 一帧有 921600 个像素，于是：
#     f1 = LUMA_SUM    >> 20   = luma      * 0.879     典型 85~110
#     f2 = LUMA_SQ_SUM >> 28   = (luma²+var) * 0.00343 典型 33~60
#     f3 = GRAD_SUM    >> 16   = 平均|ΔY|  * 14.06     典型 16~48
#
# 移位怎么定的：**按典型值定，不是按最大值定**。
#   三者的物理量差别很大（luma 0~255、luma²+var 0~65025、平均梯度只有 0~5），
#   如果都按“最大值归一化”，梯度那一路会被压成 0/1/2 这种没有分辨率的整数
#   —— 真机第一次采集就踩了这个坑：f_grad 恒等于 2（std 0.00），整个特征废掉。
#   所以 f3 用更小的移位（16），让典型值落到几十，和另外两个同量级，
#   同时最大值 255*14.06 ≈ 3586 也远小于 int16 上限，不会溢出。
#
# 三者典型值都在几十~几百，MLP 的 Q8.8 权重才不会量化到 0。
#
# 物理量 luma/contrast/sharpness 仍然用 features_from_raw() 算出来给人工检查用，
# 但它们**不是** MLP 的输入。二者不要混用，否则训练和板上推理会对不上。
#
# 注意：阶段 3 的移位是在**这一份 Python 里**做的（HDL 只输出原始累加值）；
#       阶段 6/7 的移位是在 HDL 里做的（axis_video_proc.v 的 reg_f3_r）。
#       改这里必须同步改 stage06/stage07 的 HDL，否则板上推理和训练输入不一致。
# ---------------------------------------------------------------------------
MLP_FEAT_SHIFT = (20, 28, 16)


class VersionMismatch(RuntimeError):
    """overlay 里挂的 IP 版本和本工程期望的不一致。"""


class AiVideoRegs:
    """把 PYNQ 的 IP 对象包一层，提供语义化接口。

    Parameters
    ----------
    ip : object
        需要提供 ``read(offset) -> int`` 和 ``write(offset, value)``。
        PYNQ 的 ``DefaultIP``（例如 ``ol.axis_video_proc_0``）本身就满足；
        单元测试时可以传一个假的字典对象（见 test_regs.py）。
    check_version : bool
        初始化时是否校验 VERSION。用假对象做测试时设为 False。
    """

    def __init__(self, ip, check_version=True):
        self.ip = ip
        if check_version:
            self.check_version()

    # -- 基础读写 ---------------------------------------------------------
    def rd(self, offset):
        return int(self.ip.read(offset)) & 0xFFFFFFFF

    def wr(self, offset, value):
        self.ip.write(offset, int(value) & 0xFFFFFFFF)

    # -- 版本 -------------------------------------------------------------
    def version(self):
        return self.rd(VERSION)

    def check_version(self):
        v = self.version()
        if (v & VERSION_MASK) != VERSION_FAMILY:
            raise VersionMismatch(
                "VERSION 不匹配: 读到 0x%08X，期望家族号 0x%08X。"
                "说明 overlay 里没有挂上本工程的 IP，或者挂的是旧版本。"
                % (v, VERSION_FAMILY)
            )
        self.stage = v & 0xFF
        return v

    def version_stage(self):
        """返回 VERSION 里记录的阶段号（1/2/3/6/7…）。"""
        return self.version() & 0xFF

    def version_revision(self):
        """返回 VERSION 里记录的修订号（同一个阶段内的第几版）。"""
        return (self.version() >> 8) & 0xFF

    # -- MLP 诊断计数 ------------------------------------------------------
    def mlp_start_cnt(self):
        """硬件发出过几次 MLP 启动脉冲（0x2C）。"""
        return self.rd(MLP_START_CNT)

    def mlp_done_cnt(self):
        """硬件收到过几次 MLP 完成信号（0x30）。"""
        return self.rd(MLP_DONE_CNT)

    # -- 控制 -------------------------------------------------------------
    def mode_sel(self):
        return self.rd(MODE_SEL) & 0x3

    def set_mode(self, mode):
        # 只改低 2 位，**保留 bit7（阶段 13 的分屏开关）**——
        # 早期写成直接写 (mode & 0x3)，会把分屏一起冲掉。
        cur = self.rd(MODE_SEL)
        self.wr(MODE_SEL, (cur & SPLIT_BIT) | (int(mode) & 0x3))

    # -- 阶段 13：分屏开关（MODE_SEL 的 bit7）------------------------------
    def has_split(self):
        """阶段 13 及以上才有分屏输出。"""
        return self.version_stage() >= STAGE_SPLIT

    def split(self):
        return (self.rd(MODE_SEL) >> 7) & 0x1

    def set_split(self, on):
        """开/关分屏。注意 set_mode() 只写低 2 位，不会误关分屏。"""
        cur = self.rd(MODE_SEL)
        self.wr(MODE_SEL, (cur | SPLIT_BIT) if on else (cur & ~SPLIT_BIT))

    # -- 阶段 12：连续参数 + 四象限 ----------------------------------------
    def has_param(self):
        """阶段 12 及以上才有 PARAM / 象限寄存器。"""
        return self.version_stage() >= STAGE_ADAPTIVE

    def param(self):
        return self.rd(PARAM) & 0xFF

    def set_param(self, value):
        self.wr(PARAM, int(value) & 0xFF)

    def quads(self):
        """返回 (左上, 右上, 左下, 右下)，单位是该象限的 sumY>>16。"""
        up = self.rd(QUAD_TL_TR)
        dn = self.rd(QUAD_BL_BR)
        return (up & 0xFFFF, (up >> 16) & 0xFFFF,
                dn & 0xFFFF, (dn >> 16) & 0xFFFF)

    def spatial_unevenness(self):
        """空间不均匀度 = (最亮象限 - 最暗象限) / 四象限均值。

        用来区分「整体亮」和「局部亮（逆光 / 侧光）」：
          * 照明均匀      -> 接近 0
          * 逆光 / 侧光   -> 明显大于 0
        硬件不是阶段 12（没有象限寄存器）时返回 None。
        """
        if not self.has_param():
            return None
        q = self.quads()
        avg = sum(q) / 4.0
        if avg <= 0:
            return 0.0
        return (max(q) - min(q)) / avg

    def mlp_output(self):
        return self.rd(MLP_OUTPUT) & 0x3

    def status(self):
        return self.rd(STATUS)

    def frame_cnt(self):
        return self.rd(FRAME_CNT)

    def vblank_cnt(self):
        return self.rd(VBLANK_CNT)

    # -- 特征 -------------------------------------------------------------
    def raw_stats(self):
        """返回上一整帧的原始累加值（硬件不做除法的原因见 docs/02）。"""
        return {
            "luma_sum": self.rd(LUMA_SUM),
            "luma_sq_sum": (self.rd(LUMA_SQ_SUM_HI) << 32) | self.rd(LUMA_SQ_SUM),
            "grad_sum": self.rd(GRAD_SUM),
            "pixel_cnt": self.rd(PIXEL_CNT),
        }

    @staticmethod
    def features_from_raw(stats):
        """把原始累加值换算成 (luma, contrast, sharpness)。

        训练（notebook 03/04）和板端采集（notebook 02）必须都调用这一个函数，
        否则训练和推理的输入分布会不一致。
        """
        n = stats["pixel_cnt"] or 1
        luma = stats["luma_sum"] / n
        luma2 = stats["luma_sq_sum"] / n
        contrast = math.sqrt(max(luma2 - luma * luma, 0.0))
        sharpness = stats["grad_sum"] / n
        return luma, contrast, sharpness

    def features(self):
        return self.features_from_raw(self.raw_stats())

    @staticmethod
    def mlp_features_from_raw(stats):
        """硬件真正喂给 MLP 的三个整数特征（见上面 MLP_FEAT_SHIFT 的说明）。"""
        shifts = MLP_FEAT_SHIFT
        return (
            int(stats["luma_sum"]) >> shifts[0],
            int(stats["luma_sq_sum"]) >> shifts[1],
            int(stats["grad_sum"]) >> shifts[2],
        )

    def mlp_features(self):
        return self.mlp_features_from_raw(self.raw_stats())

    # -- 同步 -------------------------------------------------------------
    def wait_frame_boundary(self, timeout=2.0):
        """阻塞到下一个帧边界（tuser）到来。

        这条流水线没有独立 vsync，帧边界就是唯一安全的切换点，
        详见 docs/01_register_map.md。
        """
        v0 = self.vblank_cnt()
        t0 = time.time()
        while self.vblank_cnt() == v0:
            if time.time() - t0 > timeout:
                raise TimeoutError("等待帧边界超时：VBLANK_CNT 一直没变化")
        return self.vblank_cnt()

    def wait_new_frame(self, timeout=2.0):
        f0 = self.frame_cnt()
        t0 = time.time()
        while self.frame_cnt() == f0:
            if time.time() - t0 > timeout:
                raise TimeoutError("等待新帧超时：FRAME_CNT 一直没变化")
        return self.frame_cnt()

    # -- 批量采集 ---------------------------------------------------------
    def collect(self, label, n=200, timeout=20.0, poll_sleep=0.0, verbose=False,
                accept=None):
        """每来一帧采一次特征，共采 n 帧。

        返回 ``[[luma, contrast, sharpness, label], ...]``。

        poll_sleep 是每轮轮询之间的 sleep，板子上建议给 1e-4 ~ 1e-3，
        避免把 CPU 占满导致 HDMI 掉帧。

        accept
            可选。``accept(f1, f2, f3) -> bool``，返回 False 的帧会被**丢掉**
            （不计入 n、也不写进 CSV）。

            为什么需要它（实测教训）：在盒子里手动移动目标物、让类内有变化时，
            画面会短暂跑出这一类的目标带 —— 实测常规档那一轮漂到了 f_luma=58，
            正好落进逆光的区间，于是两类的分布糊在一起（类间 0.6σ，MLP 学不出来）。
            加上带通滤波之后可以放心"动"，只有落在带内的帧才被记录，
            两类的重叠就自动避免了。

            丢掉的帧数记在 ``self.last_dropped`` 里，便于判断"动得是不是太大"。
        """
        rows = []
        dropped = 0
        last = self.frame_cnt()
        t0 = time.time()
        while len(rows) < n:
            now = self.frame_cnt()
            if now != last:
                last = now
                # CSV 里存的就是 MLP 的输入特征，训练/推理自然不会对不上
                f1, f2, f3 = self.mlp_features()
                if accept is None or accept(f1, f2, f3):
                    rows.append([f1, f2, f3, int(label)])
                    if verbose and (len(rows) % 50 == 0):
                        print("  已采集 %d/%d 帧%s"
                              % (len(rows), n,
                                 ("（已丢弃 %d 帧）" % dropped) if dropped else ""))
                else:
                    dropped += 1
            if poll_sleep:
                time.sleep(poll_sleep)
            if time.time() - t0 > timeout:
                raise TimeoutError(
                    "采集超时：%.0f 秒内只收到 %d/%d 帧（另外丢掉了 %d 帧）。\n"
                    "如果丢弃数很大，说明画面大部分时间不在这一类的目标带内 —— "
                    "先调好摆法/光照，再重跑；"
                    "如果丢弃数是 0 而收帧也慢，检查视频通路是否在跑（FRAME_CNT 是否在递增）。"
                    % (timeout, len(rows), n, dropped)
                )
        self.last_dropped = dropped
        return rows

    def collect_spatial(self, label, n=200, round_idx=0, timeout=20.0,
                        poll_sleep=0.0, verbose=False, accept=None):
        """每帧采 (f1,f2,f3,label,round,q_tl,q_tr,q_bl,q_br)。

        为什么单独加一个方法：原来的 collect() 只读 3 个全局特征，
        四象限寄存器 0x38/0x3C 根本没有进 CSV，所以后面的“空间决策”
        没有数据可标定。这里把四块 sumY>>16 一起存下来，训练仍然只用
        f1~f3，模型和 bitstream 都不变。

        返回的每行：
            [f_luma, f_luma2, f_grad, label, round,
             q_tl, q_tr, q_bl, q_br]
        与 lib/features_io.py 的 9 列格式一致。

        accept 与 collect() 同义：返回 False 的帧丢弃，不计入 n。
        """
        if not self.has_param():
            raise RuntimeError(
                "当前 overlay 没有四象限寄存器（需要阶段 12+）；"
                "请用 stage12_adaptive/stage13_split 的 bit，"
                "或者用 collect() 只采 3 个全局特征。"
            )
        rows = []
        dropped = 0
        last = self.frame_cnt()
        t0 = time.time()
        while len(rows) < n:
            now = self.frame_cnt()
            if now != last:
                last = now
                f1, f2, f3 = self.mlp_features()
                if accept is None or accept(f1, f2, f3):
                    q = self.quads()
                    if q is None:
                        raise RuntimeError("四象限寄存器读回 None，检查 overlay 版本")
                    rows.append([
                        f1, f2, f3, int(label), int(round_idx),
                        int(q[0]), int(q[1]), int(q[2]), int(q[3]),
                    ])
                    if verbose and (len(rows) % 50 == 0):
                        print("  已采集 %d/%d 帧（含四象限）" % (len(rows), n))
                else:
                    dropped += 1
            if poll_sleep:
                time.sleep(poll_sleep)
            if time.time() - t0 > timeout:
                raise TimeoutError(
                    "四象限采集超时：%.0f 秒内只收到 %d/%d 帧（另外丢掉了 %d 帧）。\n"
                    "如果丢弃数很大，说明画面大部分时间不在这一类的目标带内；"
                    "如果丢弃数是 0 而收帧也慢，检查视频通路是否在跑（FRAME_CNT 是否递增）。"
                    % (timeout, len(rows), n, dropped)
                )
        self.last_dropped = dropped
        return rows
