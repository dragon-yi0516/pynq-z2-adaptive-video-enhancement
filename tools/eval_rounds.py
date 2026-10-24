"""按采集轮次留出评估：3 特征 MLP vs 固定亮度阈值。

为什么需要这个脚本
------------------
`stage04_mlp_train/03_mlp_train.ipynb` 现在是随机 80/20 按帧切分。
相邻帧高度相关，1.0000 的验证准确率不能说明“换一轮场景还准不准”。

这里按 `collect_dataset.py` 的采集轮次做 leave-one-round-out：
每类每轮 60 帧，训练用 2 轮、测试用 1 轮，3 折取平均。
如果 CSV 有 `round` 列就直接用；没有就按“每类等分”推断（默认 3 轮）。

用法（PC 或板子上都能跑）：
    python3 tools/eval_rounds.py
    python3 tools/eval_rounds.py --csv data/features.csv --rounds 3
    python3 tools/eval_rounds.py --out data/eval_rounds.json

输出：
    - 每折 MLP / 亮度阈值的 macro-F1、每类 recall、混淆矩阵
    - 平均值 + Markdown 表（可直接贴进报告）
    - data/eval_rounds.json（给报告/图表用）
"""
import argparse
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
import mlp_common as mc              # noqa: E402


def infer_rounds(y, n_rounds):
    """没有 round 列时，按“每类等分”推断轮次。

    当前采集顺序是 label -> round，每轮 per_class 帧；这里只要求
    每类帧数能被 n_rounds 整除，不依赖具体采集顺序。
    """
    rounds = np.full(len(y), -1, dtype=int)
    for k in sorted(set(int(v) for v in y)):
        idx = np.where(y == k)[0]
        if len(idx) % n_rounds:
            raise ValueError(
                "class %d 有 %d 帧，不能被 --rounds %d 整除；"
                "请给每类补采到相等帧数，或用带 round 列的 CSV。"
                % (k, len(idx), n_rounds)
            )
        per = len(idx) // n_rounds
        for r in range(n_rounds):
            rounds[idx[r * per:(r + 1) * per]] = r
    return rounds


def luma_predict(Xtr, ytr, Xte):
    """只用 f_luma 的两级阈值（训练折的类均值中点）。

    这是报告里必须有的 baseline：如果 MLP 不比它强，
    就不能把“AI”当成主要卖点。
    """
    means = [float(Xtr[ytr == k, 0].mean()) for k in (0, 1, 2)]
    t1 = (means[0] + means[1]) / 2.0
    t2 = (means[1] + means[2]) / 2.0
    return np.where(Xte[:, 0] < t1, 0,
                    np.where(Xte[:, 0] < t2, 1, 2))


def metrics(y_true, y_pred):
    cm = np.zeros((3, 3), dtype=int)
    for t, p in zip(y_true, y_pred):
        cm[int(t), int(p)] += 1
    recalls, f1s = [], []
    for k in range(3):
        tp = int(cm[k, k])
        fn = int(cm[k, :].sum()) - tp
        fp = int(cm[:, k].sum()) - tp
        recalls.append(tp / (tp + fn) if (tp + fn) else 0.0)
        f1s.append(2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0)
    return cm, recalls, float(np.mean(f1s))


def main():
    p = argparse.ArgumentParser(description="leave-one-round-out 评估")
    p.add_argument("--csv", default=os.path.join(ROOT, "data", "features.csv"),
                   help="features.csv 路径（默认 data/features.csv）")
    p.add_argument("--rounds", type=int, default=3,
                   help="没有 round 列时按几轮推断（默认 3）")
    p.add_argument("--out", default=os.path.join(ROOT, "data", "eval_rounds.json"),
                   help="JSON 输出路径（默认 data/eval_rounds.json）")
    p.add_argument("--no-write", action="store_true", help="只打印，不写 JSON")
    args = p.parse_args()

    X, y, rounds, quads = features_io.load_spatial_csv(args.csv)
    if rounds is None or (rounds < 0).any():
        rounds = infer_rounds(y, args.rounds)
        source = "inferred"
    else:
        source = "csv"

    uniq = sorted(set(int(v) for v in rounds))
    print("=" * 78)
    print("leave-one-round-out 评估：%s" % args.csv)
    print("样本 %d 条，每类 %d 条；轮次 %s（来源 %s）"
          % (len(y), len(y) // 3, uniq, source))
    print("四象限列：%s" % ("有（本脚本只评估 3 特征 MLP）"
                             if quads is not None else "无"))
    print("=" * 78)

    folds = []
    for r in uniq:
        tr = rounds != r
        te = rounds == r
        mf, mq, info = mc.train_for_quantization(X[tr], y[tr], verbose=False)
        pred_mlp = mc.predict_fixed(mq, X[te])
        cm_mlp, rec_mlp, f1_mlp = metrics(y[te], pred_mlp)

        pred_l = luma_predict(X[tr], y[tr], X[te])
        cm_l, rec_l, f1_l = metrics(y[te], pred_l)

        folds.append({
            "round": int(r),
            "n": int(te.sum()),
            "mlp_macro_f1": f1_mlp,
            "luma_macro_f1": f1_l,
            "mlp_recall": rec_mlp,
            "luma_recall": rec_l,
            "mlp_cm": cm_mlp.tolist(),
            "luma_cm": cm_l.tolist(),
            "info": info,
        })
        print("fold %d  n=%3d  MLP F1=%.3f recall=%s | luma F1=%.3f recall=%s"
              % (r, te.sum(), f1_mlp,
                 "/".join("%.2f" % v for v in rec_mlp),
                 f1_l, "/".join("%.2f" % v for v in rec_l)))
        print("   MLP 混淆矩阵:\n%s" % cm_mlp)
        print("   luma 混淆矩阵:\n%s" % cm_l)

    mean_mlp = float(np.mean([f["mlp_macro_f1"] for f in folds]))
    mean_luma = float(np.mean([f["luma_macro_f1"] for f in folds]))
    std_mlp = float(np.std([f["mlp_macro_f1"] for f in folds]))
    std_luma = float(np.std([f["luma_macro_f1"] for f in folds]))

    print()
    print("| fold | n | MLP macro-F1 | luma macro-F1 | MLP recall 0/1/2 | luma recall 0/1/2 |")
    print("|---|---|---|---|---|---|")
    for f in folds:
        print("| %d | %d | %.3f | %.3f | %s | %s |"
              % (f["round"], f["n"], f["mlp_macro_f1"], f["luma_macro_f1"],
                 "/".join("%.2f" % v for v in f["mlp_recall"]),
                 "/".join("%.2f" % v for v in f["luma_recall"])))
    print("| **mean** |  | **%.3f ± %.3f** | **%.3f ± %.3f** |  |  |"
          % (mean_mlp, std_mlp, mean_luma, std_luma))
    print()
    print("结论：MLP macro-F1 %.3f ± %.3f；固定亮度阈值 %.3f ± %.3f。"
          % (mean_mlp, std_mlp, mean_luma, std_luma))
    if mean_mlp <= mean_luma:
        print("警告：MLP 没有超过亮度基线 —— 不要把 1.0000 当主结论，"
              "先补 hard pair / 空间特征。")

    if not args.no_write:
        out = {
            "csv": os.path.abspath(args.csv),
            "round_source": source,
            "n": int(len(y)),
            "mean_mlp_macro_f1": mean_mlp,
            "std_mlp_macro_f1": std_mlp,
            "mean_luma_macro_f1": mean_luma,
            "std_luma_macro_f1": std_luma,
            "folds": folds,
        }
        directory = os.path.dirname(os.path.abspath(args.out))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
        print("已写 %s" % args.out)


if __name__ == "__main__":
    main()
