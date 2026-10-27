# 报告数据底表（唯一数字来源）

> 写报告时只从这里抄数字；不要自己重算/四舍五入到另一个值。
> 每个表后面都写了原始文件。

## 1. 项目元数据

| 项 | 值 |
|---|---|
| 板卡 | PYNQ-Z2 / XC7Z020 |
| 摄像头 | OV5640（Waveshare 或等效） |
| 显示 | HDMI 720p |
| 工具 | Vivado / Vitis HLS 2024.2 |
| 视频 | 1280×720，24-bit RGB，30 Hz |
| 版本 | stage13 rev02，`VERSION=0x0001020D` |
| 帧率 | 29.61 fps（标准测试）/ 29.7 fps（实时 12 秒） |

## 2. 数据与模型

| 项 | 值 |
|---|---|
| 训练数据 | 540 帧，3 轮 × 60 帧/类，每类 180 帧 |
| 三类中心 (f_luma/f_luma2/f_grad) | 暗光 9.7/0.2/17.2；逆光 66.4/44.6/21.4；常规 96.5/68.6/29.9 |
| 模型 | 3-8-3 Q8.8 MLP |
| HLS | II=1，Depth=7，约 70 ns |
| 量化一致率 | 1.0000 |
| 权重指纹 | `d276ac41fa7e64e2` |

## 3. 3 折 leave-one-round-out

| fold | n | MLP macro-F1 | 亮度阈值 macro-F1 |
|---|---|---|---|
| 0 | 180 | 1.000 | 1.000 |
| 1 | 180 | 1.000 | 0.910 |
| 2 | 180 | 1.000 | 0.915 |
| mean |  | **1.000 ± 0.000** | **0.942 ± 0.041** |

来源：`docs/results/eval_rounds.md`、`data/eval_rounds.json`。

## 4. 同亮度 hard pair

| 场景 | n | f_luma | u | MLP-only | MLP+四象限 |
|---|---|---|---|---|---|
| 均匀暗场 | 60 | 9.0 | 0.101 | 0:60 | 0:60 |
| 暗场+亮窗 | 60 | 8.0 | 2.168 | 0:60 | **1:60** |
| 均匀正常光 | 60 | 99.8 | 0.267 | 2:60 | 2:60 |
| 正常+逆光 | 60 | 116.0 | 1.151 | 1:60 | 1:60 |

Pair 0：`|Δf_luma|=1.0`，`|Δu|=2.067`，MLP 0/0，空间 0/1（主证据）。
Pair 1：`|Δf_luma|=16.2`（WARN），`|Δu|=0.885`，MLP 2/1，空间 2/1（辅助）。

逐帧（240 帧）：纯 MLP acc 0.750 / macro-F1 0.778；MLP+四象限 1.000 / 1.000；
空间覆盖 60 次、保持 0 次；逆光 recall 0.500→1.000。

来源：`docs/results/hard_pairs.md`、`data/hard_pairs.csv`。

## 5. 实时闭环（每场景 12 秒）

| scene | 场景 | f_luma | u | MLP raw | 最终 mode | PARAM |
|---|---|---|---|---|---|---|
| 0 | 均匀暗场 | 7.84 | 0.064 | 0 | 0 | 255 |
| 1 | 暗场+亮窗 | 9.78 | 2.432 | 0 | 1 | 166 |
| 2 | 均匀正常光 | 105.62 | 0.263 | 2:570/1:6 | 2 | 190 |
| 3 | 正常+逆光 | 80.29 | 2.239 | 1 | 1 | 242 |

最终模式 0/1/2/1；29.7 fps；无场景内振荡。
来源：`docs/results/live_scheduler.md`、`data/live_scene*.csv`。

## 6. 固定 vs 连续

| 场景 | 固定 mode0（×1.5） | 自适应 | 收益 |
|---|---|---|---|
| 暗光 | 均值 12.7，饱和 0.0% | PARAM=255（×1.99），均值 16.4 | 提亮 +29%，不过曝 |
| 常规 | 均值 163.4，饱和 29.4% | PARAM=128（×1.0），均值 117.4 | 饱和 29.4% → 0.4% |

来源：`docs/results/step5_compare.md`。

## 7. 时序与资源

| 项 | 值 |
|---|---|
| WNS | **+0.120 ns** |
| TNS / setup 失败端点 | 0.000 / 0 |
| WHS / hold 失败端点 | **+0.016 ns** / 0 |
| WPWS / pulse-width 失败端点 | +0.538 ns / 0 |
| LUT | 15,862 / 53,200 = **29.82%** |
| FF | 20,736 / 106,400 = **19.49%** |
| BRAM Tile | 31.5 / 140 = **22.50%** |
| DSP | 58 / 220 = **26.36%** |
| DRC | 0 Error / 0 Critical Warning；195 Warning / 8 Advisory |
| Methodology | 4 类 Critical Warning；其中 152 项为 `vid_pclk` 无顶层时钟覆盖 |

来源：`stage13_split/reports/stage13/timing_final.rpt`、`util_final.rpt`、`drc_final.rpt`、`methodology_final.rpt`、`report_source.txt`。完整说明见 `docs/results/timing.md`。

## 8. 功能正确性

| 验证 | 结果 | 出处 |
|---|---|---|
| HLS CSim | 124 条，`fail=0` | `stage05_mlp_hls/verify.md` |
| Python 定点参考 | 与 HLS 逐条一致 | `tools/offline_check.py` |
| 权重/bit 同步 | 三者指纹一致 | `tools/check_weight_sync.py` |
| 分屏自洽 | 同帧 RMS 0.09（<3） | `docs/08_report_evidence.md` |
| 实时闭环 | 0/1/2/1，无振荡 | `docs/results/live_scheduler.md` |
| 数据体检 | 0 FAIL / 5 WARN | `tools/check_features.py` |

## 9. 写作时最容易写错的点

* 不要把 3-8-3 MLP 写成 CNN/深度学习；
* 不要把 29.7 fps 写成 60 fps；
* 不要把“可重构处理通路”写成 PE 阵列；
* 不要把 pair 1 写成“MLP 同判”；
* 不要把训练集 1.000 写成泛化 1.000（用 3 折留一 1.000）；
* 版本统一写 stage13 rev02 (`0x0001020D`)。

## 10. 真实场景 / 失败场景（2026-10-20）

### 10.1 真实场景 holdout（120 帧）

| 场景 | n | f_luma | u | MLP | MLP+四象限 |
|---|---|---|---|---|---|
| 真实暗场（重采） | 40 | 4.0 | 0.124 | 0 | 0 |
| 真实窗边逆光 | 40 | 50.2 | 2.497 | 1 | 1 |
| 真实室内正常光 | 40 | 107.7 | 0.385 | 2 | 2 |

纯 MLP 120/120 = 1.000；MLP+四象限 120/120 = 1.000。
空间覆盖 0 次、保持 40 次（scene2 u=0.385 落在迟滞带，mode 仍为 2）。

scene0 重采后四象限 `(15,17,16,17)`，u=0.124，MLP/空间都判 0。
早期 scene0 是“暗场+右侧亮区”（u=0.953），已重采，不再使用旧数据。

来源：`docs/results/real_scene.md`、`data/real_scene.csv`。

### 10.2 失败/边界

| case | n | f_luma | u | MLP | confident | 实际 mode |
|---|---|---|---|---|---|---|
| 遮镜头 | 30 | 3.0 | 0.005 | 0 | 30/30 | 0 |
| 均匀白墙 | 30 | 12.0 | 0.271 | 0 | 30/30 | 0 |
| 过曝 | 30 | 213.6 | 0.116 | 1 | **0/30** | 0 |

过曝的 `decision=1` 是空间目标，但门限拒绝，实际 mode 保持 0。
来源：`docs/results/robustness.md`、`data/robust_*.csv`。

### 10.3 1 小时 soak

| 项 | 值 |
|---|---|
| 运行时长 | 3600 s |
| 帧数 | 107,137 |
| 平均 FPS | 总体 29.76 |
| 切换次数 | 3 |
| 最后 60s 帧增量 | 约 **1,785～1,786**（按绝对计数换算） |
| 最终 mode / PARAM | 1 / 138 |
| 空间覆盖/保持（轮询） | 64,412 / 13 |
| 门限拒绝（轮询） | 63,390 |
| 卡死/花屏/Allocate/Traceback | 全程未记录 |
| 温度 | 本次测试镜像没有 thermal zone，结果不包含温度 |

来源：`docs/results/soak.md`、`tools/soak_test.ipynb` 运行输出。
