"""OV5640 曝光 / 增益控制 —— 给「密闭演示盒 + 可控光源」用。

为什么需要这个文件
------------------
默认寄存器表 lib/ov5640/ov5640_config.py 里有一行：

    [0x3503, 0x00]        # AEC（自动曝光）+ AGC（自动增益）全开

在密闭盒子里调光的时候，摄像机会自动把曝光时间 / 增益拉上去补偿，
画面亮度被「顶回」正常水平 —— 于是 MLP 看到的还是「常规」场景，
判不出暗光。

这不是猜的：实机遮镜头时 f_luma 最低只降到 27（目标 10），
就是没遮到「AEC 满补偿也救不回来」的程度。想调的「中等偏暗」
那一段根本调不出来，盒子做得再好也没用。

切到手动曝光之后，画面亮度就**完全由你的灯决定**，三档可以精确标定、
重复性接近 100%。

用法
----
notebook 里 bring_up() 之后加一行就进盒子模式：

    from lib import exposure
    exposure.set_manual(iic, exposure=512, gain=0x10)

退出盒子模式（恢复自动曝光）：

    exposure.set_auto(iic)

也可以直接用 bring_up 的参数（见 lib/video_setup.py）：

    ol, iic, ... = vs.bring_up(ROOT, manual_exposure=dict(exposure=512, gain=0x10))

本模块**只写寄存器**，不改 ov5640_config.py。所以普通演示（自动曝光）
完全不受影响，两种模式随时切换。

寄存器编码（OV5640 手册）
------------------------
曝光：20 位，单位是「行」（1 行 = 1 个行周期）
    0x3500[3:0] = 曝光[19:16]，0x3501 = 曝光[15:8]，0x3502 = 曝光[7:0]
增益：10 位
    0x350a[1:0] = 增益[9:8]，0x350b = 增益[7:0]

增益码和实际倍数的换算各资料说法不一致，所以**别照抄倍数**，
用 tools/box_calibration.ipynb 里的扫描格实测标定。
"""

CAMERA_ADDR = 0x3C              # 与 lib/video_setup.py 里的 camera_addr 保持一致

# 0x3503: bit1 = AEC 手动, bit0 = AGC 手动
#   0x00 = 全自动（默认）
#   0x03 = 全手动（盒子模式）
REG_AEC_AGC_ENABLE = 0x3503

REG_EXPOSURE_HI = 0x3500        # 曝光[19:16]，只用低 4 位
REG_EXPOSURE_MID = 0x3501       # 曝光[15:8]
REG_EXPOSURE_LO = 0x3502        # 曝光[7:0]

REG_GAIN_HI = 0x350A            # 增益[9:8]，只用低 2 位
REG_GAIN_LO = 0x350B            # 增益[7:0]

# 起始建议值。曝光 512 行在 VTS≈750 时约占 68% 的行时间；
# 增益 0x10 是常见表里的最小档。都不合适就用扫描格改。
DEFAULT_EXPOSURE = 512
DEFAULT_GAIN = 0x10

EXPOSURE_MAX = 0xFFFFF          # 20 位
GAIN_MAX = 0x3FF                # 10 位


# ---- 本工程实测标定的工作点（采集 / 演示 / 对比实验都用它）------------------
# 2026-10-13 用 tools/box_calibration.ipynb 的扫描格标出来的：
#   736 行（VTS=740，留 4 行余量）+ 增益 0x20  ->  常规档 luma ≈ 122（目标 124）
# 为什么单独放在这里：训练数据、阶段 6/7/8 的验证/演示、步骤 5 的对比实验必须用
# **同一档**。否则 AEC/AGC 一介入、噪声一变，f_grad 就整体偏移十几个点，
# 三类中心和训练分布全对不上（实测：自动曝光下常规档读 (109,57,36)，
# 而训练中心是 (96.5,68.6,29.9)，逆光档干脆一次都判不出来）。
# 重新采集过就改这里，并把 docs/04_demo_box.md 的记录表一起更新。
WORKPOINT = {"exposure": 736, "gain": 0x20}


def _write(iic, reg, val):
    """写一个 16 位地址的寄存器（和 video_setup.init_camera 用的是同一种事务）。"""
    iic.send(CAMERA_ADDR, bytes([(reg >> 8) & 0xFF, reg & 0xFF, val & 0xFF]), 3)


def _read(iic, reg):
    """尽力读一个寄存器；读不到返回 None。

    为什么不是必须的：真正要看的量是硬件算出来的 f_luma（见
    lib/ai_video_regs.py），读回寄存器只是辅助确认。
    OV5640 支持「先写寄存器地址、再顺序读」，所以这里 send 2 字节地址
    之后再 receive 1 字节。个别 PYNQ 版本上这条路径可能不通，
    那也不影响使用 —— 用 f_luma 判断即可。
    """
    try:
        iic.send(CAMERA_ADDR, bytes([(reg >> 8) & 0xFF, reg & 0xFF]), 2)
        data = iic.receive(CAMERA_ADDR, 1)
        return data[0]
    except Exception:
        return None


def set_exposure(iic, lines):
    """设置曝光（单位：行）。写 20 位，分三个寄存器。"""
    lines = int(lines)
    if not (0 <= lines <= EXPOSURE_MAX):
        raise ValueError("曝光 %d 超出范围 0~%d" % (lines, EXPOSURE_MAX))
    _write(iic, REG_EXPOSURE_HI, (lines >> 16) & 0x0F)
    _write(iic, REG_EXPOSURE_MID, (lines >> 8) & 0xFF)
    _write(iic, REG_EXPOSURE_LO, lines & 0xFF)
    return lines


def set_gain(iic, code):
    """设置增益（10 位码，不是倍数）。"""
    code = int(code)
    if not (0 <= code <= GAIN_MAX):
        raise ValueError("增益码 %d 超出范围 0~%d" % (code, GAIN_MAX))
    _write(iic, REG_GAIN_HI, (code >> 8) & 0x03)
    _write(iic, REG_GAIN_LO, code & 0xFF)
    return code


def set_manual(iic, exposure=DEFAULT_EXPOSURE, gain=DEFAULT_GAIN, verbose=True):
    """切到手动曝光 + 手动增益（盒子模式）。

    顺序很重要：先把曝光/增益写好，**最后**再把 0x3503 切成手动，
    避免中间出现一帧用旧曝光值的画面。
    """
    set_exposure(iic, exposure)
    set_gain(iic, gain)
    _write(iic, REG_AEC_AGC_ENABLE, 0x03)
    if verbose:
        print("[exposure] 已切手动：曝光 = %d 行，增益码 = 0x%02X（0x3503 = 0x03）"
              % (exposure, gain))
        print("[exposure] 从这一帧起，画面亮度只由你的灯决定（不再自动补偿）")
    return exposure, gain


def set_auto(iic, verbose=True):
    """恢复自动曝光 / 自动增益（普通演示模式）。"""
    _write(iic, REG_AEC_AGC_ENABLE, 0x00)
    if verbose:
        print("[exposure] 已恢复自动曝光 / 自动增益（0x3503 = 0x00）")


def report(iic):
    """把当前曝光/增益状态打出来（读不回时只提示，不报错）。"""
    en = _read(iic, REG_AEC_AGC_ENABLE)
    hi = _read(iic, REG_EXPOSURE_HI)
    mid = _read(iic, REG_EXPOSURE_MID)
    lo = _read(iic, REG_EXPOSURE_LO)
    gh = _read(iic, REG_GAIN_HI)
    gl = _read(iic, REG_GAIN_LO)

    if en is None:
        print("[exposure] 读不回寄存器（正常现象）。用 f_luma 判断效果即可。")
        return None

    exp = None
    if None not in (hi, mid, lo):
        exp = ((hi & 0x0F) << 16) | (mid << 8) | lo
    gain = None
    if None not in (gh, gl):
        gain = ((gh & 0x03) << 8) | gl

    mode_txt = "手动" if (en & 0x03) == 0x03 else "自动"
    print("[exposure] 0x3503 = 0x%02X（%s）  曝光 = %s 行  增益码 = %s"
          % (en, mode_txt,
             exp if exp is not None else "?",
             ("0x%02X" % gain) if gain is not None else "?"))
    return en
