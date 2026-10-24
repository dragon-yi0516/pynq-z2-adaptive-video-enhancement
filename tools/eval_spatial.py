"""比较“纯 MLP”与“MLP + 四象限空间决策”的判决。

用法：
    python3 tools/eval_spatial.py --csv data/hard_pairs.csv
    python3 tools/eval_spatial.py --csv data/features.csv
    python3 tools/eval_spatial.py --csv data/hard_pairs.csv --u-hi 0.28 --u-lo 0.12

输入 CSV 必须有四象限列：
    f_luma,f_luma2,f_grad,label,round,q_tl,q_tr,q_bl,q_br

输出：
    - 每个 scene/round 的 f_luma、u、MLP 判决分布、空间判决分布
    - 空间覆盖 / 空间保持次数
    - 如果是 4 个 round 的 hard pair，自动做 pair 对比：
        |Δf_luma| 是否 < 10、|Δu| 是否 > 0.2、
        MLP 是否给出相同判决、加四象限后是否改判为 mode 1
    - data/eval_spatial.json（可选）

注意：这里用的是 weights/mlp_weights.h 里的**当前部署权重**，
不是重新训练一份；所以它回答的是“板上现在的模型 + 空间规则会怎么判”。
"""
import argparse
import collections
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


SCENE_NAMES = {
    0: "uniform_dark",
    1: "dark_window",
    2: "uniform_normal",
    3: "normal_backlight",
}


def load_model(path):
    with open(path, encoding="utf-8") as fh:
        return mc.from_c_header(fh.read())


def fmt_counts(counter):
    return " / ".join("%s:%d" % (k, counter[k]) for k in sorted(counter, key=str))


def main():
    p = argparse.ArgumentParser(description="空间决策 vs 纯 MLP")
    p.add_argument("--csv", default=os.path.join(ROOT, "data", "hard_pairs.csv"),
                   help="含四象限列的 CSV（默认 data/hard_pairs.csv）")
    p.add_argument("--weights", default=os.path.join(ROOT, "weights", "mlp_weights.h"),
                   help="当前部署权重（默认 weights/mlp_weights.h）")
    p.add_argument("--u-hi", type=float, default=None, help="覆盖 U_HI")
    p.add_argument("--u-lo", type=float, default=None, help="覆盖 U_LO")
    p.add_argument("--out", default=os.path.join(ROOT, "data", "eval_spatial.json"),
                   help="JSON 输出路径")
    p.add_argument("--no-write", action="store_true", help="只打印，不写 JSON")
    args = p.parse_args()

    X, y, rounds, quads = features_io.load_spatial_csv(args.csv)
    if quads is None:
        raise SystemExit(
            "这份 CSV 没有四象限列；请用 tools/collect_hard_pairs.py 或 "
            "tools/collect_dataset.py（阶段 12+）重新采集。"
        )
    if rounds is None:
        rounds = np.zeros(len(X), dtype=int)
        print("注意：CSV 没有 round 列，所有样本按 scene 0 处理。")

    model = load_model(args.weights)
    mlp_pred = np.asarray(
        [mc.predict_fixed_raw(model, row[0], row[1], row[2]) for row in X],
        dtype=int,
    )

    modes, params, whys, us = [], [], [], []
    for i in range(len(X)):
        u = adaptive.spatial_unevenness(quads[i])
        m, prm, why = adaptive.decide_spatial(
            X[i], quads[i], int(mlp_pred[i]), args.u_hi, args.u_lo)
        us.append(u)
        modes.append(-1 if m is None else int(m))
        params.append(-1 if prm is None else int(prm))
        whys.append(why)

    order = sorted(set(int(v) for v in rounds))
    print("=" * 84)
    print("空间决策评估：%s" % args.csv)
    print("权重：%s" % args.weights)
    print("=" * 84)
    print("| scene | n | f_luma mean | u mean | MLP 0/1/2 | spatial 0/1/2/hold | overrides | holds |")
    print("|---|---|---|---|---|---|---|---|")

    scene_stats = []
    for r in order:
        idx = np.where(rounds == r)[0]
        f1 = X[idx, 0]
        u = np.asarray([us[i] for i in idx])
        c_mlp = collections.Counter(int(mlp_pred[i]) for i in idx)
        c_sp = collections.Counter(("hold" if modes[i] < 0 else modes[i])
                                   for i in idx)
        overrides = sum(1 for i in idx
                        if modes[i] >= 0 and modes[i] != int(mlp_pred[i]))
        holds = sum(1 for i in idx if modes[i] < 0)
        name = SCENE_NAMES.get(r, "scene_%d" % r) if len(order) == 4 else "scene_%d" % r
        scene_stats.append({
            "round": int(r),
            "name": name,
            "n": int(len(idx)),
            "f_luma_mean": float(f1.mean()),
            "u_mean": float(u.mean()),
            "mlp_counts": {str(k): int(v) for k, v in c_mlp.items()},
            "spatial_counts": {str(k): int(v) for k, v in c_sp.items()},
            "overrides": int(overrides),
            "holds": int(holds),
        })
        print("| %s | %d | %.1f | %.3f | %s | %s | %d | %d |"
              % (name, len(idx), f1.mean(), u.mean(),
                 fmt_counts(c_mlp), fmt_counts(c_sp), overrides, holds))

    total_over = sum(s["overrides"] for s in scene_stats)
    total_hold = sum(s["holds"] for s in scene_stats)
    print()
    print("总计：空间覆盖 %d 次，空间保持 %d 次（共 %d 帧）"
          % (total_over, total_hold, len(X)))

    # 4 个 round 的 hard pair：自动检查“同亮度、不同空间布局”
    if len(order) == 4 and order == [0, 1, 2, 3]:
        print()
        print("Hard pair 检查：")
        for pair in (0, 1):
            a, b = pair * 2, pair * 2 + 1
            ia = np.where(rounds == a)[0]
            ib = np.where(rounds == b)[0]
            fa, fb = X[ia, 0].mean(), X[ib, 0].mean()
            ua = np.mean([us[i] for i in ia])
            ub = np.mean([us[i] for i in ib])
            ma = collections.Counter(int(mlp_pred[i]) for i in ia)
            mb = collections.Counter(int(mlp_pred[i]) for i in ib)
            sa = collections.Counter(("hold" if modes[i] < 0 else modes[i])
                                     for i in ia)
            sb = collections.Counter(("hold" if modes[i] < 0 else modes[i])
                                     for i in ib)
            ok_f = abs(fa - fb) < 10
            ok_u = abs(ua - ub) > 0.20
            print("  pair %d：|Δf_luma|=%.1f %s；|Δu|=%.3f %s"
                  % (pair, abs(fa - fb), "OK" if ok_f else "WARN",
                     abs(ua - ub), "OK" if ok_u else "WARN"))
            print("    MLP: %s vs %s" % (fmt_counts(ma), fmt_counts(mb)))
            print("    spatial: %s vs %s" % (fmt_counts(sa), fmt_counts(sb)))
            # pair B 是逆光场景，期望空间判决以 1 为主
            b_mode1 = sb.get(1, 0)
            if b_mode1 > 0:
                print("    -> 逆光场景出现 mode 1：空间决策生效 [OK]")
            else:
                print("    -> 逆光场景没有 mode 1：检查 u 阈值或光源位置")

    if not args.no_write:
        out = {
            "csv": os.path.abspath(args.csv),
            "weights": os.path.abspath(args.weights),
            "u_hi": float(getattr(adaptive, "SPATIAL_U_HI", 0.30)
                          if args.u_hi is None else args.u_hi),
            "u_lo": float(getattr(adaptive, "SPATIAL_U_LO", 0.12)
                          if args.u_lo is None else args.u_lo),
            "total_overrides": int(total_over),
            "total_holds": int(total_hold),
            "scenes": scene_stats,
        }
        directory = os.path.dirname(os.path.abspath(args.out))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
        print("已写 %s" % args.out)


if __name__ == "__main__":
    main()
