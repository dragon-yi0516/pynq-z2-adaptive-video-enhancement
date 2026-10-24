# 阶段 12 验收清单：连续参数 + 四象限统计

对应 `docs/05_optimization_plan.md` 的步骤 1~3。

## 这一版相对阶段 7 改了什么

| 项目 | 阶段 7（v1.6 / 0x0001_0407） | 阶段 12（v2.0 / 0x0001_030C） |
|------|-------------------------------|--------------------------------|
| 处理强度 | 三种模式**写死** | `PARAM` 寄存器**连续可调** |
| 模式 0 增益 | 固定 ×1.5（正常亮度下 26.7% 像素饱和） | ×(PARAM/128)，默认 192 仍是 ×1.5 |
| 模式 1 拉伸 | 只在 <96 / >160 起作用，96~160 不变 | 以 128 为中心的**全区间**拉伸 |
| 模式 2 锐化 | 固定 \|Δ\|/2（水平差分只 +26%） | \|Δ\|*PARAM/256，最大接近 \|Δ\| |
| 空间信息 | 只有全局 sumY | 多 4 个象限 sumY（0x38 / 0x3C） |
| 数据通路 | — | **结构没动**，还是 px1_* 两级 + 3 级统计流水 |

## 1. 构建（虚拟机）

    cd ~/OV5640_capture_only/ai_video
    bash build_overlay.sh 12

**必须满足**：

- 日志出现 `== 时序收敛：OK ==`（有 WNS < 0 就不算通过）
- 最后出现 `#  阶段 12 全部完成`
- 没有 `[HDL 9-806] Syntax error` 之类的打包错误

> 时序风险点：三种模式的参数化乘法（`c * param`）会在像素路径上加一级 8x8 乘法，
> 四象限统计加了一组 32 位加法器。如果违例，把 `logs/stage12_*.log` 发回来，
> 通常可以把 PARAM 从「乘法系数」改成「移位档位」来省掉乘法器。

### 修订 02 已经踩过并修掉了这个坑

修订 01 第一次综合的结果：**WNS = -3.798 ns**，违例路径**全部**是同一条：

    Source:      axis_video_proc_0/inst/px2_g_reg[1] / px1_r_reg[2]   （像素寄存器）
    Destination: axis_video_proc_0/inst/m_tdata_r_reg[...]            （输出寄存器）

也就是「像素寄存器 -> 乘法/差值 -> 移位 -> 饱和 -> 输出寄存器」全挤在一拍里。
**阶段 7 这条路径本来就只有 +0.134 ns 余量（已经吃满）**，再塞一个 8x8 乘法就爆了。

**修订 02 的修法**：把单通道处理拆成 A（乘法）/ B（移位+饱和）两级，
中间加一组寄存器，控制信号 v/u/l 也跟着延迟一级。功能完全不变，像素输出晚 1 拍。

## 2. 版本与寄存器（板上）

    from lib.ai_video_regs import AiVideoRegs
    regs = AiVideoRegs(ol.axis_video_proc_0)
    print("VERSION = 0x%08X (阶段 %d)" % (regs.version(), regs.version_stage()))
    print("has_param =", regs.has_param())
    print("PARAM =", regs.param())
    print("四象限 =", regs.quads(), " 不均匀度 =", regs.spatial_unevenness())

- `VERSION` = **0x0001030C**（家族 1 / 修订 03 / 阶段 12）。
      别念成 `0x0000030C` —— 编码是 `0x0001_RRSS`：SS=阶段号（0x0C=12）、RR=修订号（0x03）。
- `has_param()` 为 True
- 上电默认 `PARAM` = **192**
- 四个象限值都 > 0（说明行列计数在跑）；遮住画面左上角，左上的值应明显下降

## 3. 连续参数真的生效（关键验收）

固定模式扫 PARAM，看指标**单调变化**：

    import numpy as np
    for mode in (0, 1, 2):
        for p in (128, 160, 192, 224, 255):
            regs.set_mode(mode); regs.set_param(p)
            for _ in range(3): regs.wait_new_frame()
            f = vp.frame_to_rgb(vp.capture_frame(vdma0)).astype(np.float32)
            print("mode%d PARAM=%3d 均值=%6.1f std=%6.1f 水平差分=%6.2f 饱和=%5.1f%%"
                  % (mode, p, f.mean(), f.std(),
                     np.abs(np.diff(f, axis=1)).mean(), 100.0*(f>=255).mean()))

- mode 0：PARAM 128→255，**均值单调上升**；PARAM=128 时饱和率 ≈ 0
- mode 1：PARAM 越大 **std 越小**（它在压对比，方向和其他两档相反）；
      而且**中间调（96~160）也会变**（阶段 7 对这一段完全不动）
      —— 实测：PARAM 128→255 时均值 76.5→93.3、std 15.7→10.5，符合预期
- mode 2：PARAM 越大 **水平差分越大**；PARAM=128 约等于阶段 7 的效果

## 4. 连续自适应调度

- 把 `07_auto_schedule.ipynb` 第 10 格的 cmd 加上 `"--adaptive"`
- 日志里出现 `按 --adaptive：...` 一行
- 每次 `切换模式 x -> y` 后面多出 `PARAM=... (...)`，且 PARAM 会随场景变
- 最后一行仍然是 `共切换 N 次，因 min_hold(2.0s) 被挡下 M 次，运行 X 秒`

## 5. 出问题时的回退

| 现象 | 处理 |
|------|------|
| 时序不收敛 | 退回阶段 7 的 bit（`overlay/backup/`），把日志发出来 |
| 打包报语法错 | 先 `python3 tools/check_verilog.py`，再把 Vivado 报的行号发出来 |
| 象限值不对 | 只影响新功能，主特征/视频通路不受影响；先不读它即可 |
| `--adaptive` 报错 | 不传这个开关就退化成阶段 7 的固定强度行为 |

---

## 2026-10-13 复测补充

* `VERSION` 板上实测 **0x0001030C**（家族 1 / 修订 03 / 阶段 12）✓
* 用新数据（540 帧）重训后，三类中心 = **10 / 67 / 97**（f_luma），
  比第一版的 10 / 67 / 109 略暗一点 —— 这是盒子标定的结果，不是错误。
* **自适应门限改成归一化口径**（`lib/adaptive.py`）：默认"归一化距离 ≤ 12σ 且判决类必须是最近类"。
  逐类距离门限只在 `--confidence` 显式给数时用。
* 演示/验证的三个 notebook（05/06/07）现在都锁同一档曝光：**736 行 + 增益 0x20**
  （单一来源 = `lib/exposure.py` 的 `WORKPOINT`），否则特征会整体偏移、三类中心对不上。
