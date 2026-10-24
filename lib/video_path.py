"""视频通路的启动 / 抓帧 / 显示封装。

把这一段单独抽出来，是因为阶段 0/1/2/3/6/7/8 都要反复用它。
所有 notebook 都调用这里的函数，行为一致、只调一处。

硬件通路（与 README.md 一致）：
    OV5640 -> v_demosaic -> [axis_video_proc] -> VDMA0(S2MM) -> DDR
           -> VDMA0(MM2S) -> VDMA1(S2MM) -> DDR
           -> VDMA1(MM2S) -> v_axi4s_vid_out -> rgb2dvi -> HDMI
"""
import numpy as np


# ---------------------------------------------------------------------------
# XRT 分不出 DMA 缓冲时该说什么。放在这里，是为了让所有用到采集/显示的
# notebook 和脚本共用同一份"处理阶梯" —— 这个错在板子上出现过好几次，
# 每次都要重新讲一遍太费劲。
# ---------------------------------------------------------------------------
ALLOCATE_FAIL_LADDER = """
!! XRT 分不出 DMA 缓冲了（Allocate failed: 4294967295）—— 板子的 XRT 缓冲池被占满/搞脏了。
   按这个顺序处理（**别一上来就重启板子**）：
     1) 先把**其它 notebook 的内核**关掉：Jupyter 左边点那个 notebook -> Shut Down Kernel。
        关键：每个内核都自己占着一份 DMA 缓冲，只有内核进程退出、驱动才会回收它们。
        看看现在有几个：`pgrep -af ipykernel`
     2) 本 notebook：Kernel -> Restart Kernel，然后**从上往下重跑**（别只重跑出错那一格）。
     3) 还报同样的错：`sudo reboot`（约 40 秒）。
   想留证据：`bash tools/pl_cleanup.sh`（打印残留进程 / 内存 / CMA / dmesg 尾部）
   注意：`ol.free()` / `s5.release()` 这类"手动还缓冲"**不再当作急救手段** ——
        两次实测都显示"free 完之后再分配"更容易失败；处理不了就重启内核。
"""


def frame_to_rgb(frame, flip=True):
    """把 VDMA 抓到的 BGR 帧转成 RGB，并做一次水平镜像（与摄像头朝向一致）。"""
    from PIL import Image

    img = frame
    if img.ndim == 3 and img.shape[2] == 3:
        pil = Image.fromarray(img)
        g, b, r = pil.split()
        img = np.array(Image.merge("RGB", (r, g, b)))
    if flip:
        img = np.flip(img, axis=1)
    return img


def start_capture(vdma0, mode):
    """只启动采集通道（VDMA0 的 S2MM），用于在 Jupyter 里抓帧。"""
    if vdma0.readchannel.running:
        vdma0.readchannel.stop()
    vdma0.readchannel.mode = mode
    try:
        vdma0.readchannel.start()
    except RuntimeError as exc:
        if "Allocate failed" in str(exc):
            print(ALLOCATE_FAIL_LADDER)
        raise


def capture_frame(vdma0, rgb=False):
    """抓一帧。返回 numpy 数组；rgb=True 时顺带做 BGR->RGB 和镜像。"""
    frame = np.array(vdma0.readchannel.readframe())
    if rgb:
        frame = frame_to_rgb(frame)
    return frame


def start_hdmi_passthrough(vdma0, vdma1, mode):
    """纯硬件直通显示（推荐，不占 CPU）。

    关键：一定要先 tie() 再 start()，顺序反了自动转发不会生效。
    这条链是 VDMA0 采集 -> VDMA0 输出 -> VDMA1 采集 -> VDMA1 输出 -> HDMI。
    """
    for ch in (vdma0.writechannel, vdma0.readchannel,
               vdma1.writechannel, vdma1.readchannel):
        try:
            if ch.running:
                ch.stop()
        except Exception:
            pass
        ch.mode = mode

    vdma0.readchannel.tie(vdma0.writechannel)
    vdma1.readchannel.tie(vdma1.writechannel)

    try:
        vdma0.writechannel.start()
        vdma0.readchannel.start()
        vdma1.writechannel.start()
        vdma1.readchannel.start()
    except RuntimeError as exc:
        # 四个通道里任意一个起不来都可能是这个错 —— 打印同一份处理阶梯，再抛出去
        # （抛出去是为了不掩盖问题：notebook 里能看到是哪一个通道挂的）。
        if "Allocate failed" in str(exc):
            print(ALLOCATE_FAIL_LADDER)
        raise


def start_display_bridge(vdma0, vdma1, mode):
    """CPU 桥接显示（备用）：只用 VDMA1 的 MM2S 推 HDMI。

    用途：当硬件直通不工作时，用它来判断“显示通道本身”是否正常。
    """
    for ch in (vdma0.writechannel, vdma0.readchannel,
               vdma1.writechannel, vdma1.readchannel):
        try:
            if ch.running:
                ch.stop()
        except Exception:
            pass
    vdma0.readchannel.mode = mode
    vdma1.writechannel.mode = mode
    try:
        vdma0.readchannel.start()
        vdma1.writechannel.start()
    except RuntimeError as exc:
        if "Allocate failed" in str(exc):
            print(ALLOCATE_FAIL_LADDER)
        raise


def display_frames(vdma0, vdma1, n=300):
    """抓一帧写一帧到 HDMI，跑 n 帧。"""
    for _ in range(n):
        vdma1.writechannel.writeframe(vdma0.readchannel.readframe())
    return n
