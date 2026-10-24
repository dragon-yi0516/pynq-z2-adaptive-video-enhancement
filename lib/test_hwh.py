"""离线测试：video_setup 的路径定位与 .hwh 模块解析。

跑法：
    cd <ai_video>
    python lib/test_hwh.py

它用旁边那个已知工程（Pynq_CV_OV5640_master）的 .hwh 来验证解析逻辑。
路径全部由 ASCII 片段拼接，不依赖中文字面量，避免终端编码干扰。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)               # <...>/ai_video
sys.path.insert(0, ROOT)

from lib import video_setup as vs  # noqa: E402


def sibling_hwh():
    """定位旁边工程的 .hwh（全部是 ASCII 路径片段）。"""
    parent = os.path.dirname(ROOT)         # <...>/pynq 实验材料 目录
    cand = os.path.join(
        parent, "Pynq_CV_OV5640_master", "boards", "Pynq-Z2",
        "ov5640", "bitstream", "cv_ov5640.hwh",
    )
    return cand


def main():
    hwh = sibling_hwh()
    if not os.path.exists(hwh):
        print("SKIP: 旁路工程 .hwh 不存在，跳过:", hwh)
        return

    mods = vs.hwh_modules_from_file(hwh)
    print("解析到模块数:", len(mods))
    assert len(mods) > 10, "模块数明显偏少，解析可能错了"
    for want in ("v_demosaic_0", "axi_vdma_0", "axi_vdma_1", "v_tc_0", "rgb2dvi_0"):
        assert want in mods, "缺少模块 %s" % want
        print("  找到", want)
    assert "axis_video_proc_0" not in mods, "旧工程里不该有这个 IP"
    print("hwh 解析测试通过")

    # find_overlay 的报错信息要清楚（这里故意用一个空目录）
    try:
        vs.find_overlay(root=HERE, bit_name="definitely_missing.bit")
    except FileNotFoundError as e:
        assert "definitely_missing.bit" in str(e)
        print("find_overlay 报错信息正常")
    else:
        raise AssertionError("找不到文件时应当抛 FileNotFoundError")

    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
