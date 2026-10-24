"""生成一份“示范用”的 features.csv。

用途（很重要）：
  真机采集（阶段 3）需要人手去遮镜头、找逆光、移动物体，比较费时间。
  这个脚本按真实量级造出三类可分的数据，让你在**没有板子**的情况下也能先把
  阶段 4/5 的链路（训练 -> 量化 -> C 头文件 -> 定点一致性）跑通并验证。
  等真机数据采回来，只要把文件换成 features.csv 重训即可，其它代码不用动。

三类场景的量级（参考真机特征，luma 0~255）：
  label 0 暗光   : 亮度低、对比度低、细节少
  label 1 逆光   : 整体亮度高、对比度大
  label 2 常规/细节: 亮度中等、细节（梯度）最大

用法：
    python make_demo_csv.py [输出路径] [每类样本数]
默认输出 <ai_video>/data/features_demo.csv，每类 400 条。
"""
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.features_io import write_csv  # noqa: E402

# (均值, 标准差) —— f1, f2, f3，单位是**硬件特征单位**（见 lib/ai_video_regs.py）
#
# 换算关系（1280x720，921600 像素，与 lib/ai_video_regs.py 的 MLP_FEAT_SHIFT 一致）：
#   f1 = luma   * 0.879
#   f2 = (luma^2 + var) * 0.00343       （var = contrast^2）
#   f3 = 平均|ΔY| * 14.06               （注意 f3 的移位是 16，不是 20）
# 下面的均值/标准差就是按“暗光 / 逆光 / 常规细节”三组物理量换算出来的，
# 所以它和你真机采到的数据量级一致。
#
# f3 的标准差按均值的 10% 给：真机上同一类场景里清晰度的波动本来就很小
# （第一次采集时 f_grad 几乎是常数），给太大反而会让这个合成数据不像真机。
_CLASSES = {
    # label 0 暗光: luma~45, contrast~14, 平均梯度~6
    0: ((39.6, 10.5), (7.6, 3.7), (85.0, 8.5)),
    # label 1 逆光: luma~185, contrast~62, 平均梯度~18
    1: ((162.6, 15.8), (130.7, 22.9), (253.0, 25.0)),
    # label 2 常规/细节: luma~118, contrast~34, 平均梯度~38
    2: ((103.7, 13.2), (51.8, 12.2), (534.0, 53.0)),
}


def make_demo_features(n_per_class=400, seed=0):
    """返回 (X, y)，X 形状 (3*n, 3)。"""
    rng = np.random.RandomState(seed)
    X = []
    y = []
    for label in sorted(_CLASSES):
        stats = _CLASSES[label]
        vals = np.stack([
            rng.normal(m, s, size=n_per_class) for (m, s) in stats
        ], axis=1)
        # 物理上这些量都不能是负数
        vals = np.clip(vals, 0.0, None)
        X.append(vals)
        y.extend([label] * n_per_class)
    return np.vstack(X), np.asarray(y, dtype=int)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    default_out = os.path.join(os.path.dirname(here), "data", "features_demo.csv")
    out = sys.argv[1] if len(sys.argv) > 1 else default_out
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 400

    X, y = make_demo_features(n_per_class=n, seed=0)
    write_csv(out, [(round(r[0]), round(r[1]), round(r[2]), int(lab))
                    for r, lab in zip(X, y)])
    print("已生成:", out)
    for label in sorted(_CLASSES):
        m = y == label
        print("  label %d : luma=%7.2f contrast=%7.2f sharpness=%7.2f  (n=%d)"
              % (label, X[m, 0].mean(), X[m, 1].mean(), X[m, 2].mean(), int(m.sum())))


if __name__ == "__main__":
    main()
