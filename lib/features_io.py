"""features.csv 的读写（**全工程唯一实现**）。

为什么单独抽出来：
  采集端（阶段 3）写、训练端（阶段 4）读、测试向量生成端（阶段 5）读，
  三处必须严格同一个列定义，否则会出现“列换了但没人发现，准确率莫名下降”。

列定义（前 4 列不要改）：
    f_luma, f_luma2, f_grad, label

可选列（阶段 12+ 的四象限空间信息，旧 CSV 没有也能读）：
    round, q_tl, q_tr, q_bl, q_br

其中前三列就是**硬件喂给 MLP 的三个整数特征**，不是物理量：
    f_luma  = LUMA_SUM    >> 20   ~ luma * 0.879
    f_luma2 = LUMA_SQ_SUM >> 28   ~ (luma^2 + var) * 0.00343
    f_grad  = GRAD_SUM    >> 16   ~ 平均|ΔY| * 14.06

移位的权威定义在 lib/ai_video_regs.py 的 MLP_FEAT_SHIFT = (20, 28, 16)，
HDL / HLS 两边必须和它一致（f_grad 用 >>20 会恒等于 2，等于把这一维废掉）。
物理量 luma/contrast/sharpness 由 AiVideoRegs.features() 换算，只用于人工检查。
"""
import csv
import os

import numpy as np

FEATURE_COLUMNS = ("f_luma", "f_luma2", "f_grad")
LABEL_COLUMN = "label"
ALL_COLUMNS = FEATURE_COLUMNS + (LABEL_COLUMN,)
SPATIAL_COLUMNS = ("round", "q_tl", "q_tr", "q_bl", "q_br")
ALL_COLUMNS_SPATIAL = ALL_COLUMNS + SPATIAL_COLUMNS


def _read_rows(path):
    """读 CSV，返回 (fieldnames, rows)。前 4 列必须存在，可选列可有可无。"""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        missing = [c for c in ALL_COLUMNS if c not in fieldnames]
        if missing:
            raise ValueError(
                "features.csv 列不对，缺少 %s；实际列 = %s。"
                "请用 lib/features_io.py 的列定义重新采集。" % (missing, fieldnames)
            )
        rows = list(reader)
    return fieldnames, rows


def _to_xy(rows):
    X = [[float(row[c]) for c in FEATURE_COLUMNS] for row in rows]
    y = [int(row[LABEL_COLUMN]) for row in rows]
    return np.asarray(X), np.asarray(y)


def load_csv(path):
    """读回 (X, y)：X 形状 (N,3) float，y 形状 (N,) int。

    只读前 4 列；带 round/quads 的新 CSV 也能直接读，旧调用方不用改。
    """
    _, rows = _read_rows(path)
    return _to_xy(rows)


def load_spatial_csv(path):
    """读回 (X, y, rounds, quads)。

    rounds : (N,) int，CSV 没有 round 列时返回 None
    quads  : (N,4) float，顺序 (左上, 右上, 左下, 右下)；
             CSV 没有四象限列时返回 None

    这两个返回值是给“四象限进入决策”和“按采集轮次留出评估”用的，
    训练/推理仍然只用前 3 个特征，模型和 bitstream 不需要改。
    """
    fieldnames, rows = _read_rows(path)
    X, y = _to_xy(rows)
    if all(c in fieldnames for c in SPATIAL_COLUMNS):
        rounds = np.asarray([int(float(row["round"])) for row in rows], dtype=int)
        quads = np.asarray(
            [[float(row[c]) for c in ("q_tl", "q_tr", "q_bl", "q_br")]
             for row in rows],
            dtype=float,
        )
    else:
        rounds = None
        quads = None
    return X, y, rounds, quads


def write_csv(path, rows):
    """写 features.csv。

    rows 支持两种长度：
      4 列: (f_luma, f_luma2, f_grad, label)
      9 列: (f_luma, f_luma2, f_grad, label, round, q_tl, q_tr, q_bl, q_br)

    只要有一行是 9 列，就按 9 列写；4 列行补 round=-1、quads=0。
    这样旧的采集脚本、旧 CSV、阶段 12+ 的空间采集可以共存。
    """
    rows = list(rows)
    spatial = any(len(r) >= 9 for r in rows)
    header = ALL_COLUMNS_SPATIAL if spatial else ALL_COLUMNS
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(list(header))
        for r in rows:
            if spatial:
                if len(r) >= 9:
                    vals = [int(r[i]) for i in range(9)]
                else:
                    vals = [int(r[0]), int(r[1]), int(r[2]), int(r[3]),
                            -1, 0, 0, 0, 0]
                w.writerow(vals)
            else:
                w.writerow([int(r[0]), int(r[1]), int(r[2]), int(r[3])])
    return path


def pick_features_csv(root, prefer_real=True):
    """优先用真机采集的 features.csv，没有就退回示范数据。"""
    real = os.path.join(root, "data", "features.csv")
    demo = os.path.join(root, "data", "features_demo.csv")
    if prefer_real and os.path.exists(real):
        return real, "real"
    if os.path.exists(demo):
        return demo, "demo"
    if os.path.exists(real):
        return real, "real"
    raise FileNotFoundError(
        "既没有 data/features.csv 也没有 data/features_demo.csv。"
        "真机数据用阶段 3 采；离线试跑用 python stage04_mlp_train/make_demo_csv.py"
    )
