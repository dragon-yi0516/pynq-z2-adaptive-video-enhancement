"""四象限空间决策 + CSV 9 列格式的离线单测（不需要板子）。

跑法：
    python3 lib/test_spatial.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lib import adaptive             # noqa: E402
from lib import features_io          # noqa: E402
from lib.ai_video_regs import AiVideoRegs  # noqa: E402


def test_csv_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        p4 = os.path.join(d, "f4.csv")
        p9 = os.path.join(d, "f9.csv")
        features_io.write_csv(p4, [[10, 0, 17, 0], [95, 65, 30, 2]])
        features_io.write_csv(p9, [
            [10, 0, 17, 0, 0, 100, 101, 99, 100],
            [95, 65, 30, 2, 1, 500, 501, 499, 500],
        ])
        X4, y4 = features_io.load_csv(p4)
        X9, y9 = features_io.load_csv(p9)
        X, y, rounds, quads = features_io.load_spatial_csv(p9)
        assert X4.shape == (2, 3) and X9.shape == (2, 3)
        assert y4.tolist() == [0, 2] and y9.tolist() == [0, 2]
        assert rounds.tolist() == [0, 1]
        assert quads.shape == (2, 4)
        assert quads[1].tolist() == [500.0, 501.0, 499.0, 500.0]
    print("csv roundtrip OK")


def test_spatial_unevenness():
    assert abs(adaptive.spatial_unevenness((19, 19, 20, 21)) - 0.101) < 0.02
    assert adaptive.spatial_unevenness((534, 304, 532, 298)) > 0.5
    # 暗场噪声底保护：均值 < 5 时返回 0
    assert adaptive.spatial_unevenness((1, 0, 3, 0)) == 0.0
    print("spatial_unevenness OK")


def test_decide_spatial():
    # 均匀正常光 -> 信任 MLP
    m, p, _ = adaptive.decide_spatial(
        (95, 65, 30), (500, 501, 499, 500), 2)
    assert m == 2 and p is not None

    # 正常亮度 + 逆光 -> 空间覆盖为 mode 1
    m, p, _ = adaptive.decide_spatial(
        (93, 70, 32), (900, 300, 900, 300), 2)
    assert m == 1 and p is not None

    # 暗场 + 亮窗 -> 不用全局增益，改 mode 1
    m, p, _ = adaptive.decide_spatial(
        (12, 10, 20), (300, 100, 300, 100), 0)
    assert m == 1 and p is not None

    # 中间地带（0.30 < u < 0.55）-> 保持（None）
    m, p, _ = adaptive.decide_spatial(
        (70, 45, 25), (130, 100, 110, 90), 2)
    assert m is None and p is None
    print("decide_spatial OK")


def test_real_hard_pairs():
    """2026-10-19 板上实测的 4 个场景（见 docs/results/hard_pairs.md）。"""
    cases = [
        # (features, quads, mlp, expected spatial mode)
        ((9, 0, 20), (34, 37, 36, 38), 0, 0),       # 均匀暗场
        ((8, 3, 9), (15, 14, 83, 14), 0, 1),        # 暗场+亮窗
        ((100, 49, 27), (399, 334, 442, 420), 2, 2),  # 均匀正常光
        ((116, 96, 22), (191, 735, 231, 694), 1, 1),  # 正常+逆光
    ]
    for f, q, mlp, expected in cases:
        m, p, why = adaptive.decide_spatial(f, q, mlp)
        print("  f=%s u=%.3f MLP=%d -> mode=%s (%s)"
              % (f, adaptive.spatial_unevenness(q), mlp, m, why))
        assert m == expected, (f, q, mlp, m, expected)
    print("real hard pairs OK")


class _FakeRegs(AiVideoRegs):
    """只实现 collect_spatial 用到的读接口，验证逐帧采集逻辑。"""

    def __init__(self):
        self.n = 0
        self.last_dropped = 0

    def has_param(self):
        return True

    def frame_cnt(self):
        self.n += 1
        return self.n

    def mlp_features(self):
        return 10, 0, 17

    def quads(self):
        return 100, 101, 99, 100


def test_collect_spatial():
    r = _FakeRegs()
    rows = r.collect_spatial(0, n=3, round_idx=2, poll_sleep=0)
    assert len(rows) == 3
    assert len(rows[0]) == 9
    assert rows[0][4] == 2
    assert rows[0][5:] == [100, 101, 99, 100]
    print("collect_spatial OK")


if __name__ == "__main__":
    test_csv_roundtrip()
    test_spatial_unevenness()
    test_decide_spatial()
    test_real_hard_pairs()
    test_collect_spatial()
    print("ALL SPATIAL TESTS PASSED")
