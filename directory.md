# 目录对照

赛题推荐使用 `src/`、`sim/`、`build/`、`board/`、`data/`、`skill/`、`report/`。本项目为了保持已验证的 PYNQ Notebook、Tcl 构建脚本和相对导入路径不变，保留了按开发阶段组织的目录；本文件给出完整对照和文件用途。除根目录标准文件名 `README.md` 和 `LICENSE` 外，其余目录名和文件名均使用小写字母、数字、下划线或连字符。

## 1. 与赛题推荐目录对照

| 赛题推荐目录 | 本项目位置 | 内容 |
|---|---|---|
| `src/` | `lib/`、`tools/`、`stage*/hdl/`、`stage05_mlp_hls/src/` | PS 侧 Python、RTL、HLS、寄存器表和接口工具 |
| `sim/` | `lib/test_*.py`、`stage05_mlp_hls/src/*_tb.cpp`、`tools/offline_check.py` | 单元测试、HLS CSim、定点参考和误差检查 |
| `build/` | `build_overlay.sh`、`tools/*.tcl`、`bitstream_2024_2/`、`stage13_split/reports/` | Vivado/HLS 构建脚本、基础 BD 和最终实现报告 |
| `board/` | `stage00..stage13/` 的 Notebook、`overlay/`、`weights/` | 上板实验、演示、版本检查、最终 bit/hwh 和权重 |
| `data/` | `data/` | 训练、holdout、hard pair、边界 probe、实时日志和 soak 数据 |
| `skill/` | `skill/` | 四个可复用 PYNQ/Vivado Skill |
| `report/` | `report/`、`docs/` | 设计报告、数据底表、AI 协作记录、技术说明和结果页 |

## 2. 源码：`src` 对照

| 内容 | 实际位置 |
|---|---|
| 最终 RTL 处理 IP | `stage13_split/hdl/axis_video_proc.v` |
| RTL IP 打包与插入 | `stage13_split/tcl/package_ip.tcl`、`stage13_split/tcl/insert_split.tcl` |
| MLP HLS 源码 | `stage05_mlp_hls/src/mlp_engine.cpp`、`mlp_engine.h` |
| 权重头文件 | `stage05_mlp_hls/src/mlp_weights.h`、`weights/mlp_weights.h` |
| HLS 工程脚本 | `stage05_mlp_hls/hls/script.tcl` |
| PS 侧驱动与寄存器封装 | `lib/ai_video_regs.py`、`lib/video_setup.py`、`lib/video_path.py` |
| 场景决策与参数映射 | `lib/adaptive.py`、`lib/features_io.py` |
| 数据采集与评估工具 | `tools/collect_dataset.py`、`tools/eval_rounds.py`、`tools/eval_spatial.py`、`tools/eval_holdout.py` |
| 历史阶段源码 | `stage00_baseline/` 到 `stage12_adaptive/`，按阶段保留迭代过程 |

### 阶段源码说明

| 阶段 | 主要内容 |
|---|---|
| `stage00_baseline` | 基础 overlay、IP 和 HWH 检查 |
| `stage01_axis_passthrough` | AXI4-Stream 直通 IP |
| `stage02_axil_regs` | AXI-Lite 寄存器 |
| `stage03_feature_extract` | 亮度、平方和梯度统计 |
| `stage04_mlp_train` | MLP 训练、量化与导出 |
| `stage05_mlp_hls` | HLS 3-8-3 MLP、CSim 和 C Synthesis |
| `stage06_mlp_integrate` | MLP 接入处理 IP |
| `stage07_reconfig_array` | 三种处理模式与 PARAM |
| `stage08_auto_schedule` | PS 侧自动调度、防抖与门限 |
| `stage09_perf_test` | 帧率、寄存器读延迟与切换延迟 |
| `stage10_release` | 发布包整理脚本 |
| `stage11_demo` | 演示流程与分屏对比 |
| `stage12_adaptive` | 四象限统计与连续 PARAM |
| `stage13_split` | 最终 HDMI 同源分屏、Vivado 报告和最终 overlay |

## 3. 仿真与验证：`sim` 对照

| 内容 | 实际位置 |
|---|---|
| 寄存器封装单测 | `lib/test_regs.py` |
| HWH 解析与 overlay 路径检查 | `lib/test_hwh.py` |
| 四象限空间规则单测 | `lib/test_spatial.py` |
| HLS CSim 测试平台 | `stage05_mlp_hls/src/mlp_engine_tb.cpp` |
| HLS 测试向量 | `stage05_mlp_hls/src/tv_mlp.h` |
| Python 定点参考与量化检查 | `tools/offline_check.py` |
| 权重、HLS 和 bitstream 同步检查 | `tools/check_weight_sync.py` |
| 黄金参考 CSV 比对 | `skill/golden_reference_ci/compare_csv.py` |
| 全量验证索引 | `docs/verification_index.md` |

## 4. 构建与实现报告：`build` 对照

| 内容 | 实际位置 |
|---|---|
| 一键构建入口 | `build_overlay.sh` |
| 阶段流程 | `tools/stage_flow.tcl` |
| 综合、实现与 bit 导出 | `tools/build_and_copy.tcl` |
| BD 插 IP 公共脚本 | `tools/insert_axis_video_proc_common.tcl` |
| IP 打包公共脚本 | `tools/package_ip_common.tcl` |
| 基础 Block Design | `bitstream_2024_2/cv_ov5640.tcl` |
| 板级引脚约束 | `bitstream_2024_2/cv_ov5640.xdc` |
| rgb2dvi/TMDS IP | `bitstream_2024_2/ip_repo/` |
| 最终时序报告 | `stage13_split/reports/stage13/timing_final.rpt` |
| 最终资源报告 | `stage13_split/reports/stage13/util_final.rpt` |
| 最终 DRC | `stage13_split/reports/stage13/drc_final.rpt` |
| 方法学报告 | `stage13_split/reports/stage13/methodology_final.rpt` |
| 报告来源记录 | `stage13_split/reports/stage13/report_source.txt` |
| 历史时序/资源基线 | `stage07_reconfig_array/timing_v3.rpt`、`stage07_reconfig_array/util_v3.rpt` |

## 5. 板端运行：`board` 对照

| 内容 | 实际位置 |
|---|---|
| 最终 overlay | `overlay/cv_ov5640.bit`、`overlay/cv_ov5640.hwh` |
| 部署权重 | `weights/mlp_weights.h` |
| 版本与 IP 检查 | `stage00_baseline/00_baseline_check.ipynb` |
| 手动三模式演示 | `stage07_reconfig_array/06_mode_manual.ipynb` |
| 自动调度 | `stage08_auto_schedule/07_auto_schedule.ipynb` |
| 性能测试 | `stage09_perf_test/08_perf_test.ipynb` |
| 答辩主流程 | `stage11_demo/09_demo.ipynb` |
| 分屏对比 | `stage11_demo/10_split_compare.ipynb`、`stage13_split/13_verify_split.ipynb` |
| 全屏 A/B 录制 | `tools/ab_toggle.ipynb` |
| 实时调度验证 | `tools/verify_live_scheduler.ipynb` |
| 1 小时运行 | `tools/soak_test.ipynb` |
| 演示前检查 | `stage11_demo/demo_checklist.md` |

## 6. 数据：`data`

| 文件 | 内容 |
|---|---|
| `features.csv` | 540 帧三类训练特征 |
| `features_demo.csv` | 小规模演示数据 |
| `mlp_float.npz` | 浮点训练模型 |
| `eval_rounds.json` | 3 折 leave-one-round-out 指标 |
| `eval_spatial.json` | 四象限空间规则评估 |
| `hard_pairs.csv`、`hard_pairs_scene*.csv` | 同亮度、不同空间布局数据 |
| `real_scene.csv`、`real_scene_scene*.csv` | 真实场景 holdout |
| `robust_lens_covered.csv` | 遮镜头边界数据 |
| `robust_uniform_wall.csv` | 均匀白墙边界数据 |
| `robust_overexposed.csv` | 过曝边界数据 |
| `live_scene*.csv` | 四场景实时调度记录 |
| `soak.csv` | 1 小时运行心跳 |
| `soak.log` | 1 小时运行最终日志 |

## 7. 技能包：`skill`

| 目录 | 用途 |
|---|---|
| `skill/pynq_overlay_preflight/` | overlay、IP、VERSION 和 VDMA 上板前检查 |
| `skill/axil_register_contract/` | 寄存器表、Python 封装和 HDL 地址一致性检查 |
| `skill/golden_reference_ci/` | Python 参考结果与 HLS/板端输出逐条比对 |
| `skill/vivado_report_gate/` | WNS/TNS、资源报告解析与阈值门禁 |

## 8. 文档与报告

| 内容 | 实际位置 |
|---|---|
| 项目总览 | `README.md` |
| 完整目录对照 | `directory.md` |
| 设计报告正文 | `report/design_report.md` |
| 数据底表 | `report/report_data_sheet.md` |
| AI 协作完整记录 | `report/ai_collaboration_record.md` |
| 较早的协作摘要 | `report/llm_collaboration.md` |
| 模型卡 | `report/model_card.md` |
| 相关工作总结 | `report/related_work.md` |
| 技术说明 | `docs/01_register_map.md` 到 `docs/09_spatial_decision.md` |
| 验证索引 | `docs/verification_index.md` |
| 各实验结果 | `docs/results/` |
| 2024.2 迁移记录 | `docs/migration_2024_2.md` |
| 构建与运行说明 | `docs/run_guide.md` |
| 开发交接 | `docs/handoff.md` |
| 拍照与视频指南 | `docs/demo_capture_guide.md` |

## 9. 根目录文件

| 文件 | 用途 |
|---|---|
| `README.md` | 项目简介、结果、硬件和复现入口 |
| `directory.md` | 本文件，完整目录与赛题结构对照 |
| `LICENSE` | BSD-3-Clause 许可证 |
| `third_party_notices.md` | 上游项目和第三方 IP 说明 |
| `requirements.txt` | PC/Ubuntu 侧 Python 依赖 |
| `build_overlay.sh` | Vivado 2024.2 一键构建入口 |
| `run_all.sh` | 离线测试与评估入口 |
| `.gitattributes` | 文本换行和二进制文件类型 |
| `.gitignore` | 构建缓存和本地临时文件规则 |

## 10. 推荐阅读顺序

1. `README.md`：先看项目做了什么和结果；
2. `directory.md`：找到赛题目录对应的实际位置；
3. `docs/verification_index.md`：逐项查看验证命令、判据和证据；
4. `report/design_report.md`：阅读完整设计报告；
5. `docs/results/`：查看每项实测数据；
6. `skill/readme.md`：查看可复用工具。