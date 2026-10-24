"""MLP 训练 / Q8.8 量化 / 定点推理 —— 全工程唯一实现。

为什么用 numpy 手写、而不是 sklearn：
  1. 板子上不一定装了 sklearn，numpy 一定有；手写后 notebook 在板子和 PC 上行为一致。
  2. 量化前需要把“输入归一化”折进第一层权重，手写比改 sklearn 内部更直观。
  3. PC 上零额外依赖就能单测（见文件末尾的 self-test）。

数据流：
      原始特征 x_raw (luma, contrast, sharpness)
          │  x_q = x_raw << MLP_INPUT_SHIFT          (定点化，避免 int16 溢出)
          ▼
      hidden = relu( (x_q · w1) >> 8 + b1 )           (Q8.8)
          ▼
      score  = (hidden · w2) >> 8 + b2                (Q8.8)
          ▼
      class  = argmax(score)

训练与推理一致性的关键：**训练时用的归一化被折进了 w1/b1**，
所以定点推理只需要原始特征，硬件侧不需要任何除法器。
"""
import math
import re

import numpy as np

INPUT_DIM = 3
HIDDEN_DIM = 8
OUTPUT_DIM = 3

# x_q = x_raw << INPUT_SHIFT。
# 这里的 INPUT_SHIFT = 0：因为硬件侧已经把三个累加值右移到了 0~224 的量级
# （见 lib/ai_video_regs.py 的 MLP_FEAT_SHIFT），
# 三个特征量级相近、又都远小于 int16 上限，所以不需要再缩放，
# 这样既省一次乘法，也避免“缩放后权重太小、量化成 0”。
INPUT_SHIFT = 0

Q = 8                 # Q8.8
Q_SCALE = 1 << Q      # 256
INT16_MAX = 32767
INT16_MIN = -32768
INT32_MAX = 2 ** 31 - 1


def _relu(x):
    return np.maximum(x, 0.0)


def _softmax(z):
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def train(X, y, hidden=HIDDEN_DIM, epochs=4000, lr=0.5, seed=0, verbose=False):
    """训练 3-hidden-N 的小 MLP，返回**原始特征空间**的浮点权重。

    归一化在内部完成，并且已经折进 W1/b1，所以返回值可以直接喂给
    ``quantize()``，硬件不需要再做归一化。

    Returns
    -------
    dict : {'w1': (3,H), 'b1': (H,), 'w2': (H,K), 'b2': (K,), 'classes': K}
    """
    X = np.asarray(X, dtype=np.float64)
    y = np.asarray(y, dtype=np.int64)
    n, d = X.shape
    if d != INPUT_DIM:
        raise ValueError("特征维度必须是 %d，收到 %d" % (INPUT_DIM, d))
    classes = int(y.max()) + 1

    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std < 1e-6] = 1e-6
    Xn = (X - mean) / std

    rng = np.random.RandomState(seed)
    params = {
        "w1": rng.randn(d, hidden) * 0.5,
        "b1": np.zeros(hidden),
        "w2": rng.randn(hidden, classes) * 0.5,
        "b2": np.zeros(classes),
    }
    vel = {k: np.zeros_like(v) for k, v in params.items()}

    Y = np.zeros((n, classes))
    Y[np.arange(n), y] = 1.0

    for ep in range(epochs):
        H = _relu(Xn @ params["w1"] + params["b1"])
        P = _softmax(H @ params["w2"] + params["b2"])

        dZ = (P - Y) / n
        g = {
            "w2": H.T @ dZ,
            "b2": dZ.sum(axis=0),
        }
        dH = (dZ @ params["w2"].T) * (H > 0)
        g["w1"] = Xn.T @ dH
        g["b1"] = dH.sum(axis=0)

        lr_t = lr * (0.999 ** ep)
        for k in params:
            vel[k] = 0.9 * vel[k] - lr_t * g[k]
            params[k] = params[k] + vel[k]

        if verbose and (ep + 1) % 500 == 0:
            acc = _accuracy_from_probs(P, y)
            print("  epoch %5d  loss=%.4f  acc=%.3f"
                  % (ep + 1, -np.log(np.clip(P[np.arange(n), y], 1e-12, 1)).mean(), acc))

    # 把归一化折进第一层：z1 = W1@(x-m)/s + b1 = (W1/s)@x + (b1 - (W1/s)@m)
    w1e = params["w1"] / std[None, :].T
    b1e = params["b1"] - (w1e.T @ mean)

    return {
        "w1": w1e,           # (3, H) —— 作用在**原始特征**上
        "b1": b1e,           # (H,)
        "w2": params["w2"],  # (H, K)
        "b2": params["b2"],  # (K,)
        "classes": classes,
        "mean": mean,
        "std": std,
    }


def _accuracy_from_probs(P, y):
    return float((P.argmax(axis=1) == y).mean())


def predict_float(model, X):
    """浮点推理（用于和定点结果对比）。"""
    X = np.asarray(X, dtype=np.float64).reshape(-1, INPUT_DIM)
    H = _relu(X @ model["w1"] + model["b1"])
    Z = H @ model["w2"] + model["b2"]
    return Z.argmax(axis=1)


def accuracy(model, X, y):
    return float((predict_float(model, X) == np.asarray(y)).mean())


def _q8_8(x):
    return np.clip(np.round(np.asarray(x, dtype=np.float64) * Q_SCALE),
                   INT16_MIN, INT16_MAX).astype(np.int16)


def quantize(model, x_max=None):
    """把浮点权重变成 Q8.8 定点，并做溢出检查。

    Parameters
    ----------
    model : dict  ``train()`` 的返回值
    x_max : array-like, 可选
        三个原始特征在训练集里的最大值，用于做最坏情况溢出检查。
        不传就按 (255, 128, 255) 估计。
    """
    if x_max is None:
        x_max = (255.0, 128.0, 255.0)
    x_max = np.asarray(x_max, dtype=np.float64)

    k = float(1 << INPUT_SHIFT)
    w1q = _q8_8(model["w1"] * (Q_SCALE / k))   # 补偿 x_q = x_raw * k
    b1q = _q8_8(model["b1"])
    w2q = _q8_8(model["w2"])
    b2q = _q8_8(model["b2"])

    # ---- 溢出检查：定点路径必须严格等价于“在 int32 里算不出溢出” --------
    xq_max = np.floor(x_max).astype(np.int64) * int(k)  # x_q 的上界（整数运算）
    # 第一层：|b1| + Σ|x_q * w1q|>>8  的上界
    z1_hi = np.abs(b1q.astype(np.int64)) + \
        ((xq_max[:, None] * np.abs(w1q.astype(np.int64))).sum(axis=0) >> Q)
    need1 = int(z1_hi.max())
    h_hi = max(need1, 0)
    # 第二层
    y_hi = int((np.abs(b2q.astype(np.int64)) +
                ((h_hi * np.abs(w2q.astype(np.int64))).sum(axis=0) >> Q)).max())

    report = {
        "xq_max": xq_max.astype(int).tolist(),
        "z1_max_abs": need1,
        "y_max_abs": y_hi,
        "int32_ok": (need1 < INT32_MAX) and (y_hi < INT32_MAX),
        "w1_sat": int((np.abs(model["w1"] * (Q_SCALE / k)) * Q_SCALE > INT16_MAX).sum()),
    }
    if not report["int32_ok"]:
        raise ValueError("定点路径会溢出 int32，请降低 INPUT_SHIFT 或重新训练: %s" % report)
    if report["w1_sat"]:
        raise ValueError("w1 量化后饱和了 %d 个值：说明 std 太小，检查数据" % report["w1_sat"])

    return {
        "w1": w1q,                    # (3, H) int16
        "b1": b1q,                    # (H,)   int16
        "w2": w2q,                    # (H, K) int16
        "b2": b2q,                    # (K,)   int16
        "classes": int(model.get("classes", OUTPUT_DIM)),
        "input_shift": INPUT_SHIFT,
        "report": report,
    }


def _to_int16(v):
    v = int(v)
    if v > INT16_MAX:
        return INT16_MAX
    if v < INT16_MIN:
        return INT16_MIN
    return v


def predict_fixed_raw(model, luma, contrast, sharpness):
    """定点推理：输入是**原始**特征（和硬件寄存器给出的一致）。

    移位一律用算术右移（Python 的 >> 对负数是 floor，等价于 Verilog 的 >>>），
    这样才能和 HDL/HLS 的结果逐位一致。
    """
    k = model.get("input_shift", INPUT_SHIFT)
    limit = INT16_MAX >> k
    xq = [_to_int16(min(max(float(v), 0.0), float(limit))) << k
          for v in (luma, contrast, sharpness)]

    w1 = model["w1"]
    b1 = model["b1"]
    hidden = []
    for i in range(int(w1.shape[1])):
        acc = int(b1[i])
        for j in range(INPUT_DIM):
            acc += (int(w1[j, i]) * xq[j]) >> Q
        hidden.append(acc if acc > 0 else 0)

    w2 = model["w2"]
    b2 = model["b2"]
    best_k = 0
    best_v = None
    for kk in range(int(w2.shape[1])):
        acc = int(b2[kk])
        for i in range(len(hidden)):
            acc += (int(w2[i, kk]) * hidden[i]) >> Q
        if best_v is None or acc > best_v:
            best_v = acc
            best_k = kk
    return best_k


def predict_fixed(model, X):
    X = np.asarray(X, dtype=np.float64).reshape(-1, INPUT_DIM)
    return np.array([predict_fixed_raw(model, r[0], r[1], r[2]) for r in X], dtype=int)


def agreement(model_fixed, model_float, X):
    """量化前后一致率（方案书要求 > 97%）。"""
    a = predict_fixed(model_fixed, X)
    b = predict_float(model_float, X)
    return float((a == b).mean())


# ---------------------------------------------------------------------------
# 训练 + 量化一次到位（notebook / 脚本请用这个，别自己拼 train() + quantize()）
#
# 为什么需要它：训练时的归一化会被折进第一层（w1_folded = w1 / std），而本工程
# 的定点约定要求 |w1_folded| <= 0.5 —— 它在 Q8.8 里还要再乘 65536 才塞得进 int16
# （见 quantize() 里的 w1_sat）。如果某个特征的标准差小、三类又分得很开，
# 折进去的权重就会超标，quantize() 会直接拒绝导出，报「w1 量化后饱和」。
#
# 这不是 bug，是「类内变化太少」的信号 —— 正是阶段 3 那个「每类只有 2~18 个
# 不同取值」的老问题。两条路：把数据采得更松散（tools/collect_dataset.py 每类
# 换 3~5 种摆法，顺便提升泛化），或者把学习率降下来别把决策边界绷那么紧。
# 下面这个函数自动做后一件事，并把结果记进 info 里。
# ---------------------------------------------------------------------------
DEFAULT_ATTEMPTS = ((4000, 0.5), (4000, 0.1), (4000, 0.03), (6000, 0.01), (8000, 0.003))


def train_for_quantization(X, y, hidden=HIDDEN_DIM, attempts=DEFAULT_ATTEMPTS,
                           seed=0, verbose=True, min_accuracy=0.85,
                           min_agreement=0.97):
    """训练 + 量化，自动挑一组「准确率够、量化又不饱和」的超参。

    Returns
    -------
    (model_float, model_fixed, info)
        info 记了实际用了哪一组超参、准确率、一致率、max|w1_folded| 与余量。
    """
    X = np.asarray(X, dtype=np.float64)
    y = np.asarray(y, dtype=np.int64)
    last_reason = None

    for i, (epochs, lr) in enumerate(attempts, start=1):
        model = train(X, y, hidden=hidden, epochs=epochs, lr=lr, seed=seed)
        acc = accuracy(model, X, y)
        w1_max = float(np.abs(model["w1"]).max())
        tag = "尝试 %d/%d: epochs=%d lr=%g" % (i, len(attempts), epochs, lr)

        if acc < min_accuracy:
            last_reason = "准确率只有 %.3f（要求 >= %.2f）" % (acc, min_accuracy)
            if verbose:
                print("  %s -> %s，换下一组" % (tag, last_reason))
            continue

        try:
            qmodel = quantize(model, x_max=X.max(axis=0))
        except ValueError as exc:
            last_reason = str(exc)
            if verbose:
                print("  %s -> 准确率 %.3f，但 max|w1_folded|=%.3f 超过 0.5，"
                      "量化会饱和，把学习率再降一档" % (tag, acc, w1_max))
            continue

        ag = agreement(qmodel, model, X)
        if ag < min_agreement:
            last_reason = "量化前后一致率只有 %.3f（要求 > %.2f）" % (ag, min_agreement)
            if verbose:
                print("  %s -> %s，换下一组" % (tag, last_reason))
            continue

        info = {
            "attempt": i, "epochs": epochs, "lr": lr, "accuracy": acc,
            "agreement": ag, "w1_max_abs": w1_max,
            "w1_headroom": 0.5 / max(w1_max, 1e-12),
        }
        if verbose:
            print("  %s -> 准确率 %.4f，量化一致率 %.4f，max|w1_folded|=%.3f"
                  "（离 0.5 还有 %.1f 倍余量）"
                  % (tag, acc, ag, w1_max, info["w1_headroom"]))
        return model, qmodel, info

    raise ValueError(
        "试了 %d 组超参都没能得到可用的定点模型（最后一次的原因：%s）。\n"
        "多半是类内变化太少：折进第一层的权重必然超标。\n"
        "优先级从高到低：\n"
        "  1) 用 tools/collect_dataset.py 补采（每类换 3~5 种摆法），这同时也提升泛化；\n"
        "  2) 再往下降学习率（比如 0.001）或降 epochs；\n"
        "  3) 跑 python3 tools/check_features.py 看是不是某类只有几个不同取值。\n"
        % (len(attempts), last_reason))


# ---------------------------------------------------------------------------
# C 头文件导出 / 回读
# ---------------------------------------------------------------------------
def to_c_header(model, comment=""):
    """生成 mlp_weights.h。数组布局与工程里 HLS 代码一致：
        w1[j*HIDDEN + i]    (3 x H)
        w2[i*OUTPUT + k]    (H x K)
    """
    # 布局：w1[j*HIDDEN + i]，w2[i*OUTPUT + k]（与 HLS 代码里的下标一致）
    w1 = np.asarray(model["w1"]).reshape(-1)
    b1 = np.asarray(model["b1"]).reshape(-1)
    w2 = np.asarray(model["w2"]).reshape(-1)
    b2 = np.asarray(model["b2"]).reshape(-1)

    def arr(name, vals):
        body = ",".join(str(int(v)) for v in vals)
        return "const short %s[%d] = {%s};\n" % (name, len(vals), body)

    lines = []
    lines.append("// auto-generated by ai_video/stage04_mlp_train/mlp_common.py\n")
    if comment:
        lines.append("// %s\n" % comment)
    lines.append("#ifndef AI_VIDEO_MLP_WEIGHTS_H\n#define AI_VIDEO_MLP_WEIGHTS_H\n\n")
    lines.append("#define MLP_INPUT_DIM  %d\n" % INPUT_DIM)
    lines.append("#define MLP_HIDDEN_DIM %d\n" % int(np.asarray(model["w1"]).shape[1]))
    lines.append("#define MLP_OUTPUT_DIM %d\n" % int(np.asarray(model["w2"]).shape[1]))
    lines.append("#define MLP_INPUT_SHIFT %d\n" % int(model.get("input_shift", INPUT_SHIFT)))
    lines.append("#define MLP_Q_SHIFT %d\n\n" % Q)
    lines.append(arr("w1", w1))
    lines.append(arr("b1", b1))
    lines.append(arr("w2", w2))
    lines.append(arr("b2", b2))
    lines.append("\n#endif\n")
    return "".join(lines)


def _parse_c_array(text, name):
    m = re.search(r"const\s+short\s+%s\s*\[\s*\d*\s*\]\s*=\s*\{(.*?)\}\s*;" % re.escape(name),
                  text, re.S)
    if not m:
        raise ValueError("头文件里找不到数组 %s" % name)
    vals = [int(x) for x in re.findall(r"-?\d+", m.group(1))]
    return np.array(vals, dtype=np.int16)


def from_c_header(text):
    """把 mlp_weights.h 读回成 model dict（阶段 5 用来对齐 HLS 与 Python）。"""
    h = int(re.search(r"#define\s+MLP_HIDDEN_DIM\s+(\d+)", text).group(1))
    k = int(re.search(r"#define\s+MLP_OUTPUT_DIM\s+(\d+)", text).group(1))
    shift = int(re.search(r"#define\s+MLP_INPUT_SHIFT\s+(\d+)", text).group(1))

    w1 = _parse_c_array(text, "w1").reshape(INPUT_DIM, h)
    b1 = _parse_c_array(text, "b1")
    w2 = _parse_c_array(text, "w2").reshape(h, k)
    b2 = _parse_c_array(text, "b2")
    return {"w1": w1, "b1": b1, "w2": w2, "b2": b2,
            "classes": k, "input_shift": shift}


# ---------------------------------------------------------------------------
# self-test：python -m stage04_mlp_train.mlp_common  （或直接 python mlp_common.py）
# ---------------------------------------------------------------------------
def _selftest():
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from make_demo_csv import make_demo_features

    X, y = make_demo_features(n_per_class=400, seed=1)
    mf = train(X, y, epochs=1500, seed=1)
    acc = accuracy(mf, X, y)
    print("float train accuracy = %.3f" % acc)
    assert acc > 0.85, "训练精度不够，检查 make_demo_csv 的可分性"

    mq = quantize(mf, x_max=X.max(axis=0))
    print("quantize report:", mq["report"])
    ag = agreement(mq, mf, X)
    print("fixed vs float agreement = %.4f" % ag)
    assert ag > 0.97, "量化前后一致率不够"

    hdr = to_c_header(mq, comment="selftest")
    back = from_c_header(hdr)
    assert (back["w1"] == mq["w1"]).all()
    assert (back["w2"] == mq["w2"]).all()
    ag2 = agreement(back, mf, X)
    assert abs(ag2 - ag) < 1e-12
    print("header round-trip OK")

    # 训练 + 量化一次到位：demo 数据应该第 1 组就过
    _, mq2, info = train_for_quantization(X, y, verbose=False)
    assert mq2["report"]["int32_ok"], mq2["report"]
    assert info["agreement"] > 0.97, info
    print("train_for_quantization OK: attempt=%d max|w1_folded|=%.3f"
          % (info["attempt"], info["w1_max_abs"]))
    print("ALL SELFTESTS PASSED")


if __name__ == "__main__":
    _selftest()
