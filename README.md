# PYNQ-Z2 上的 OV5640 自适应视频增强

这是我在 PYNQ-Z2（XC7Z020）上完成的一个 FPGA 视频处理项目。
OV5640 采集到的画面会经过去马赛克和自建的 AXI4-Stream 处理 IP，再由
VDMA 送入 DDR，最后通过 HDMI 显示。PL 负责逐像素统计和图像处理，PS 负责
判断场景并调整参数。

## 我为什么做这个

摄像头自带的 AEC/AGC 主要按整幅画面调亮度。在窗边逆光这种场景里，
如果把主体提亮，窗户就更容易过曝；如果压暗高光，主体又会太黑。
所以我想试试：能不能让 FPGA 先看画面特征，再根据场景选择处理方式，
而不是一直使用同一组固定参数。

最后的做法是：

* PL 每个像素统计亮度、亮度平方和梯度，同时统计四个象限的亮度；
* PS 用一个 3-8-3 的 Q8.8 定点 MLP 判断暗光、逆光或常规场景；
* 四象限数据用来补充“亮区是不是集中在局部”这个信息；
* 再根据模式和连续 PARAM 调整增益、逆光补偿或锐化，参数在帧边界更新。

![PYNQ-Z2 系统连接示意图](report/assets/system_diagram.png)

## 当前完成情况

| 项目 | 实测结果 |
|---|---|
| 板卡和器件 | PYNQ-Z2 / XC7Z020 |
| 视频 | 1280×720，24-bit RGB，29.61 fps；1 小时运行平均 29.76 fps |
| 时序 | WNS +0.120 ns，WHS +0.016 ns，setup/hold 失败端点均为 0 |
| 资源 | LUT 29.82% / FF 19.49% / BRAM 22.50% / DSP 26.36% |
| 3 折留一 | MLP macro-F1 1.000；固定亮度阈值 0.942 |
| 固定参数 vs 连续参数 | 常规场景饱和率 29.4% → 0.4% |
| 同亮度 hard pair | MLP 都判 0；加入四象限后，亮窗场景改判为 mode 1 |
| hard pair 逐帧 | MLP 准确率 0.750；加入四象限后 1.000 |
| 真实场景 | 3 个场景共 120 帧，MLP 和空间规则均为 1.000 |
| 1 小时运行 | 107,137 帧，29.76 fps，3 次模式切换，没有记录到停流 |
| 分屏对比 | 同一帧的左右图 RMS 为 0.09 |

这些数字都按来源记录在 `docs/results/` 和 `report/report_data_sheet.md`，
没有把 stage7 的旧资源数据当成 stage13 的结果。

## 硬件结构

```text
OV5640
  -> v_vid_in_axi4s
  -> v_demosaic
  -> axis_video_proc（统计 + 四象限 + 三模式 + PARAM + 分屏）
  -> axi_vdma_0 (S2MM) -> DDR
  -> axi_vdma_0 (MM2S) -> axi_vdma_1 (S2MM) -> DDR
  -> axi_vdma_1 (MM2S) -> v_axi4s_vid_out
  -> rgb2dvi -> HDMI
```

`axis_video_proc` 插在 `v_demosaic_0/m_axis_video` 和
`axi_vdma_0/S_AXIS_S2MM` 之间。这一段是完整的 24-bit RGB 像素流，
所以处理后的画面既能被 Jupyter 抓取，也能直接送到 HDMI。

## 实现报告

stage13 的原始 Vivado 报告放在 `stage13_split/reports/stage13/`：

| 文件 | 内容 |
|---|---|
| `timing_final.rpt` | setup、hold、pulse-width 和关键路径 |
| `util_final.rpt` | LUT、FF、BRAM、DSP 占用 |
| `drc_final.rpt` | 布线后的 DRC |
| `methodology_final.rpt` | 时钟和约束方法学检查 |
| `report_source.txt` | 工程路径、工具版本、实现状态和生成时间 |

## 目录对照

比赛推荐 `src/`、`sim/`、`build/`、`board/`、`data/`、`skill/`、`report/`。本项目按开发阶段组织，对应关系如下：

| 推荐目录 | 本项目位置 |
|---|---|
| `src/` | `stage01..stage13/` 的 `hdl/`、`hls/`、`src/`，以及 `lib/` |
| `sim/` | `stage05_mlp_hls/src/*_tb.cpp`、`tools/offline_check.py`、`lib/test_*.py` |
| `build/` | `build_overlay.sh`、`tools/*.tcl`、`bitstream_2024_2/` |
| `board/` | `stage08..stage13/` 的 Notebook、`overlay/`、`weights/` |
| `data/` | `data/` 下的训练、holdout、边界、实时和 soak 数据 |
| `skill/` | 四个可复用 Skill |
| `report/` | `report/` 和 `docs/` |

## 快速复现

### 1. PC 或 Ubuntu 离线检查

```bash
git clone https://github.com/dragon-yi0516/pynq-z2-adaptive-video-enhancement.git
cd pynq-z2-adaptive-video-enhancement
bash run_all.sh test
```

也可以分开运行：

```bash
python3 lib/test_regs.py
python3 lib/test_hwh.py
python3 lib/test_spatial.py
python3 tools/offline_check.py --weights /tmp/mlp_weights.h
```

### 2. Ubuntu + Vivado 2024.2 重建 overlay

```bash
source /tools/Xilinx/Vivado/2024.2/settings64.sh
bash build_overlay.sh 13
```

重新生成的文件会放到 `overlay/cv_ov5640.bit` 和
`overlay/cv_ov5640.hwh`。迁移和踩坑记录在 `README_2024.2.md`。

### 3. 板子上运行

把仓库拷到 PYNQ 板卡，例如：

```text
/home/xilinx/jupyter_notebooks/ai_video_competition/
```

建议按下面的顺序打开 Notebook：

```text
stage00_baseline/00_baseline_check.ipynb
stage07_reconfig_array/06_mode_manual.ipynb
stage08_auto_schedule/07_auto_schedule.ipynb
stage09_perf_test/08_perf_test.ipynb
stage11_demo/09_demo.ipynb
tools/verify_live_scheduler.ipynb
tools/soak_test.ipynb
```

运行前先确认 overlay 版本：

```text
VERSION = 0x0001020D
```

## 数据和模型

训练数据放在 `data/`，包括：

* 540 帧三类标定数据；
* 240 帧同亮度 hard pair；
* 3 个真实场景的 120 帧 holdout；
* 遮镜头、白墙和过曝边界数据；
* 四场景实时日志和 1 小时 soak 数据。

部署权重在 `weights/mlp_weights.h`，HLS 源码里的副本也使用同一份权重。
需要重新训练或导出时可以从 `stage04_mlp_train/` 和
`stage05_mlp_hls/` 开始。

## Skill 目录

`skill/` 里整理了四个可以在别的 PYNQ 项目里复用的工具：

* `pynq_overlay_preflight`：上板前检查 overlay、IP、VERSION 和 VDMA；
* `axil_register_contract`：检查寄存器表、Python 封装和 HDL 地址是否一致；
* `golden_reference_ci`：逐条比较 Python 参考结果和 HLS/板上输出；
* `vivado_report_gate`：读取 Vivado 时序和资源报告，按阈值给出 PASS/FAIL。

每个目录的 README 都写了适用场景、用法、失效条件和验证记录。大模型协作过程见 `report/AI_COLLABORATION_RECORD.md`。

## 已知问题

* 目前只区分暗光、逆光和常规三类，不是通用场景理解；
* 训练数据是 540 帧标定数据，真实房间的数据量还不够；
* 四象限只能看出大范围明暗不均，定位不到很小的局部高光；
* 当前是 720p30，不是 720p60；
* 用户已指定约束内 setup/hold/pulse-width 都通过，但顶层 `vid_pclk`
  还没有完整的输入时钟和 I/O 延时约束，具体边界写在
  `docs/results/timing.md`；
* `hard_pairs.csv` 和空间阈值换环境后需要重新标定。

## License

本项目新增部分使用 BSD-3-Clause。基础 BD、`rgb2dvi` 和 OV5640 配置表来自
[Pynq-CV-OV5640](https://github.com/xupsh/Pynq-CV-OV5640)。
第三方说明见 `THIRD_PARTY_NOTICES.md`。