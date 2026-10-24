"""连续自适应策略：把实时特征换算成 (mode, param)。

和阶段 7 的「三选一」有什么区别
--------------------------------
阶段 7：MLP 吐出 0/1/2 -> 直接写 MODE_SEL -> 画面按三种**写死的强度**处理。
        实测（06_mode_manual）三档输出均值 169.3 / 124.8 / 116.1 ——
        mode1 和 mode2 只差 8.4 灰度，肉眼几乎看不出切换。

阶段 12：MODE_SEL 仍然决定「用哪种处理」，但**强度**由 PARAM 连续控制。
        本模块负责把特征换算成 0~255 的参数，而且特意针对了阶段 7 实测到的两个毛病：

          * mode 0 增益：阶段 7 固定 ×1.5，在正常亮度下会把 **26.7% 的像素打到 255**。
            现在按实测亮度反推：越暗增益越大（最多 ×2），到目标亮度就回到 ×1.0，
            所以**不会过曝**。
          * mode 1 逆光补偿：阶段 7 只在 <96 / >160 两端起作用，中间 96~160 原样不动，
            普通画面里几乎看不出变化。现在改成以 128 为中心的**全区间**补偿
            （暗部提亮 + 亮部压下），强度按对比度反推 —— 反差越大补得越狠。
          * mode 2 锐化：阶段 7 固定 |Δ|/2。现在按细节量反推，
            细节少时锐化更强（最多接近全强度 |Δ|），细节多时收敛到 0.5 倍以免放大噪声。

所以同一个模式内部参数也在动 —— 这才是「自适应」，而不是「三档查表」。

物理量换算（必须和 lib/ai_video_regs.py 的 MLP_FEAT_SHIFT、make_demo_csv.py 一致）
    f1 = luma      * 0.879
    f2 = (luma²+var)* 0.00343
    f3 = 平均|ΔY|  * 14.06
"""
import csv
import math
import os

PARAM_MIN = 128          # 参数下限：三种模式在这个值上分别是 ×1.0 / ±32 / |Δ|/2
PARAM_MAX = 255

# 四象限空间决策的默认阈值。已用本项目 hard pair 实测标定
# （2026-10-19，240 帧，见 docs/results/hard_pairs.md）：
#   均匀暗场   u=0.101
#   均匀正常光 u=0.267
#   暗场+亮窗  u=2.168
#   正常+逆光  u=1.151
# 因此：
#   u >= U_HI : 空间明显不均（窗口/侧光）-> 优先逆光补偿
#   u <= U_LO : 照明均匀 -> 信任 MLP 的 0/2 分类
#   中间      : 不确定 -> 保持当前模式，避免在边界来回切
# 0.30/0.55 把实测的“均匀簇”（0.10~0.27）和“逆光簇”（1.15~2.17）都包住了。
SPATIAL_U_HI = 0.55
SPATIAL_U_LO = 0.30


def clamp(v, lo=PARAM_MIN, hi=PARAM_MAX):
    return max(lo, min(hi, int(round(v))))


# ---------------------------------------------------------------------------
# 三类中心 / 散布：**从 data/features.csv 现场算**，不再写死。
#
# 为什么必须改成读文件：这批数据重训之后三类中心会动
# （实测 暗光 9.8→16.8、逆光 67.4→63.7、常规 109.3→89.4）。
# 写死的中心会让置信度门限指着错的地方，后果很隐蔽：
#   常规档特征 (89,38,38) 离「旧中心」(109.3,54.7,34.6) 有 26.3，
#   而门限是 25 → 每次都被判成「不可信」→ mode 2 永远切不进去。
#
# 读不到 CSV 时退回出厂参考值（第一版数据实测），保证脚本不会因为缺文件而崩。
# ---------------------------------------------------------------------------
FALLBACK_CLASS_MEAN = {0: (9.8, 1.0, 24.7), 1: (67.4, 39.1, 29.6), 2: (109.3, 54.7, 34.6)}
FALLBACK_CLASS_STD = {0: (0.4, 0.0, 0.5), 1: (2.5, 1.7, 0.9), 2: (4.5, 4.2, 5.3)}
CLASS_NAME = {0: "暗光", 1: "逆光", 2: "常规/细节"}


def _norm(v):
    return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)


def load_class_stats(csv_path=None):
    """从 data/features.csv 算每类的均值与标准差。

    Returns
    -------
    (mean, std, source)   source 取 "features.csv" 或 "fallback"
    """
    here = os.path.dirname(os.path.abspath(__file__))
    path = csv_path or os.path.join(os.path.dirname(here), "data", "features.csv")
    try:
        acc = {}
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                acc.setdefault(int(row["label"]), []).append(
                    (float(row["f_luma"]), float(row["f_luma2"]), float(row["f_grad"])))
        if sorted(acc) != [0, 1, 2]:
            raise ValueError("features.csv 里不是三类")
        mean, std = {}, {}
        for k, rows in acc.items():
            n = float(len(rows))
            mean[k] = tuple(sum(r[i] for r in rows) / n for i in range(3))
            std[k] = tuple((sum((r[i] - mean[k][i]) ** 2 for r in rows) / n) ** 0.5
                           for i in range(3))
        return mean, std, "features.csv"
    except Exception:
        return dict(FALLBACK_CLASS_MEAN), dict(FALLBACK_CLASS_STD), "fallback"


CLASS_MEAN, CLASS_STD, CLASS_STATS_SOURCE = load_class_stats()


def suggest_confidence(class_mean=None, class_std=None):
    """按当前三类中心推荐**每类**的置信度门限，返回 {类: 门限}。

    每类的门限 = max(2.5 × 该类的散布半径, 0.5 × 它到最近那一类的中心距)

      * 第一项保证「正常场景的正常抖动」不会被拒（2.5 倍散布半径）；
      * 第二项保证「中间地带」会被拒 —— 比最近邻中心距的一半还远就分不清了。

    为什么按类给不同门限：暗光类散布大（f_luma std 8+）、离最近的中心有 53，
    门限就该宽松（~27）；逆光和常规只隔 29、散布 4，门限就该紧（~15）。
    一个统一数字做不到这件事 —— 这正是原来写死 25 会出错的地方。
    """
    mean = class_mean or CLASS_MEAN
    std = class_std or CLASS_STD
    out = {}
    for k in (0, 1, 2):
        others = [j for j in (0, 1, 2) if j != k]
        gap = min(_norm(tuple(mean[k][i] - mean[j][i] for i in range(3))) for j in others)
        out[k] = round(max(2.5 * _norm(std[k]), 0.5 * gap), 1)
    return out


CONFIDENCE_BY_CLASS = suggest_confidence()
# 兼容用：只传一个数时（例如 --confidence 25）所有类共用它；这里取最紧的那一类，
# 宁可严一点也别把中间地带的样本放进来。
DEFAULT_CONFIDENCE = min(CONFIDENCE_BY_CLASS.values())


def set_class_stats(mean, std):
    """把模块的中心 / 散布 / 门限整体换成另一份。

    注意：suggest_confidence() 只是**算**，不会改全局；要真的换中心必须调用这个，
    否则会出现「门限按一份数据算、距离按另一份数据量」的错配
    （这种错配排查起来很费劲，所以这里给一个显式接口）。
    """
    global CLASS_MEAN, CLASS_STD, CONFIDENCE_BY_CLASS, DEFAULT_CONFIDENCE
    CLASS_MEAN = {k: tuple(float(x) for x in mean[k]) for k in (0, 1, 2)}
    CLASS_STD = {k: tuple(float(x) for x in std[k]) for k in (0, 1, 2)}
    CONFIDENCE_BY_CLASS = suggest_confidence(CLASS_MEAN, CLASS_STD)
    DEFAULT_CONFIDENCE = min(CONFIDENCE_BY_CLASS.values())
    return CONFIDENCE_BY_CLASS


def reload_from_csv(csv_path=None):
    """重新读 data/features.csv 并刷新中心 / 门限。返回数据来源（"features.csv" / "fallback"）。

    什么时候用：板子上刚重训完（features.csv 变了），而进程还活着的时候。
    """
    global CLASS_STATS_SOURCE
    mean, std, src = load_class_stats(csv_path)
    CLASS_STATS_SOURCE = src
    set_class_stats(mean, std)
    return src


def distance_to_center(features, cls):
    """特征到某一类中心的欧氏距离。"""
    a, b, c = CLASS_MEAN[cls]
    f1, f2, f3 = features
    return ((f1 - a) ** 2 + (f2 - b) ** 2 + (f3 - c) ** 2) ** 0.5


def distance_norm(features, cls):
    """**归一化空间**的距离 —— 和 MLP 训练/推理时的度量一致。

    为什么要单独有这个：distance_to_center() 是不归一化的欧氏距离，而模型是在
    (x-mean)/std 空间里学的边界。类内 std 差别大时，两者会给出**不同的最近类**：
    实测点 (34,8,40) 不归一化时离暗光最近（34.3）、归一化后离逆光最近（12.5），
    而模型吃的是后者。所以判"这次判决可不可信"必须用归一化距离。
    """
    s = CLASS_STD.get(cls)
    if not s:
        return distance_to_center(features, cls)
    return math.sqrt(sum(
        ((features[i] - CLASS_MEAN[cls][i]) / (s[i] if s[i] > 1e-9 else 1.0)) ** 2
        for i in range(3)))


def nearest_class(features):
    """离得最近的那一类（只用于诊断/打印）。"""
    return min(CLASS_MEAN, key=lambda k: distance_to_center(features, k))


# 归一化距离的宽松上界。取值依据（2026-10-13 实测）：
#   * 正常演示帧都在 6σ 以内（常规 (98,69,30) 是 0.2σ、(121,85,29) 是 3.8σ、(119,87,26) 是 5.6σ）；
#   * 真正的外推乱判点是 21σ（(34,8,40) 被判 0）和 61σ（(51,24,29) 被判 0/2）。
# 12σ 正好卡在两者之间：不误杀正常帧，又能挡住"完全外推"的判决。
NN_SIGMA_MAX = 12.0


def is_confident(features, cls, threshold=None, nearest_slack=1.5):
    """MLP 判成 cls 时，这次判决值不值得信。

    默认（threshold=None）用**归一化空间**的两条规则 —— 因为 MLP 就是在归一化空间里
    学的边界，用别的度量判它"可不可信"会得出相反结论：

      A) 离 cls 中心 ≤ NN_SIGMA_MAX(8σ)    —— 宽松上界，只挡完全外推的点
      B) cls 必须是（1.5 倍余量内）**最近类**

    为什么要有 B（2026-10-13 实测）：(34,8,40) 被判成 0，而它在归一化空间离逆光 12.6、
    常规 15.9、暗光 21.2 —— 模型给的是"几何上最远的那个类"，属于外推乱判。
    加 B 之后这类判决被拒，180 次轮询里那 39 次"该切"的误判就没了。

    为什么不把 A 也写成"不归一化距离 ≤ 逐类门限"：那份逐类门限（暗光 36 / 逆光 30 /
    常规 28）会被类内 std 撑得很大或很小，实测把正常的偏亮常规帧 (121,85,29) 也卡掉了
    （它离常规中心 29.5 只比门限 28.4 大一点点，可它在归一化空间只有 3.8σ，完全正常）。

    threshold 传正数 = 改用"不归一化距离 ≤ threshold"（保留给 --confidence 显式给数）；
    传 <= 0 = 关掉整条门限（永远返回 True）。
    """
    if threshold is not None and threshold <= 0:
        return True                                   # 显式关掉
    d_self_n = distance_norm(features, cls)
    d_min_n = min(distance_norm(features, k) for k in (0, 1, 2))
    if d_self_n > d_min_n * nearest_slack:            # 规则 B
        return False
    if threshold is None:                             # 规则 A（默认口径）
        return d_self_n <= NN_SIGMA_MAX
    return distance_to_center(features, cls) <= threshold


def physical(features):
    """(f1,f2,f3) -> (luma, contrast, sharpness) 三个物理量。"""
    f1, f2, f3 = features
    luma = f1 / 0.879
    var = (f2 / 0.00343) - luma * luma
    return luma, math.sqrt(max(var, 0.0)), f3 / 14.06


def gain_param(f1, target=None, floor=None):
    """mode 0（增益）的连续参数：亮度越低于目标，增益越大；到目标就回到 ×1.0。

    f1 是硬件特征（≈ 平均亮度 × 0.879）。两个锚点默认取**当前数据**的类中心：
      target = 常规档中心（"已经够亮"的参考）
      floor  = 暗光档中心（"最暗"的参考）
    （写死的 110 / 15 只作为读不到 features.csv 或数据异常时的兜底。）
      f1 <= floor  -> 255（×1.99，最亮）
      f1 >= target -> 128（×1.0，不动）
      中间线性过渡
    这样做的好处：**不会过曝**。阶段 7 固定 ×1.5 在正常亮度下会把 26.7% 像素打到 255。
    """
    if target is None:
        target = CLASS_MEAN[2][0]
    if floor is None:
        floor = CLASS_MEAN[0][0]
    if target - floor < 10.0:
        target, floor = 110.0, 15.0
    if f1 >= target:
        return PARAM_MIN
    if f1 <= floor:
        return PARAM_MAX
    k = (target - f1) / (target - floor)
    return clamp(PARAM_MIN + (PARAM_MAX - PARAM_MIN) * k)


def class_contrast(cls):
    """某一类中心的物理对比度（std）。"""
    return physical(CLASS_MEAN[cls])[1]


def stretch_param(contrast, lo=None, hi=None):
    """mode 1（逆光补偿）的连续参数：**对比度越高，补偿越强**。

    两个锚点默认取**当前数据**的类对比度：
      lo = 三类里对比度最低的那个（不需要补）
      hi = 三类里对比度最高的那个（反差最大 -> 补得最狠）
    （第一版数据实测是 13 / 22 / 74；改成读实时数据后，重采重训都会自动跟着变。）

    逆光补偿做的事是「暗部提亮 + 亮部压下来」——也就是把整体往中间调靠、
    压低反差，让逆光场景里的主体能看清。所以**场景反差越大，补得越狠**才合理。
    （修订 03 把方向反过来了：之前写成"对比度低才补得狠"，那是错的。）

        contrast <= lo -> PARAM_MIN(128) 轻微补偿
        contrast >= hi -> PARAM_MAX(255) 最强补偿

    注意：这个模式下 PARAM 越大，输出 std 越小（因为它在**压**对比），
    方向感和 mode 0 / mode 2 相反，别拿"std 变大"来判断它生效。
    """
    if lo is None or hi is None:
        cs = [class_contrast(k) for k in (0, 1, 2)]
        if max(cs) - min(cs) < 8.0:
            lo_, hi_ = 20.0, 80.0
        else:
            # 上锚点留 20% 余量：演示时画面反差常常比训练集更大，
            # 不留余量的话 PARAM 会一路贴在上限、看不出"连续变化"。
            lo_, hi_ = min(cs), max(cs) * 1.2
        lo = lo_ if lo is None else lo
        hi = hi_ if hi is None else hi
    if contrast <= lo:
        return PARAM_MIN
    if contrast >= hi:
        return PARAM_MAX
    k = (contrast - lo) / (hi - lo)
    return clamp(PARAM_MIN + (PARAM_MAX - PARAM_MIN) * k)


def sharpen_param(f3, strong=None, weak=None):
    """mode 2（锐化）的连续参数：细节越少锐化越强。

    f3 是硬件特征（≈ 平均|ΔY| × 14.06）。两个锚点默认取**当前数据**的类中心：
      strong = 细节最少的类 -> 锐化最强（接近全强度 |Δ|）
      weak   = 细节最多的类 -> 收敛到 |Δ|/2，避免放大噪声
    （第一版数据实测三档中心 25 / 30 / 35；现在跟着 features.csv 走。）
    """
    if strong is None:
        strong = max(0.0, min(CLASS_MEAN[k][2] - 2.0 * CLASS_STD[k][2] for k in (0, 1, 2)))
    if weak is None:
        # 上锚点 = 训练集里"细节最多"的那一类 +2σ 再留 40% 余量。
        # 为什么留余量：实测（2026-10-13）演示时 f3 = 33~43，而训练集最大值约 32，
        # 不留余量的话 k 恒为 0 -> PARAM 一直贴在 128，"连续自适应"在 mode 2 上看不出来。
        weak = max(CLASS_MEAN[k][2] + 2.0 * CLASS_STD[k][2] for k in (0, 1, 2)) * 1.4
    if weak - strong < 5.0:
        strong, weak = 20.0, 40.0
    if f3 >= weak:
        return PARAM_MIN
    if f3 <= strong:
        return PARAM_MAX
    k = (weak - f3) / (weak - strong)
    return clamp(PARAM_MIN + (PARAM_MAX - PARAM_MIN) * k)


def decide(features, mlp):
    """核心入口：给 (f1,f2,f3) 和 MLP 判决，返回 (mode, param, 说明)。

    mode 直接沿用 MLP 的三分类（0 暗光 / 1 逆光 / 2 常规），
    param 由上面三个函数按实时特征算出来。
    """
    luma, contrast, sharp = physical(features)
    if mlp == 0:
        p = gain_param(features[0])
        return 0, p, "增益 ×%.2f (luma=%.0f)" % (p / 128.0, luma)
    if mlp == 1:
        p = stretch_param(contrast)
        return 1, p, "逆光补偿 ±%d (contrast=%.0f)" % ((p * 127) >> 9, contrast)
    p = sharpen_param(features[2])
    return 2, p, "锐化 ×%.2f (f3=%d)" % (p / 256.0, features[2])


def param_for(features, mlp):
    """只要 (param, 说明) —— 给调度脚本用。

    为什么要单独包一层：`decide()` 返回 3 个值 (mode, param, why)，
    调用方写成 `p, why = decide(...)` 会直接 ValueError。
    这个坑在 notebook 和 auto_schedule.py 里各踩过一次，
    所以干脆提供一个只返回 2 个值的接口，以后脚本统一用这个。
    """
    _mode, p, why = decide(features, mlp)
    return p, why


def spatial_unevenness(quads):
    """四象限不均匀度 u = (最亮 - 最暗) / 四块均值。

    quads 是硬件寄存器 0x38/0x3C 解出来的 (左上, 右上, 左下, 右下)，
    单位是该象限的 sumY >> 16。均匀照明接近 0，窗口/侧光明显大于 0。

    暗场保护：四块均值很小时（纯黑/噪声底），比值会被噪声放大，
    这时直接返回 0，让决策回到 MLP，不要凭噪声切模式。
    """
    if quads is None:
        return 0.0
    q = [float(v) for v in quads]
    if len(q) != 4:
        return 0.0
    avg = sum(q) / 4.0
    if avg < 5.0:
        return 0.0
    return (max(q) - min(q)) / avg


def decide_spatial(features, quads, mlp, u_hi=None, u_lo=None):
    """在 MLP 判决之上加一层“空间布局”决策，返回 (mode, param, 说明)。

    为什么需要它：三个全局特征（平均亮度/亮度平方/水平梯度）分不清
    “整体偏亮”和“中间暗、四周亮”的逆光；四象限统计已经在硬件里，
    但原来的 decide()/auto_schedule 完全没用它。

    规则（先用保守的三段式，阈值必须用 hard pair 标定）：
      u >= u_hi : 空间不均 -> mode 1（逆光补偿）。
                  即使 MLP 判 0（暗光），也不要用 mode 0 全局增益，
                  否则画面里的亮窗/灯会被打到 255。
      u <= u_lo : 照明均匀 -> 信任 MLP 的 0/2；mode 1 也按普通强度算。
      中间      : 返回 mode=None，让调用方保持当前模式（迟滞）。

    mode=None 是**有意**的：空间不确定时“不动”比“乱切”好。
    """
    u_hi = SPATIAL_U_HI if u_hi is None else float(u_hi)
    u_lo = SPATIAL_U_LO if u_lo is None else float(u_lo)
    if u_hi < u_lo:
        u_hi, u_lo = u_lo, u_hi

    if quads is None:
        m, p, why = decide(features, mlp)
        return m, p, why + "（无四象限数据）"

    u = spatial_unevenness(quads)
    if u >= u_hi:
        _, contrast, _ = physical(features)
        p = stretch_param(contrast)
        return 1, p, ("空间不均 u=%.2f（quads=%s）-> 逆光补偿 ±%d"
                      % (u, tuple(int(v) for v in quads), (p * 127) >> 9))

    if u <= u_lo:
        m, p, why = decide(features, mlp)
        return m, p, "照明均匀 u=%.2f -> 信任 MLP：%s" % (u, why)

    return None, None, "空间不确定 u=%.2f（quads=%s）-> 保持当前模式" % (
        u, tuple(int(v) for v in quads))


def describe():
    """给日志/文档用的一句话说明。"""
    return ("连续自适应：mode 仍由 MLP 决定，强度 PARAM 按实测特征实时算 —— "
            "暗光按亮度反推增益(不过曝)、逆光按对比度反推补偿强度、常规按细节量反推锐化")
