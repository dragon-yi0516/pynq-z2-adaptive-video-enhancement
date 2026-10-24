"""PC 离线自检：不接板子，把阶段 4 的完整链路跑一遍。

跑法：
    cd <ai_video>
    python tools/offline_check.py

它做的事和 notebook 03/04 完全一样（用的是同一份 mlp_common.py），
所以本地通过就等于板子上那两步的代码逻辑没问题。

产物：
    data/features_demo.csv   （如果还没有就生成）
    data/mlp_float.npz
    weights/mlp_weights.h
"""
import argparse
import csv
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STAGE4 = os.path.join(ROOT, "stage04_mlp_train")
sys.path.insert(0, ROOT)
sys.path.insert(0, STAGE4)

import mlp_common as mc          # noqa: E402
from make_demo_csv import make_demo_features                 # noqa: E402
from lib import features_io                                  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(description="PC 离线自检（训练→量化→导出→回读）")
    p.add_argument("--weights", default=os.path.join("weights", "mlp_weights.h"),
                   help="导出头文件路径（默认 weights/mlp_weights.h）。"
                        "只想验证流程、不想覆盖板子用的权重时，给一个临时路径。")
    return p.parse_args()


def main():
    args = parse_args()
    data_dir = os.path.join(ROOT, "data")
    weights_dir = os.path.join(ROOT, "weights")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(weights_dir, exist_ok=True)

    real = os.path.join(data_dir, "features.csv")
    demo = os.path.join(data_dir, "features_demo.csv")

    if os.path.exists(real):
        csv_path = real
        print("[1/6] 使用真机数据:", csv_path)
    else:
        if not os.path.exists(demo):
            X0, y0 = make_demo_features(n_per_class=400, seed=0)
            features_io.write_csv(
                demo,
                [(round(r[0]), round(r[1]), round(r[2]), int(lab))
                 for r, lab in zip(X0, y0)],
            )
        csv_path = demo
        print("[1/6] 使用示范数据:", csv_path)

    X, y = features_io.load_csv(csv_path)
    print("     样本 %d 条，类别 %s" % (len(X), sorted(set(y.tolist()))))

    print("[2/6] 训练 3-8-3 MLP + 自动避开 w1 量化饱和 ...")
    # 和 03_mlp_train.ipynb 完全同一条路径。旧版这里用 train()+quantize()，
    # 在当前数据集上会报 “w1 量化后饱和” —— 不是数据错，而是归一化折进
    # 第一层后权重超过 Q8.8 的 0.5 上限。train_for_quantization() 会自动
    # 降学习率重试，并把实际用的超参记进 info。
    model, qmodel, info = mc.train_for_quantization(X, y, verbose=True)
    acc = info["accuracy"]
    print("     浮点训练准确率 = %.4f，量化一致率 = %.4f，max|w1_folded|=%.3f"
          % (acc, info["agreement"], info["w1_max_abs"]))
    assert acc > 0.85, "准确率不足 85%"

    print("[3/6] 保存浮点模型 data/mlp_float.npz ...")
    npz = os.path.join(data_dir, "mlp_float.npz")
    np.savez(npz, w1=model["w1"], b1=model["b1"], w2=model["w2"],
             b2=model["b2"], mean=model["mean"], std=model["std"],
             classes=model["classes"])

    print("[4/6] Q8.8 量化报告 + 溢出检查 ...")
    print("     ", qmodel["report"])
    ag = info["agreement"]
    print("     量化前后一致率 = %.4f (要求 > 0.97)" % ag)
    assert ag > 0.97, "一致率不足"

    print("[5/6] 导出 weights/mlp_weights.h ...")
    hdr = mc.to_c_header(qmodel, comment="offline_check agreement=%.4f" % ag)
    h_path = (args.weights if os.path.isabs(args.weights)
              else os.path.join(ROOT, args.weights))
    h_dir = os.path.dirname(os.path.abspath(h_path))
    if h_dir:
        os.makedirs(h_dir, exist_ok=True)
    with open(h_path, "w", encoding="utf-8") as f:
        f.write(hdr)
    back = mc.from_c_header(open(h_path, encoding="utf-8").read())
    assert (back["w1"] == qmodel["w1"]).all()
    assert (back["w2"] == qmodel["w2"]).all()
    assert mc.agreement(back, model, X) == ag

    print("[6/6] 定点推理抽查（用第一类的第 1 条样本）:")
    x0 = X[0]
    cls = mc.predict_fixed_raw(qmodel, x0[0], x0[1], x0[2])
    print("     raw=(%.1f, %.1f, %.1f) -> class %d (真实 %d)"
          % (x0[0], x0[1], x0[2], cls, y[0]))

    print("ALL OFFLINE CHECKS PASSED")
    print("产物: %s" % npz)
    print("      %s" % h_path)


if __name__ == "__main__":
    main()
