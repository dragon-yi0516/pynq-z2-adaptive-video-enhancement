"""阶段 3 采集数据的体检工具：**补采 / 重训之前先跑这个**。

跑法（板子上、PC 上都能跑，只要装了 numpy）：

    cd <ai_video>
    python3 tools/check_features.py                    # 查 data/features.csv
    python3 tools/check_features.py data/features.csv
    python3 tools/check_features.py --no-fail          # 只体检，不改退出码

它针对的是这份工程**实测踩到的两个坑**（见 docs/04_demo_box.md 第 1 节、
docs/05_optimization_plan.md 第七节）：

  坑 1：`data/features.csv` 每类 200 帧，但**只有 2~18 个不同取值**
        —— 三个静止场景各拍 200 帧。MLP 只见过那三个点，
        实机落在中间地带（f_luma=30）时判决是任意的（实测被判成类别 1，
        而它离类别 0 的 10 比离类别 1 的 67 更近）。
  坑 2：三类主要由亮度分开，所以"这是不是就是个亮度阈值？"会被问。
        doc 04 第 8 节给了一个实验来回答，本工具给出**数据侧的对应证据**。

检查项
------
  C1 每类样本数
  C2 每类每特征的**不同取值个数**      <- 主判据，直接抓"三个静止点"
  C3 恒定列（整列 std=0 判死，类内恒定为警告）
  C4 三类中心两两是否分得开（中心距 >= 2x 散布半径）—— 数据能不能用的硬条件
  C4b 类中心跟原标定中心（10 / 67 / 109）差多远 —— 只决定要不要重训/重出 bit
  C5 类之间有没有"没有样本的中间地带"（实机落在那里判决任意）
  C6 暗光类够不够暗（盒子目标 ≈10）
  C7 暗光类里还有没有细节（否则只是"全黑"）
  C8 类内覆盖宽度（某一维在类内几乎不变 -> 模型把它当身份证，板上一漂就乱判）
  另外打印"只用亮度分类的准确率"和逆光/常规的去趋势残差 —— doc 04 第 8 节
  那个"是不是纯亮度分类器"的问题，答案就在这两个数里。

退出码：有 FAIL 返回 1（可以当闸门用）。
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from lib import features_io                              # noqa: E402
from lib.video_setup import VIDEO_HEIGHT, VIDEO_WIDTH    # noqa: E402

PIXELS = float(VIDEO_WIDTH * VIDEO_HEIGHT)
# f_luma = LUMA_SUM >> 20，而 LUMA_SUM = luma x 像素数，所以反过来：
LUMA_PER_F_LUMA = (1 << 20) / PIXELS          # 约 1.138

CLASS_NAMES = {0: "暗光", 1: "逆光", 2: "常规"}

# ---- 判据阈值（要调就改这里）------------------------------------------------
EXPECT_PER_CLASS = 200
MIN_SAMPLES_PER_CLASS = 30

# 盒子标定目标（docs/04_demo_box.md 第 4 节的三个类别中心）
BOX_TARGET_F_LUMA = {0: 10.0, 1: 67.0, 2: 109.0}
BOX_TARGET_TOL = 0.40          # 中心偏离"原标定中心"超过 40% 就提醒（需要重训）
NOISE_FLOOR_F_LUMA = 20.0      # 最亮的类都低于这个值，说明采集时几乎没有光

# 类内"不同特征三元组"的个数：< FAIL 说明这一类基本是一个点（模型没见过它的范围）
MIN_VEC_FAIL = 5
MIN_VEC_WARN = 20
DARK_F_LUMA_FAIL = 30.0        # 盒子暗光档目标 ≈10；30 正是实测翻车的那一段
DARK_F_LUMA_WARN = 20.0
GAP_RATIO_WARN = 4.0           # 类间空隙 / 类内 std 中位数
GAP_RATIO_FAIL = 8.0           # 空隙这么空 = 实机落在中间地带必定乱判 -> 判死
DARK_GRAD_MIN_RATIO = 0.4
LUMA_ONLY_REPORT = 0.90        # 只做展示，用来回答"是不是纯亮度分类器"
# 类内覆盖宽度下限（按特征索引）：某一维在类内几乎不变 = 模型把它当"身份证"，
# 板上一漂就判决乱跳（实测：常规类 f_grad 只有 2 个取值，而板上它在 12~43 之间漂）
MIN_SPAN = {0: 10.0, 1: 6.0, 2: 5.0}


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------
def class_stats(X, y):
    """每类每特征的均值 / 标准差 / 样本数。"""
    out = {}
    for k in sorted(set(int(v) for v in y)):
        v = X[y == k]
        out[k] = {"mean": v.mean(axis=0), "std": v.std(axis=0), "n": len(v),
                  "unique": [len(set(v[:, c])) for c in range(X.shape[1])]}
    return out


def best_threshold_accuracy(v, y_binary):
    """一维特征 + 单阈值，二分类的最好准确率（两个方向都试）。"""
    order = np.argsort(v, kind="mergesort")
    vs, ys = v[order], (y_binary[order] == 1)
    n = len(vs)
    pos_cum = np.concatenate(([0], np.cumsum(ys)))
    total_pos = int(pos_cum[-1])
    best = 0
    for i in range(n + 1):
        pos_below = int(pos_cum[i])
        neg_below = i - pos_below
        pos_above = total_pos - pos_below
        neg_above = (n - i) - pos_above
        best = max(best, neg_below + pos_above, pos_below + neg_above)
    return best / n


def two_threshold_accuracy(v, y, mapping):
    """一维特征 + 两个阈值分三类；mapping 规定低/中/高分别算哪一类。"""
    order = np.argsort(v, kind="mergesort")
    vs, ys = v[order], y[order]
    n = len(vs)
    cum = np.zeros((n + 1, 3), dtype=np.int64)
    for k in (0, 1, 2):
        cum[1:, k] = np.cumsum(ys == k)
    bounds = np.unique(np.searchsorted(vs, np.unique(vs), side="left"))
    cand = sorted(set(int(b) for b in bounds) | {n})
    best = 0
    for ai, a in enumerate(cand):
        for b in cand[ai:]:
            correct = (cum[a, mapping[0]]
                       + (cum[b, mapping[1]] - cum[a, mapping[1]])
                       + (cum[n, mapping[2]] - cum[b, mapping[2]]))
            if correct > best:
                best = int(correct)
    return best / n


def luma_only_accuracy(X, y):
    """只用 f_luma 分三类的最好准确率（两种标签顺序都试，取更有利的）。"""
    v = X[:, 0]
    return max(two_threshold_accuracy(v, y, (0, 1, 2)),
               two_threshold_accuracy(v, y, (2, 1, 0)))


def detrended_residual(X):
    """把 f_luma2 里"跟亮度走"的部分减掉，剩下的才是真正的对比度信息。"""
    a, b = np.polyfit(X[:, 0], X[:, 1], 1)
    return X[:, 1] - (a * X[:, 0] + b), a, b


def cohens_d(sample_a, sample_b):
    """两组样本的标准化均值差。>=1 才叫"分得开"。"""
    if len(sample_a) < 2 or len(sample_b) < 2:
        return 0.0
    pooled = np.sqrt((sample_a.var(ddof=1) + sample_b.var(ddof=1)) / 2.0)
    if pooled < 1e-9:
        return 1e9 if abs(sample_a.mean() - sample_b.mean()) > 1e-9 else 0.0
    return float((sample_a.mean() - sample_b.mean()) / pooled)


def gap_report(X, y):
    """类之间有没有"没有样本的中间地带"。

    对每个特征，按类中心排序后看相邻两类：如果 A 的最大值 < B 的最小值，
    中间那段就是空的。用「空隙 / 两类的类内 std 中位数」衡量有多空：
    * 比值 ≈ 1  -> 两簇的云是接着的，中间地带也有样本，实机不会乱判；
    * 比值 >> 1 -> 中间是一段真空，实机落进去就靠 MLP 瞎猜
      （实测 f_luma=30 被判成 1 就是掉进了这段真空）。
    """
    out = []
    for c, name in enumerate(features_io.FEATURE_COLUMNS):
        centers = {k: float(X[y == k, c].mean()) for k in (0, 1, 2)}
        order = sorted(centers, key=lambda k: centers[k])
        for a, b in zip(order, order[1:]):
            va, vb = X[y == a, c], X[y == b, c]
            gap = float(vb.min() - va.max())
            spread = float(np.median([va.std(), vb.std()]))
            if gap <= 0:
                out.append((name, a, b, gap, spread, 0.0))
            else:
                out.append((name, a, b, gap, spread, gap / max(spread, 1e-9)))
    return out


# ---------------------------------------------------------------------------
# 体检
# ---------------------------------------------------------------------------
def check(X, y, expect_per_class):
    """返回 (findings, extra)；findings 每项 (level, code, text, hint)。"""
    stats = class_stats(X, y)
    findings = []
    extra = {}

    def add(level, code, text, hint=""):
        findings.append((level, code, text, hint))

    missing = [k for k in sorted(CLASS_NAMES) if k not in stats]
    if missing:
        for k in missing:
            add("FAIL", "C1", "label %d（%s）一类都没有" % (k, CLASS_NAMES[k]),
                "三类的标签必须是 0/1/2；用 tools/collect_dataset.py 采")
        return findings, extra

    # ---- 打印数据长相 ----------------------------------------------------
    print("[每类统计]  f_* 是硬件喂给 MLP 的整数特征")
    print("  %-9s %-22s %-22s %-22s"
          % ("特征", "label0 暗光", "label1 逆光", "label2 常规"))
    for c, name in enumerate(features_io.FEATURE_COLUMNS):
        line = "  %-9s" % name
        for k in (0, 1, 2):
            line += "  %7.1f+-%-6.1f      " % (stats[k]["mean"][c], stats[k]["std"][c])
        print(line)
    print("  %-9s %-22s %-22s %-22s"
          % ("约等于亮度",
             "%.0f" % (stats[0]["mean"][0] * LUMA_PER_F_LUMA),
             "%.1f" % (stats[1]["mean"][0] * LUMA_PER_F_LUMA),
             "%.1f" % (stats[2]["mean"][0] * LUMA_PER_F_LUMA)))
    for k in (0, 1, 2):
        v = X[y == k]
        span = tuple(float(v[:, c].max() - v[:, c].min()) for c in range(3))
        print("  label%d 不同取值个数=%s  覆盖宽度=(%.0f, %.0f, %.0f)"
              % (k, tuple(stats[k]["unique"]), span[0], span[1], span[2]))
    print()

    # ---- C1 样本数 -------------------------------------------------------
    for k in (0, 1, 2):
        n = stats[k]["n"]
        if n < MIN_SAMPLES_PER_CLASS:
            add("FAIL", "C1", "label %d（%s）只有 %d 条，少于 %d 条没法训练"
                % (k, CLASS_NAMES[k], n, MIN_SAMPLES_PER_CLASS),
                "用 tools/collect_dataset.py 重采这一类")
        elif n != expect_per_class:
            add("WARN", "C1", "label %d（%s）有 %d 条，期望 %d 条"
                % (k, CLASS_NAMES[k], n, expect_per_class), "想对齐就重采")

    # ---- C2 类内变化（不看单个特征，看整个特征三元组）--------------------
    # 为什么按三元组算：某个特征在某一类里恒定不一定有害（暗光类的 f_luma2 会被量化成
    # 常数 0），真正要命的是"这一类只有一个点" —— 模型没见过它的范围，
    # 实机落在中间地带就只能瞎猜。
    vec_unique = {}
    for k in (0, 1, 2):
        vec_unique[k] = len(set(tuple(v) for v in X[y == k].tolist()))
    worst_k = min(vec_unique, key=lambda k: vec_unique[k])
    worst_u = vec_unique[worst_k]
    if worst_u < MIN_VEC_FAIL:
        add("FAIL", "C2",
            "label %d（%s）整类只有 %d 个不同的特征三元组（判据 >= %d）："
            "这一类基本是「同一个静止画面拍了 %d 帧」"
            % (worst_k, CLASS_NAMES[worst_k], worst_u, MIN_VEC_FAIL, stats[worst_k]["n"]),
            "每轮 60 帧里让场景动起来（缓慢移动/转动目标物、改一点距离或灯位），"
            "再多换几轮 —— 每类的「不同取值」越多，实机落在中间地带时判决才越稳")
    elif worst_u < MIN_VEC_WARN:
        add("WARN", "C2", "label %d（%s）只有 %d 个不同的特征三元组（理想 >= %d）"
            % (worst_k, CLASS_NAMES[worst_k], worst_u, MIN_VEC_WARN),
            "采集过程中让目标物/灯缓慢变化，能显著增加类内变化")
    else:
        add("PASS", "C2", "最差的一类也有 %d 个不同的特征三元组（label%d）"
            % (worst_u, worst_k))

    # ---- C3 恒定列 -------------------------------------------------------
    for c, name in enumerate(features_io.FEATURE_COLUMNS):
        if X[:, c].std() <= 1e-9:
            add("FAIL", "C3", "%s 整列恒等于 %.1f（std=0）：这一维完全没有分辨率"
                % (name, X[0, c]),
                "移位取太粗或硬件没统计到，先回阶段 2/3 的 VERIFY 查寄存器")
            continue
        flat = [k for k in (0, 1, 2) if stats[k]["std"][c] <= 1e-9]
        if flat:
            add("WARN", "C3", "%s 在 label %s 里恒定（std=0）：这一类在该维度没有分辨率"
                % (name, "/".join(str(k) for k in flat)),
                "多半就是 C2 说的「只有一个点」，重采即可")

    # ---- C4 三类中心必须两两分得开（硬判据）------------------------------
    # 这才是"数据能不能用"的关键：两类糊在一起，重训也救不回来。
    # 判据：中心距 >= 2 x 两类的散布半径（在三个特征组成的空间里量）。
    centers = {k: stats[k]["mean"] for k in (0, 1, 2)}
    stds = {k: stats[k]["std"] for k in (0, 1, 2)}
    brightest = max(float(centers[k][0]) for k in (0, 1, 2))
    worst = None
    for a, b in ((0, 1), (0, 2), (1, 2)):
        gap = float(np.linalg.norm(centers[a] - centers[b]))
        spread = max(float(np.linalg.norm(stds[a])), float(np.linalg.norm(stds[b])))
        ratio = gap / (2.0 * spread) if spread > 1e-9 else 99.0
        if worst is None or ratio < worst[0]:
            worst = (ratio, a, b, gap, spread)
    ratio, a, b, gap, spread = worst
    if brightest < NOISE_FLOOR_F_LUMA:
        add("FAIL", "C4",
            "整份数据都贴在噪声底：最亮的类才 f_luma=%.0f（目标 67~109）" % brightest,
            "这不是「标定偏了」，是采集时几乎没有光。先查灯的电源和调光旋钮，"
            "再确认曝光写进去了：box_calibration.ipynb 的扫描格在**自动/手动**下"
            "各读一次 f_luma，两个都≈4 就是没光进镜头（不是寄存器问题）")
    elif ratio < 1.0:
        add("FAIL", "C4",
            "label%d 和 label%d 在特征空间里糊在一起：中心距 %.1f，而两类的散布半径就有 %.1f"
            % (a, b, gap, spread),
            "两类的光/摆法差别要拉大（目标 f 见 docs/04_demo_box.md 第 4 节的表），"
            "也先确认采集时真的换了场景")
    else:
        add("PASS", "C4", "三类中心两两分得开（最差的一对 label%d/label%d：中心距 %.1f，散布半径 %.1f）"
            % (a, b, gap, spread))

    # ---- C4b 和原标定中心（10/67/109）差多远（软判据）--------------------
    # 差得多 = 现有模型和阶段 7/12 的 bit 不能直接复用，要重训 + 重出 bit ——
    # 但重训本来就在计划里，所以这条只提醒，不影响"数据能不能用"。
    off = []
    for k in (0, 1, 2):
        got = float(centers[k][0])
        want = BOX_TARGET_F_LUMA[k]
        off.append((k, got, want, abs(got - want) / want))
    far = [t for t in off if t[3] > BOX_TARGET_TOL]
    if far:
        add("WARN", "C4b",
            "类中心跟原标定中心有距离：" +
            "；".join("label%d 实测 %.0f / 原中心 %.0f" % (t[0], t[1], t[2]) for t in far),
            "现有模型和阶段 7/12 的 bit 不能直接复用，要重训 + 重出 bit"
            "（这条不影响「数据能不能用」）")
    else:
        add("PASS", "C4b", "三类中心和原标定中心一致 (%s)，现有 bit 也可以先用着"
            % " / ".join("%.0f" % t[1] for t in off))

    # ---- C5 中间地带 -----------------------------------------------------
    gaps = gap_report(X, y)
    extra["gaps"] = gaps
    hollow = [g for g in gaps if g[5] > GAP_RATIO_WARN]
    if hollow:
        worst_gap = max(hollow, key=lambda g: g[5])
        level = "FAIL" if worst_gap[5] > GAP_RATIO_FAIL else "WARN"
        add(level, "C5",
            "label%d 和 label%d 在 %s 上中间空了 %.0f（= 类内 std 的 %.1f 倍）："
            "这段区间里一个训练样本都没有，实机落进去判决是任意的"
            % (worst_gap[1], worst_gap[2], worst_gap[0], worst_gap[3], worst_gap[5]),
            "这就是实测「f_luma=30 被判成 1」的成因。做法：在**该类的目标带内**多留变化"
            "（每轮 60 帧里让场景动起来 + 多换几种摆法），让两簇的云接上（比值降到 %.0f 以下）"
            % GAP_RATIO_WARN)
    else:
        add("PASS", "C5", "三类之间的空隙都不超过类内 std 的 %.0f 倍：中间地带也有样本"
            % GAP_RATIO_WARN)

    # ---- C6 暗光够暗 -----------------------------------------------------
    dark = stats[0]["mean"][0] * LUMA_PER_F_LUMA
    if dark > DARK_F_LUMA_FAIL:
        add("FAIL", "C6", "暗光类亮度 %.0f（盒子目标 ≈%.0f）：这不算暗光"
            % (dark, BOX_TARGET_F_LUMA[0]),
            "先确认切了手动曝光（lib/exposure.py 的 set_manual），"
            "再确认箱体不漏光、灯关到位")
    elif dark > DARK_F_LUMA_WARN:
        add("WARN", "C6", "暗光类亮度 %.0f，比盒子目标 ≈%.0f 亮"
            % (dark, BOX_TARGET_F_LUMA[0]), "灯再关一点，或把曝光调小")
    else:
        add("PASS", "C6", "暗光类亮度 %.0f（盒子目标 ≈%.0f）"
            % (dark, BOX_TARGET_F_LUMA[0]))

    # ---- C7 暗光里还有细节（只警告）--------------------------------------
    g0, g2 = stats[0]["mean"][2], stats[2]["mean"][2]
    ratio = g0 / g2 if g2 > 0 else 0.0
    if ratio < DARK_GRAD_MIN_RATIO:
        add("WARN", "C7", "暗光类 f_grad 只有常规类的 %.0f%%：画面几乎纯黑，没细节"
            % (ratio * 100),
            "暗光档也放一张有纹理的卡片（打印网格 / 文字卡），"
            "否则「暗光=全黑」，演示时看不出增强的意义")
    else:
        add("PASS", "C7", "暗光类 f_grad 是常规类的 %.0f%%，画面里还留着细节" % (ratio * 100))

    # ---- C8 类内覆盖宽度 -------------------------------------------------
    # 实测教训：这份数据里常规类的 f_grad 在 180 帧里只有 2 个取值（38/39），
    # 而板子上 f_grad 会随纹理 / 距离在 12~43 之间漂 —— 模型把那一维学成"窄带"，
    # 输入一偏出窄带判决就在两类之间跳（monitor 里 f 几乎一样、结论却相反）。
    narrow = []
    for k in (0, 1, 2):
        v = X[y == k]
        for c, name in enumerate(features_io.FEATURE_COLUMNS):
            span = float(v[:, c].max() - v[:, c].min())
            if span < MIN_SPAN[c]:
                narrow.append((k, name, span, MIN_SPAN[c]))
    if narrow:
        add("WARN", "C8",
            "有 %d 处类内覆盖太窄（模型会把那一维当身份证）：%s"
            % (len(narrow), "；".join("label%d 的 %s 只铺开 %.0f（建议 >= %.0f）" % t
                                     for t in narrow[:4])),
            "补采时让这一维也有变化：换纹理密度/粗细、改距离、轻微失焦、缓慢移动目标物。")
    else:
        add("PASS", "C8", "各特征的类内覆盖都够宽（f_luma >= 10、f_luma2 >= 6、f_grad >= 5）")

    # ---- 证据：是不是"纯亮度分类器"（回答 doc 04 第 8 节）-----------------
    acc_luma = luma_only_accuracy(X, y)
    resid, slope, intercept = detrended_residual(X)
    d12 = cohens_d(resid[y == 1], resid[y == 2])
    extra.update({"luma_only": acc_luma, "resid_d": d12,
                  "corr": float(np.corrcoef(X[:, 0], X[:, 1])[0, 1])})
    print("[是不是纯亮度分类器]  （docs/04_demo_box.md 第 8 节那个问题的数据侧证据）")
    print("  只用 f_luma 做两级阈值分类的准确率 = %.1f%%" % (acc_luma * 100))
    print("  corr(f_luma, f_luma2) = %.3f" % extra["corr"])
    print("  去掉亮度趋势后，逆光 vs 常规 的对比度差异 d = %.2f" % d12)
    if acc_luma >= 1.0:
        print("  -> 这份数据里亮度就能 100% 分开三类，所以「只靠亮度」目前是成立的。")
    elif acc_luma > LUMA_ONLY_REPORT:
        print("  -> 亮度已经能分开大部分，对比度只补了一点点。")
    else:
        print("  -> 亮度分不开三类，对比度确实在起作用。")
    print("  -> 现场按 doc 04 第 8 节做那个实验（把灯固定到 f_luma≈77 换卡片），")
    print("     这里再跑一次本工具：d 越大，答辩时「不是纯亮度阈值」越站得住。")
    print()
    return findings, extra


def report(findings):
    order = {"FAIL": 0, "WARN": 1, "PASS": 2}
    fails = warns = passes = 0
    print("[验收]")
    for level, code, text, hint in sorted(findings, key=lambda f: order[f[0]]):
        print("  [%s] %s %s" % (level, code, text))
        if hint and level != "PASS":
            print("         -> %s" % hint)
        if level == "FAIL":
            fails += 1
        elif level == "WARN":
            warns += 1
        else:
            passes += 1
    print()
    if fails:
        print("结论：%d 个 FAIL / %d 个 WARN  ->  这份数据先别拿去重训，回阶段 3 补采。"
              % (fails, warns))
    elif warns:
        print("结论：0 个 FAIL / %d 个 WARN  ->  可以重训；有时间就把警告也修掉"
              "（尤其是 C2/C5，直接决定实机稳不稳）。" % warns)
    else:
        print("结论：全部通过（%d 项）->  可以重训。" % passes)
    return fails


def main():
    p = argparse.ArgumentParser(description="阶段 3 采集数据体检")
    p.add_argument("csv", nargs="?", default=os.path.join(ROOT, "data", "features.csv"),
                   help="features.csv 路径（默认 data/features.csv）")
    p.add_argument("--expect-per-class", type=int, default=EXPECT_PER_CLASS,
                   help="每类期望样本数（默认 %d）" % EXPECT_PER_CLASS)
    p.add_argument("--no-fail", action="store_true",
                   help="即使有 FAIL 也返回退出码 0")
    args = p.parse_args()

    if not os.path.exists(args.csv):
        print("找不到 %s。" % args.csv)
        print("真机数据用 tools/collect_dataset.py 采（或阶段 3 的 02_feature_collect.ipynb）")
        return 2

    print("=" * 74)
    print("阶段 3 数据体检：%s" % args.csv)
    print("=" * 74)
    X, y = features_io.load_csv(args.csv)
    counts = {int(k): int((y == k).sum()) for k in sorted(set(int(v) for v in y))}
    print("样本 %d 条，每类 %s" % (len(X), counts))
    print()

    findings, _ = check(X, y, args.expect_per_class)
    fails = report(findings)
    if fails and not args.no_fail:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
