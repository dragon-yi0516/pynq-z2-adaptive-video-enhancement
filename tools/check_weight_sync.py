"""权重 / HLS 源码 / bitstream 的一致性检查（不用接板子）。

为什么需要它
------------
实测踩过一次：训练完导出了新权重，但**忘了重出 bitstream**，
于是板上跑的还是旧模型 —— monitor 看到的所有判决都是旧权重给的，白折腾一轮。
（教训来自 2026-10-11：`weights/mlp_weights.h` 11:36 更新，
 而 overlay 里的 bit 还是更早那份。）

它检查三件事：
  1) `weights/mlp_weights.h` 和 `stage05_mlp_hls/src/mlp_weights.h` 是否一致（sha256）；
  2) 权重头文件里的维数 / 移位是否和工程约定对得上；
  3) **bitstream 有没有比权重旧** —— 旧了就说明板上跑的一定还是旧模型。

用法（PC / 板子上都行）：
    cd <ai_video>
    python3 tools/check_weight_sync.py
    python3 tools/check_weight_sync.py --allow-stale    # 只报告，不返回非零

退出码：需要重出 bit、或权重没同步时返回 1（可以当闸门用）。
"""
import argparse
import hashlib
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

WEIGHTS = os.path.join(ROOT, "weights", "mlp_weights.h")
HLS_SRC = os.path.join(ROOT, "stage05_mlp_hls", "src", "mlp_weights.h")
BITSTREAM_CANDIDATES = (
    os.path.join(ROOT, "overlay", "cv_ov5640.bit"),
    os.path.join(ROOT, os.pardir, "bitstream", "cv_ov5640.bit"),
    os.path.join(ROOT, "bitstream", "cv_ov5640.bit"),
)

EXPECT = {"MLP_INPUT_DIM": 3, "MLP_HIDDEN_DIM": 8, "MLP_OUTPUT_DIM": 3,
          "MLP_INPUT_SHIFT": 0, "MLP_Q_SHIFT": 8}


def sha256(path, n=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(n)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def find_bitstream():
    for p in BITSTREAM_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def parse_defines(text):
    out = {}
    for key in EXPECT:
        m = re.search(r"#define\s+%s\s+(-?\d+)" % key, text)
        if m:
            out[key] = int(m.group(1))
    return out


def main():
    ap = argparse.ArgumentParser(description="权重 / HLS / bitstream 一致性检查")
    ap.add_argument("--allow-stale", action="store_true",
                    help="bitstream 比权重旧时也只报告，不返回非零退出码")
    args = ap.parse_args()

    problems = []
    print("=" * 74)
    print("权重同步检查")
    print("=" * 74)

    # ---- 1) 权重头文件本身 -------------------------------------------------
    if not os.path.exists(WEIGHTS):
        print("!! 找不到 %s —— 先跑 04_mlp_quant_export.ipynb 导出权重" % WEIGHTS)
        return 1
    text = open(WEIGHTS, encoding="utf-8").read()
    fp = sha256(WEIGHTS)
    defines = parse_defines(text)
    print("权重 : %s" % os.path.relpath(WEIGHTS, ROOT))
    print("       指纹 %s  修改时间 %s" % (fp[:16],
          time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(WEIGHTS)))))
    print("       维数/移位 %s" % defines)
    for k, v in EXPECT.items():
        if k in defines and defines[k] != v:
            problems.append("权重头文件里 %s=%d，工程约定是 %d" % (k, defines[k], v))

    # ---- 2) HLS 源码里的那份是否同步 ---------------------------------------
    if not os.path.exists(HLS_SRC):
        problems.append("找不到 %s：HLS 会用到旧权重（先跑 05_mlp_verify.ipynb 的同步格）"
                        % os.path.relpath(HLS_SRC, ROOT))
        print("HLS  : 缺失")
    else:
        fp2 = sha256(HLS_SRC)
        same = (fp2 == fp)
        print("HLS  : %s  指纹 %s  %s"
              % (os.path.relpath(HLS_SRC, ROOT), fp2[:16], "一致" if same else "**不一致**"))
        if not same:
            problems.append("stage05_mlp_hls/src/mlp_weights.h 和 weights/mlp_weights.h 不一致："
                            "跑 05_mlp_verify.ipynb 里那格同步，再重跑 HLS")

    # ---- 3) bitstream 是不是比权重旧 --------------------------------------
    bit = find_bitstream()
    if bit is None:
        print("BIT  : 没找到 cv_ov5640.bit（跳过新鲜度检查）")
    else:
        t_bit, t_w = os.path.getmtime(bit), os.path.getmtime(WEIGHTS)
        print("BIT  : %s  修改时间 %s" % (os.path.relpath(bit, ROOT),
              time.strftime("%m-%d %H:%M", time.localtime(t_bit))))
        if t_bit < t_w:
            print("       -> **bitstream 比权重旧 %.0f 分钟**" % ((t_w - t_bit) / 60.0))
            problems.append("bitstream 比权重旧：板上跑的一定还是旧模型。"
                            "跑 `bash build_overlay.sh 12` 重出 bit 之后再看 monitor")
        else:
            print("       -> bitstream 比权重新，权重应该已经进去了（再核对一次 VERSION）")

    # ---- 结论 -------------------------------------------------------------
    print()
    if problems:
        print("[结论] 有 %d 个问题：" % len(problems))
        for p in problems:
            print("  - " + p)
        if args.allow_stale:
            print("（--allow-stale：退出码仍是 0）")
            return 0
        return 1
    print("[结论] 权重、HLS 源码、bitstream 三者一致 —— 可以放心拿 monitor 验证新模型。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
