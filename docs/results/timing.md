# 时序、资源与实现签核

## 1. 报告来源

最终证据来自 Vivado 2024.2 的 stage13 工程：

```text
/home/xu/OV5640_capture_only/bitstream/cv_ov5640/cv_ov5640.xpr
impl_1: PROGRESS=100% / STATUS=write_bitstream Complete!
```

报告目录：`stage13_split/reports/stage13/`。

| 文件 | 用途 |
|---|---|
| `timing_final.rpt` | setup / hold / pulse-width 与关键路径 |
| `util_final.rpt` | LUT / FF / BRAM / DSP 资源 |
| `drc_final.rpt` | routed design 的 DRC |
| `methodology_final.rpt` | 时钟、约束与实现方法学检查 |
| `report_source.txt` | 工程、工具版本、运行状态和生成时间 |

## 2. 时序摘要（post-route）

| 指标 | 结果 | 判定 |
|---|---:|---|
| WNS | **+0.120 ns** | 通过 |
| TNS | **0.000 ns** | 通过 |
| TNS 失败端点 | **0** | 通过 |
| WHS | **+0.016 ns** | 通过 |
| THS | **0.000 ns** | 通过 |
| THS 失败端点 | **0** | 通过 |
| WPWS | **+0.538 ns** | 通过 |
| TPWS 失败端点 | **0** | 通过 |

报告中同时写明：`All user specified timing constraints are met.`

`clk_fpga_0` 的 100 MHz 约束内路径共有 59,272 个 setup/hold endpoint，
全部通过；最差 setup slack 为 +0.120 ns，最差 hold slack 为 +0.016 ns。

## 3. 资源

| 资源 | 已用 | 可用 | 比例 |
|---|---:|---:|---:|
| Slice LUT | 15,862 | 53,200 | **29.82%** |
| Slice Register | 20,736 | 106,400 | **19.49%** |
| Block RAM Tile | 31.5 | 140 | **22.50%** |
| DSP48E1 | 58 | 220 | **26.36%** |

其中 BRAM 由 28 个 RAMB36 和 7 个 RAMB18（折算 3.5 个 tile）组成。

### 与 stage7 历史基线对比

| 资源 | stage7 | stage13 | 变化 |
|---|---:|---:|---:|
| LUT | 16,337（30.71%） | 15,862（29.82%） | -475 / -0.89 个百分点 |
| FF | 19,180（18.03%） | 20,736（19.49%） | +1,556 / +1.46 个百分点 |
| BRAM Tile | 31.5（22.50%） | 31.5（22.50%） | 不变 |
| DSP | 44（20.00%） | 58（26.36%） | +14 / +6.36 个百分点 |

这组数据应作为最终资源表使用；stage7 只作为优化前历史基线。

## 4. DRC 与 methodology

### 4.1 DRC

`drc_final.rpt` 共发现 203 项：

- Error：0
- Critical Warning：0
- Warning：195
- Advisory：8

Warning 主要来自 DSP 输入/输出流水建议、LUT 配对布局建议，以及
`vid_pclk` 经过非 CCIO 引脚进入 BUFG 的板级时钟放置提示。它们没有被写成
时序违例，但也不能当成“零告警”。

### 4.2 Methodology

`methodology_final.rpt` 共 171 项检查，存在 4 类 Critical Warning：

| 规则 | 数量 | 位置/原因 |
|---|---:|---|
| TIMING-4 | 1 | `clk_wiz_0/clk_in1` 在已有主时钟下游重复定义 |
| TIMING-17 | 152 | `v_vid_in_axi4s_0` 的寄存器没有顶层 `vid_pclk` 时钟到达 |
| TIMING-27 | 1 | `clk_wiz_0/clk_in1` 在层次化内部 pin 上定义主时钟 |
| TIMING-36 | 1 | `rgb2dvi_0/U0/SerialClk` 生成时钟缺少边沿传播 |

因此不能写成“所有 Critical Warning 都来自 rgb2dvi”。准确表述是：

> 用户已约束的 100 MHz 与视频输出路径完成 setup/hold/pulse-width 检查，
> WNS +0.120 ns、WHS +0.016 ns、失败端点 0。仍有摄像头输入时钟
> `vid_pclk` 未在顶层建立 `create_clock` 的覆盖缺口，并且存在 clk_wiz
> 重复主时钟定义和 rgb2dvi/TMDS 生成时钟提示。板级功能、1 小时 soak
> 和分屏 RMS 0.09 已验证，但本次报告不等于“全设计零 Critical Warning”。

## 5. 报告可直接使用的口径

> 最终 stage13 在 XC7Z020、Vivado 2024.2 上完成实现，用户已指定约束内的
> setup/hold/pulse-width 检查全部通过：WNS +0.120 ns、WHS +0.016 ns、
> TNS/THS 失败端点均为 0。资源占用为 LUT 29.82%、FF 19.49%、
> BRAM 22.50%、DSP 26.36%。DRC 无 Error 或 Critical Warning；methodology
> 仍报告摄像头输入时钟约束缺口，以及 clk_wiz 主时钟和 rgb2dvi SerialClk 两类 IP 时钟提示，已在报告中如实披露。