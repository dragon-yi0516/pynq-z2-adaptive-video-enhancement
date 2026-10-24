"""overlay / OV5640 / VDMA 的统一初始化。

所有阶段的 notebook 都调用这里的函数，避免每个 notebook 复制一大段初始化代码。

设计原则：
* 与硬件无关的部分（找路径）放在顶层，PC 上也能 import 本模块做路径测试。
* 与 PYNQ 有关的部分放在函数内部 import，这样 PC 上（没装 pynq）也能 import。
"""
import os
import sys
import time

VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720
VIDEO_BPP = 24

# ---------------------------------------------------------------------------
# 工程根目录：由本文件的真实位置推出来（在 <工程根>/lib/video_setup.py），
# 所以不管你把整个文件夹放在 /home/xu/... 还是 /home/xilinx/... 都能自己找到，
# notebook 里再也不用写死绝对路径。
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))     # <工程根>/lib
DEFAULT_ROOT = os.path.dirname(HERE)                  # <工程根>

BIT_NAME = "cv_ov5640.bit"

# overlay 可能出现在这几个位置，**按顺序**找。
#   第一项是“同一个工程里的 Vivado 输出目录”，
#   这样每次重建 bitstream 之后 notebook 会自动用新的那一个，
#   不需要再把 .bit/.hwh 拷到别的地方 —— 这就是“不挪文件”的关键。
OVERLAY_CANDIDATES = (
    (os.pardir, "bitstream"),
    ("overlay",),
    ("bitstream",),
    ("boards", "Pynq-Z2", "ov5640", "bitstream"),
)

# 让 `import lib.xxx` / `import ov5640` 在任何情况下都能用
if DEFAULT_ROOT not in sys.path:
    sys.path.insert(0, DEFAULT_ROOT)


def ensure_on_path(root):
    """把工程根目录加进 sys.path，使 import lib.xxx 可用。"""
    if root not in sys.path:
        sys.path.insert(0, root)
    return root


def project_root(root=None):
    """定位工程根目录。

    * 不传参数：用 lib/video_setup.py 自己的位置推出来的 DEFAULT_ROOT（最可靠）。
    * 传了参数：按传入值（保留这个入口是为了方便单元测试和临时指向别处）。
    """
    if root:
        return ensure_on_path(root)
    return ensure_on_path(DEFAULT_ROOT)


def find_overlay(root=None, bit_name=BIT_NAME):
    """返回 overlay .bit 的绝对路径；找不到就抛出可读的错误。"""
    root = project_root(root)
    for parts in OVERLAY_CANDIDATES:
        path = os.path.join(root, *parts, bit_name)
        if os.path.exists(path):
            return path
    tried = "\n".join(
        "  " + os.path.normpath(os.path.join(root, *parts, bit_name))
        for parts in OVERLAY_CANDIDATES
    )
    raise FileNotFoundError(
        "找不到 %s，尝试过以下位置：\n%s\n"
        "请把 Vivado 生成的 .bit/.hwh 放到 %s/overlay/ 下。"
        % (bit_name, tried, root)
    )


def load_overlay(root=None, bit_name=BIT_NAME, verbose=True):
    """加载 overlay 并打印 IP 列表，返回 Overlay 对象。"""
    from pynq import Overlay

    path = find_overlay(root, bit_name)
    if verbose:
        print("加载 overlay:", path)
    ol = Overlay(path)
    if verbose:
        print("IP 列表:", sorted(ol.ip_dict.keys()))
    return ol


def hwh_modules_from_file(hwh_path):
    """从任意 .hwh 文件里读出所有模块实例名。"""
    if not os.path.exists(hwh_path):
        return []
    names = []
    with open(hwh_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "<MODULE" not in line:
                continue
            key = 'INSTANCE="'
            pos = line.find(key)
            if pos < 0:
                continue
            rest = line[pos + len(key):]
            end = rest.find('"')
            if end > 0:
                names.append(rest[:end])
    return sorted(set(names))


def hwh_find_modules(root=None, bit_name=BIT_NAME):
    """从工程 overlay 目录里的 .hwh 读出所有模块名。

    为什么需要它：PYNQ 的 ``ol.ip_dict`` 只列出**有地址**的 IP。
    像阶段 1 里还没有 AXI-Lite 接口的 ``axis_video_proc_0``，
    不会出现在 ip_dict 里，但它在 .hwh 里是存在的。
    所以“IP 到底有没有被综合进去”要用这个函数来看。
    """
    path = find_overlay(root, bit_name)
    return hwh_modules_from_file(os.path.splitext(path)[0] + ".hwh")


def hwh_has_module(name, root=None, bit_name=BIT_NAME):
    """判断某个模块名是否出现在 .hwh 里。"""
    return name in hwh_find_modules(root, bit_name)


def init_camera(ol, verbose=True, settle=0.2, retries=4):
    """配置 OV5640（SCCB/I2C），返回 AxiIIC 对象。

    为什么要 settle + retries（阶段 8 的后台脚本就是在这里挂的）：

    往 PL 重新下载 bitstream 时，这个设计里摄像头的复位脚是从 PL 出来的，
    于是相机被复位一次。OV5640 复位后要过一小会儿 SCCB 才会应答；如果马上
    就写那 253 个寄存器，第一笔就 NAK，PYNQ 直接抛
    ``RuntimeError: Could not send I2C data``。

    同理，另一个进程（notebook 内核）如果还持着同一个 overlay / 同一个
    axi_iic_0，也可能让某一笔事务失败。所以这里：

      1. 先等 settle 秒（默认 0.2s）让相机起来；
      2. 整段 253 个寄存器最多重试 retries 次，每次重试都重新建 AxiIIC 实例，
         失败之间 sleep 0.2s。

    实测：不重试时后台进程必挂；加了两道保险之后能自己恢复。
    """
    from pynq.lib.iic import AxiIIC

    from lib.ov5640.ov5640_config import ov5640_config

    if "axi_iic_0" not in ol.ip_dict:
        raise RuntimeError("overlay 里没有 axi_iic_0，无法配置摄像头")

    if settle:
        time.sleep(settle)

    camera_addr = 0x3C
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            iic = AxiIIC(ol.ip_dict["axi_iic_0"])
            for reg, val in ov5640_config:
                iic.send(camera_addr, bytes([(reg >> 8) & 0xFF, reg & 0xFF, val]), 3)
            if verbose:
                print("OV5640 配置完成（%d 个寄存器）" % len(ov5640_config))
            return iic
        except Exception as e:      # RuntimeError("Could not send I2C data") 等
            last_err = e
            # 失败信息无论 verbose 都要打：后台脚本就是靠它才知道"其实重试过"
            print("! OV5640 配置第 %d/%d 次失败：%s" % (attempt, retries, e))
            time.sleep(0.2)

    raise RuntimeError("OV5640 配置失败（试了 %d 次）：%s" % (retries, last_err))


def init_demosaic(ol, width=VIDEO_WIDTH, height=VIDEO_HEIGHT, verbose=True):
    """启动 Bayer -> RGB 去马赛克。"""
    if "v_demosaic_0" not in ol.ip_dict:
        raise RuntimeError("overlay 里没有 v_demosaic_0")
    demosaic = ol.v_demosaic_0
    demosaic.write(0x10, width)
    demosaic.write(0x18, height)
    demosaic.write(0x28, 1)      # auto restart
    demosaic.write(0x00, 0x81)   # start
    if verbose:
        print("v_demosaic 启动 (%dx%d)" % (width, height))
    return demosaic


def stop_all_channels(vdma0, vdma1):
    """停掉四个 VDMA 通道。

    换 overlay 或重开 notebook 前必须先停：残留的 DMA 会继续写 DDR，
    轻则花屏，重则把新 overlay 的地址空间写坏。
    """
    for ch in (vdma0.writechannel, vdma0.readchannel,
               vdma1.writechannel, vdma1.readchannel):
        try:
            if ch.running:
                ch.stop()
        except Exception:
            pass


def shut_down(*args, **kwargs):
    """收尾用：把 VDMA 通道停掉。notebook 最后一格写这个最省事。

    三种写法都能用（自动识别传进来的是 overlay 还是 vdma）：

        vs.shut_down(ol)
        vs.shut_down(vdma0, vdma1)
        vs.shut_down()

    为什么要这一步：残留的 DMA 会继续往 DDR 写，下一次加载 overlay / 重开
    notebook 时容易出现花屏甚至地址踩踏。演示前收尾一定要做。
    """
    objs = list(args) + list(kwargs.values())
    vdmas = []
    for o in objs:
        if o is None:
            continue
        if hasattr(o, "readchannel") and hasattr(o, "writechannel"):
            vdmas.append(o)
        elif hasattr(o, "ip_dict"):
            for name in ("axi_vdma_0", "axi_vdma_1"):
                if name in o.ip_dict:
                    try:
                        vdmas.append(getattr(o, name))
                    except Exception:
                        pass
    for v in vdmas:
        for ch in (v.writechannel, v.readchannel):
            try:
                if ch.running:
                    ch.stop()
            except Exception:
                pass
    return len(vdmas)


def init_vdma(ol, verbose=True):
    """返回 (vdma0, vdma1, VideoMode) 三元组。"""
    from pynq.lib.video import VideoMode

    for name in ("axi_vdma_0", "axi_vdma_1"):
        if name not in ol.ip_dict:
            raise RuntimeError("overlay 里没有 %s" % name)
    vdma0 = ol.axi_vdma_0
    vdma1 = ol.axi_vdma_1
    mode = VideoMode(VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_BPP)
    if verbose:
        print("VDMA 就绪, VideoMode = %dx%d %dbit"
              % (mode.width, mode.height, mode.bits_per_pixel))
    return vdma0, vdma1, mode


def bring_up(root=None, bit_name=BIT_NAME, verbose=True, manual_exposure=None,
             skip_camera=False):
    """一步到位：加载 overlay + 配置摄像头 + 启动去马赛克 + 拿到 VDMA。

    返回 (ol, iic, demosaic, vdma0, vdma1, mode)。

    manual_exposure
        可选。给「密闭演示盒 + 可控光源」用：传一个 dict 就把 OV5640
        从自动曝光切到手动曝光，例如

            ol, iic, ... = vs.bring_up(ROOT, manual_exposure=dict(exposure=512, gain=0x10))

        为什么需要：默认 AEC/AGC 全开（0x3503=0x00），盒子里调暗灯时
        摄像机会自动把曝光拉回去，画面亮度不变、MLP 判不出暗光。
        切手动之后亮度就完全由灯决定。

        不传（默认 None）时行为**完全不变**，还是自动曝光。
        详见 lib/exposure.py 和 docs/04_demo_box.md。

    skip_camera
        为 True 时不重配摄像头（notebook 已经写过 253 个寄存器时用），
        避免两个进程抢 I2C 导致 "Could not send I2C data"。
        iic 仍然返回，manual_exposure 也仍然可以生效。
    """
    from lib import dma  # noqa: F401  注册 AxiVDMA 驱动，必须有这一句

    ol = load_overlay(root, bit_name, verbose)
    if skip_camera:
        iic = getattr(ol, "axi_iic_0", None)
        if verbose:
            print("跳过摄像头重配（--no-camera）：沿用 notebook 已经写好的寄存器")
    else:
        iic = init_camera(ol, verbose)
    if manual_exposure is not None and iic is not None:
        from lib import exposure
        exposure.set_manual(iic, **manual_exposure)
    demosaic = init_demosaic(ol, verbose=verbose)
    vdma0, vdma1, mode = init_vdma(ol, verbose)
    return ol, iic, demosaic, vdma0, vdma1, mode
