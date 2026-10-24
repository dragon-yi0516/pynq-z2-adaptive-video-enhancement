"""ai_video_regs 的离线单元测试（不需要 PYNQ、不需要板子）。

跑法：
    python lib/test_regs.py

验证三件事：
1. VERSION 校验：正确值通过，错误值报 VersionMismatch。
2. 特征换算：给定 sum / sumY2 / pixel_cnt，算出的 luma/contrast 是否正确。
3. collect()：按 FRAME_CNT 的变化采够指定帧数，标签正确。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.ai_video_regs import (  # noqa: E402
    AiVideoRegs,
    VersionMismatch,
    EXPECTED_VERSION,
    VERSION_FAMILY,
    VERSION,
    FRAME_CNT,
    LUMA_SUM,
    LUMA_SQ_SUM,
    LUMA_SQ_SUM_HI,
    GRAD_SUM,
    PIXEL_CNT,
)


class FakeIP:
    """最小可用的假 AXI-Lite 从设备。"""

    def __init__(self):
        self.regs = {VERSION: EXPECTED_VERSION}

    def read(self, off):
        return self.regs.get(off, 0)

    def write(self, off, val):
        self.regs[off] = int(val) & 0xFFFFFFFF


class AutoFrameIP(FakeIP):
    """每读一次 FRAME_CNT 就自增，用来模拟视频在跑。"""

    def __init__(self, step=1):
        FakeIP.__init__(self)
        self._f = 0
        self._step = step

    def read(self, off):
        if off == FRAME_CNT:
            self._f += self._step
            return self._f
        return FakeIP.read(self, off)


def test_version():
    regs = AiVideoRegs(FakeIP())
    assert regs.version() == EXPECTED_VERSION

    bad = FakeIP()
    bad.regs[VERSION] = 0xDEADBEEF          # 家族号不对
    try:
        AiVideoRegs(bad)
    except VersionMismatch:
        pass
    else:
        raise AssertionError("版本错误时应当抛 VersionMismatch")

    # 阶段号不同但家族号相同 -> 视为同一个 IP，应当通过
    other_stage = FakeIP()
    other_stage.regs[VERSION] = VERSION_FAMILY | 0x0007
    r = AiVideoRegs(other_stage)
    assert r.version_stage() == 7, r.version_stage()
    print("test_version OK")


def test_features():
    ip = FakeIP()
    # 4 个像素，亮度都是 100，但其中一个偏离 10 -> 标准差应为 10 * sqrt(3/4)? 见下
    # 这里用更直观的构造：4 个像素 Y = 110, 110, 90, 90 (均值 100)
    ys = [110, 110, 90, 90]
    ip.regs[PIXEL_CNT] = len(ys)
    ip.regs[LUMA_SUM] = sum(ys)
    ip.regs[LUMA_SQ_SUM] = sum(y * y for y in ys)
    ip.regs[LUMA_SQ_SUM_HI] = 0
    ip.regs[GRAD_SUM] = 40

    regs = AiVideoRegs(ip)
    luma, contrast, sharpness = regs.features()
    assert abs(luma - 100.0) < 1e-9, luma
    assert abs(contrast - 10.0) < 1e-9, contrast
    assert abs(sharpness - 10.0) < 1e-9, sharpness

    # 检查 48bit 拼接：sumY2 故意超过 32bit
    big = (1 << 32) + 12345
    ip.regs[LUMA_SQ_SUM_HI] = big >> 32
    ip.regs[LUMA_SQ_SUM] = big & 0xFFFFFFFF
    assert regs.raw_stats()["luma_sq_sum"] == big
    print("test_features OK")


def test_collect():
    ip = AutoFrameIP()
    # 直接构造出想要的 MLP 特征：f1=100, f2=200, f3=50
    f1, f2, f3 = 100, 200, 50
    ip.regs[PIXEL_CNT] = 921600
    ip.regs[LUMA_SUM] = f1 << 20
    sq = f2 << 28
    ip.regs[LUMA_SQ_SUM_HI] = (sq >> 32) & 0xFFFFFFFF
    ip.regs[LUMA_SQ_SUM] = sq & 0xFFFFFFFF
    ip.regs[GRAD_SUM] = f3 << 16

    regs = AiVideoRegs(ip)
    rows = regs.collect(label=2, n=3, timeout=5.0)
    assert len(rows) == 3, rows
    for r in rows:
        assert r[3] == 2
        assert r[0] == f1 and r[1] == f2 and r[2] == f3, r
    assert regs.mlp_features() == (f1, f2, f3)
    print("test_collect OK")


def main():
    test_version()
    test_features()
    test_collect()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
