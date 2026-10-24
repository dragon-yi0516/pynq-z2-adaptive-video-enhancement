"""用板上部署的权重评估一份“外部/真实场景”CSV（不重训）。

用途：
  * 盒子标定的模型拿到真实房间，准确率会掉多少？
  * 四象限规则在真实场景里是帮忙还是添乱？
  * hard pair 的“期望标签”与 MLP/空间决策差在哪？

用法：
    python3 tools/eval_holdout.py --csv data/real_scene.csv
    python3 tools/eval_holdout.py --csv data/hard_pairs.csv
    python3 tools/eval_holdout.py --csv data/features.csv   # 训练集自评

输入 CSV：
    f_luma,f_luma2,f_grad,label[,round,q_tl,q_tr,q_bl,q_br]

注意：这是**部署权重**的评估，不训练、不改 bitstream。
"""
import argparse
import collections
import csv
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if os.path.join(ROOT, "stage04_mlp_train") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "stage04_mlp_train"))

from lib import features_io          # noqa: E402
from lib import adaptive             # noqa: E402
import mlp_common as mc              # noqa: E402


def load_model(path):
    with open(path, encoding="utf-8") as fh:
        return mc.from_c_header(fh.read())


def metrics(y, pred):
    cm = np.zeros((3, 3), dtype=int)
    for t, p in zip(y, pred):
        cm[int(t), int(p)] += 1
    recalls, f1s = [], []
    for k in range(3):
        tp = int(cm[k, k])
        fn = int(cm[k, :].sum()) - tp
        fp = int(cm[:, k].sum()) - tp
        recalls.append(tp / (tp + fn) if (tp + fn) else 0.0)
        f1s.append(2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0)
    return cm, recalls, float(np.mean(f1s))


def print_block(name, y, pred):
    cm, rec, f1 = metrics(y, pred)
    acc = float((np.asarray(y) == np.asarray(pred)).mean()) if len(y) else 0.0
    print("%s：n=%d  acc=%.4f  macro-F1=%.4f  recall=%s"
          % (name, len(y), acc, f1,
             "/".join("%.3f" % v for v in rec)))
    print(cm)
    return {"n": len(y), "acc": acc, "macro_f1": f1, "recall": rec,
            "cm": cm.tolist()}


def main():
    p = argparse.ArgumentParser(description="deployed-weight holdout evaluation")
    p.add_argument("--csv", required=True)
    p.add_argument("--weights", default=os.path.join(ROOT, "weights", "mlp_weights.h"))
    p.add_argument("--out", default="", help="可选 JSON 输出")
    p.add_argument("--no-spatial", action="store_true",
                   help="只评估纯 MLP，不套四象限规则")
    args = p.parse_args()

    X, y, rounds, quads = features_io.load_spatial_csv(args.csv)
    model = load_model(args.weights)
    mlp = np.asarray([mc.predict_fixed_raw(model, r[0], r[1], r[2]) for r in X],
                     dtype=int)

    print("=" * 76)
    print("holdout 评估：%s" % args.csv)
    print("权重：%s" % args.weights)
    print("样本 %d 条；四象限：%s" % (len(X), "有" if quads is not None else "无"))
    print("=" * 76)

    out = {"csv": os.path.abspath(args.csv), "n": int(len(X))}
    out["mlp"] = print_block("MLP", y, mlp)

    if quads is not None and not args.no_spatial:
        modes, params, holds = [], [], 0
        for i in range(len(X)):
            m, prm, _ = adaptive.decide_spatial(X[i], quads[i], int(mlp[i]))
            if m is None:
                holds += 1
                modes.append(int(mlp[i]))   # 保持 MLP 的判决用于算准确率
                params.append(-1)
            else:
                modes.append(int(m))
                params.append(int(prm))
        out["spatial"] = print_block("MLP + 四象限", y, modes)
        out["holds"] = int(holds)
        out["overrides"] = int(sum(1 for i in range(len(X))
                                   if modes[i] != int(mlp[i])))
        print("空间规则：覆盖 %d 次，保持 %d 次" % (out["overrides"], holds))

        if rounds is not None:
            print()
            print("| scene | n | f_luma | u | MLP | spatial |")
            print("|---|---|---|---|---|---|")
            for r in sorted(set(int(v) for v in rounds)):
                idx = np.where(rounds == r)[0]
                f1 = X[idx, 0]
                us = np.asarray([adaptive.spatial_unevenness(quads[i]) for i in idx])
                c_mlp = collections.Counter(int(mlp[i]) for i in idx)
                c_sp = collections.Counter(("hold" if modes[i] is None else modes[i])
                                           for i in idx)
                print("| %d | %d | %.1f | %.3f | %s | %s |"
                      % (r, len(idx), f1.mean(), us.mean(),
                         dict(c_mlp), dict(c_sp)))

    if args.out:
        directory = os.path.dirname(os.path.abspath(args.out))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
        print("已写", args.out)


if __name__ == "__main__":
    main()
