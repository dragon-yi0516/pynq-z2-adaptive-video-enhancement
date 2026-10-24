# AXI-Lite 寄存器映射（唯一权威定义）

所有阶段的 HDL、notebook、`.py` 都引用这一份地址，禁止各写一套。
在 Python 侧对应的常量在 `lib/ai_video_regs.py`。

基地址由 Vivado 的 Address Editor 分配。**注意：每次重新插 BD（`build_overlay.sh`）
都会重新分配** —— 2026-10-13 那次是 `0x44A00000`，更早是 `0x43C00000`。
所以脚本里**别写死**，用 `ol.ip_dict["axis_video_proc_0"]["phys_addr"]` 读
（`07_auto_schedule.ipynb` 就是这么做的；`auto_schedule.py --base` 手工指定时也要用这个值）。
Python 里用 `ol.axis_video_proc_0.read(offset)` 访问，`offset` 就是下表偏移。

| 偏移 | 名称 | 读写 | 位宽 | 含义 |
|------|------|------|------|------|
| 0x00 | `MLP_OUTPUT`  | R   | 32 | bit[1:0] = MLP 分类结果 0/1/2 |
| 0x04 | `MODE_SEL`    | R/W | 32 | bit[1:0] = 可重构阵列模式 0/1/2；bit7 = **HDMI 分屏开关（阶段 13 才有）**。阶段 12 的 HDL 不实现这一位：写 1 读回也是 1，但屏幕不会分屏 —— 所以演示脚本要先 `regs.has_split()` 自检，别让这一幕"假成功" |
| 0x08 | `STATUS`      | R   | 32 | bit0 推理完成、bit1 帧边界、bit2 统计就绪 |
| 0x0C | `VERSION`     | R   | 32 | 常量 `0x0001_0000`（用于确认 IP 真的挂上了） |
| 0x10 | `LUMA_SUM`    | R   | 32 | 上一整帧 `sum(Y)` |
| 0x14 | `LUMA_SQ_SUM` | R   | 32 | 上一整帧 `sum(Y^2)` 的**低 32 位** |
| 0x18 | `GRAD_SUM`    | R   | 32 | 上一整帧 `sum(|相邻像素梯度|)` |
| 0x1C | `FRAME_CNT`   | R   | 32 | 已完成帧计数（每帧 +1） |
| 0x20 | `VBLANK_CNT`  | R   | 32 | 帧边界计数（见下面“为什么没有真正的 VBlank”） |
| 0x24 | `LUMA_SQ_SUM_HI` | R | 32 | `sum(Y^2)` 的**高 16 位**（bit[15:0]） |
| 0x28 | `PIXEL_CNT`   | R   | 32 | 上一帧参与统计的像素个数 |
| 0x2C | `MLP_START_CNT` | R | 32 | 硬件一共发出过几次 MLP 启动（诊断用，阶段 6 修订 02 起） |
| 0x30 | `MLP_DONE_CNT`  | R | 32 | 硬件一共收到过几次 MLP 完成（诊断用） |

### 阶段 12 新增（硬件版本 `0x0001_030C` 起可读；旧硬件读到 0）

> 注意：阶段 12 的**修订 01/02** 有地址译码 bug（`reg_read` 里把 0x34/0x38/0x3C
> 写成了字索引 6'h0D/0E/0F），**写进去生效但读回来恒为 0**。
> 修订 03（`0x0001_030C`）已修。如果你读 `PARAM` 或四象限一直是 0，先确认 VERSION。

用 `regs.has_param()` 判断有没有这几个寄存器。

| 偏移 | 名字 | 读写 | 位宽 | 说明 |
|------|------|------|------|------|
| 0x34 | `PARAM` | R/W | 8 | **连续强度参数**（帧边界生效）。三个模式共用，含义随 `MODE_SEL` 变：<br>mode 0 增益：倍数 = `PARAM/128`（128=×1.0，192=×1.5，255=×1.99）<br>mode 1 对比拉伸：最多 ±`(PARAM*127/512)` 灰度（128→±32，255→±63）<br>mode 2 锐化：强度 = `PARAM/256`（0=直通，128=`\|Δ\|/2`，255≈`\|Δ\|`） |
| 0x38 | `QUAD_TL_TR` | R | 32 | 四象限亮度统计：[31:16]=右上、[15:0]=左上，值 = 该象限 `sumY >> 16` |
| 0x3C | `QUAD_BL_BR` | R | 32 | 同上：[31:16]=右下、[15:0]=左下 |

**为什么要象限统计**：只看全局 `sumY`，一个"上亮下暗的逆光"和"整体偏亮"可能差不多。
切成 4 块分别求和后，PS 端算 `(max-min)/mean` 就能把"空间不均匀"单独量出来
（`regs.spatial_unevenness()`），答辩时用来回应"这是不是纯亮度分类器"。

> 阶段 12 的 PARAM 默认值是 **192**：让 mode 0 仍然是阶段 7 那个 ×1.5，
> 而 mode 1/mode 2 的默认强度比阶段 7 更强（这是要修的那个"效果不明显"）。

## VERSION 的编码：`0x0001_RRSS`

* 高 16 位 `0x0001` = IP 家族号；
* `RR` = 修订号（同一阶段内的第几版）；
* `SS` = 阶段号。

例子：`0x0001_0206` = 家族 1、修订 02、阶段 6。
`ai_video_regs.py` 里 `version_stage()` / `version_revision()` 就是拆这两个字节。

## `MLP_START_CNT` / `MLP_DONE_CNT` 怎么用（排查 MLP_OUTPUT 一直是 0）

| 现象 | 说明卡在哪 | 怎么办 |
|------|-----------|--------|
| `MLP_START_CNT` **不动** | 启动请求没发出去 | 检查视频流在不在（`FRAME_CNT` 是否递增）、`mlp_start`/`ap_start` 是否连上 |
| `START` 在涨、`DONE` **不动** | 启动了但没收到完成 | 检查 MLP 时钟/复位（`ap_clk`/`ap_rst`，`ap_rst` 是高有效，必须经反相器）、`ap_done` 是否接对 |
| 两个都在涨，但 `MLP_OUTPUT` 不对 | 结果没接对 | 检查 `ap_return` → `mlp_result` 那根线 |
| 两个都在涨，`MLP_OUTPUT` 也在变 | 正常 | — |

## 软件侧由硬件原始累加值换算出的三个特征

硬件只给原始累加值，除法/开方在 Jupyter 做（省 DSP，也方便改公式）：

```python
psum  = rd(PIXEL_CNT) or 1
luma      = rd(LUMA_SUM) / psum
luma2     = ((rd(LUMA_SQ_SUM_HI) << 32) | rd(LUMA_SQ_SUM)) / psum
contrast  = sqrt(max(luma2 - luma * luma, 0.0))      # 标准差
sharpness = rd(GRAD_SUM) / psum
```

> 上面这三个是**物理量**，只用于人工检查（例如“遮镜头亮度应该掉下来”）。
> 它们**不是** MLP 的输入，别拿去训练。

## MLP 真正吃的三个特征（重要）

FPGA 里零成本能做的只有加法和移位。所以 MLP 的输入直接由累加值右移得到：

| MLP 输入 | 来源 | 移位 | 取值范围 | 物理含义 |
|---------|------|------|---------|---------|
| `f_luma`  | `LUMA_SUM`    | >> 20 | 典型 85~110，上限 224 | ≈ luma × 0.879 |
| `f_luma2` | `LUMA_SQ_SUM` | >> 28 | 典型 33~60，上限 223 | ≈ (luma² + 方差) × 0.00343 |
| `f_grad`  | `GRAD_SUM`    | >> 16 | 典型 16~48，上限 3586 | ≈ 平均\|ΔY\| × 14.06 |

移位值在 `lib/ai_video_regs.py` 的 `MLP_FEAT_SHIFT` 里定义，
Python 侧 `mlp_features()` / HDL 侧 `reg_f1_r/reg_f2_r/reg_f3_r` 必须一致。

为什么这样定：

* 三个量级都被拉到 0~224，Q8.8 权重才不会因为某个特征量级太大而被量化成 0；
* 都在 int16 范围内，定点乘加不会溢出（`quantize()` 会做最坏情况检查）；
* 全部只靠移位，不占乘法器、不占 BRAM。

`data/features.csv` 里的三列就是这三个值。

## 为什么没有“真正的 VBlank”

当前项目里自定义 IP 挂在纯 AXI4-Stream 像素流上（`demosaic -> IP -> VDMA0`），
这条流里**没有**独立的 `vsync/vblank` 信号，只有：

* `tuser` = 一帧的第一个像素（帧起始）
* `tlast` = 一行最后一个像素（行尾）

所以：

* `VBLANK_CNT` 统计的是**帧边界事件**（每个 `tuser` 上升沿 +1），
  它就是这条流水线上唯一可以“无撕裂切换”的时刻。
* `MODE_SEL` 在 IP 内部**被 tuser 重新采样**成 `mode_active`，
  也就是说你在任意时刻写 `MODE_SEL`，硬件都会等到下一帧开始才真正生效，
  从根上避免“半帧换模式”导致的撕裂。

这就是为什么 `07_auto_schedule.ipynb` 里 `wait_vblank()` 用 `VBLANK_CNT`
轮询即可，而不需要 CPU 精确对准某个时序信号。

## 统计快照的一致性

累加器是“活”的（每来一个像素就加），但 4 个读数寄存器在**每个 tuser 时被锁存**：

```
tuser 上升沿:  LUMA_SUM/LUMA_SQ_SUM/GRAD_SUM/PIXEL_CNT <- 活累加器
               活累加器清零，重新开始统计下一帧
               FRAME_CNT += 1, VBLANK_CNT += 1, STATUS.bit1 = 1 一拍
```

因此 Jupyter 读到的永远是**上一整帧的完整统计**，不会读到算了一半的中间值，
也不需要在软件侧做“读两遍看是否相等”的防抖。

---

## 读特征 / 四象限寄存器之前，必须先把采集通道启动起来

这个 IP 里所有累加器（`LUMA_SUM / LUMA_SQ_SUM / GRAD_SUM / PIXEL_CNT / QUAD_TL_TR / QUAD_BL_BR`）
都只在 **beat（`tvalid & tready`）**时累加。而 `vs.bring_up()` **不启动采集** —— 它只做
加载 overlay + 配摄像头 + 启动 demosaic + 建立 VDMA。所以必须再补一句：

```python
from lib import video_path as vp
from lib.ai_video_regs import LUMA_SUM, PIXEL_CNT

vp.start_capture(vdma0, mode)                    # 启动 VDMA0 的 S2MM
regs.wait_new_frame(); regs.wait_new_frame()     # 等 1~2 帧，读到的才是整帧统计
print("PIXEL_CNT =", regs.rd(PIXEL_CNT))         # 应 ≈ 921600
print("LUMA_SUM  =", regs.rd(LUMA_SUM))          # 应非 0
print("四象限 =", regs.quads())                  # 每块几百，且四块不一样
vs.stop_all_channels(vdma0, vdma1)
```

**2026-10-14 实测踩过**：只 `bring_up` 不启动采集，`quads()` 四项全 `0`，
看着像 HDL 坏了 —— 其实是没像素流过。

期望量级：单象限 = 640×360 像素的 `sumY >> 16` ≈ 该象限平均亮度 × **3.5**
（正常场景每块几百）。四块**不一样**才说明空间信息有效 —— 用逆光那种
「上亮下暗」的画面测，差异最明显，答辩可以直接演示这个。
