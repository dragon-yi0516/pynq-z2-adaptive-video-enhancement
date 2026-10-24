# 验证索引

> 原则：每一项验证都要能回答“怎么跑、看到什么算过、证据在哪、是否上板”。

## 1. 验证矩阵

| 验证 | 方法 | 命令 | 通过标准 | 证据 | 环境 |
|---|---|---|---|---|---|
| 寄存器封装 | 假 IP 单测 | `python3 lib/test_regs.py` | ALL TESTS PASSED | 终端输出 | PC |
| HWH/路径 | 解析真实 hwh | `python3 lib/test_hwh.py` | ALL TESTS PASSED | 终端输出 | PC |
| 空间规则 | 合成+实测点单测 | `python3 lib/test_spatial.py` | ALL TESTS PASSED | 终端输出 | PC |
| 训练→量化→导出→回读 | 离线链路 | `python3 tools/offline_check.py --weights /tmp/mlp_weights.h` | ALL OFFLINE CHECKS PASSED | 终端输出 | PC |
| 数据体检 | C1~C8 | `python3 tools/check_features.py data/features.csv --no-fail` | 0 FAIL | 终端输出 | PC/板 |
| 3 折留一 | 按轮次留出 | `python3 tools/eval_rounds.py --no-write` | MLP 1.000 / 亮度 0.942 | `docs/results/eval_rounds.md` | PC/板 |
| hard pair | 同亮度空间对照 | `python3 tools/eval_holdout.py --csv data/hard_pairs.csv` | MLP 0.750，组合 1.000 | `docs/results/hard_pairs.md` | PC |
| 真实场景 | 部署权重 holdout | `python3 tools/eval_holdout.py --csv data/real_scene.csv` | 120/120，组合不引入错误 | `docs/results/real_scene.md` | PC/板 |
| 失败/边界 | probe 观测 | `tools/check_robustness.ipynb` | 过曝拒绝，白墙/遮镜头不乱切 | `docs/results/robustness.md` | 板 |
| 实时闭环 | 12 秒/场景 | `tools/verify_live_scheduler.ipynb` | 0/1/2/1，约 29.7 fps | `docs/results/live_scheduler.md` | 板 |
| 1 小时 soak | 3600 秒连续 | `tools/soak_test.ipynb` | 107,137 帧 / 29.76 fps / 3 次切换 / 无停流 | `docs/results/soak.md` | 板 |
| 同源分屏 | 同帧 RMS | `13_verify_split.ipynb` | RMS <3 | `docs/08_report_evidence.md` | 板 |
| 时序 | Vivado summary | `report_timing_summary` | WNS ≥0，失败端点 0 | `docs/results/timing.md` | Vivado |
| 资源 | Vivado utilization | `tools/export_vivado_reports.tcl` | LUT 29.82% / FF 19.49% / BRAM 22.50% / DSP 26.36% | `stage13_split/reports/stage13/util_final.rpt` | Vivado |
| CSim | HLS 测试向量 | `vitis_hls -f script.tcl` | 124 条 fail=0 | `stage05_mlp_hls/VERIFY.md` | HLS |

## 2. 明确未验证 / 不要外推

- 温度：镜像无 thermal zone，本稿写“未采集”；
- 整机/HDMI 实拍：待补；
- stage13 的 timing/utilization/DRC/methodology 已补齐；power 报告仍未生成；
- methodology 仍有 4 类 Critical Warning，其中 152 项为 `vid_pclk` 无顶层时钟覆盖；
- DRC 的 195 项 Warning 多为 DSP 流水、LUT 配对和板级 `vid_pclk` 非 CCIO 时钟放置提示；
- 色偏、快速切换、跨曝光参数：未附有效最终记录；
- White Balance/Gamma LUT/TNR：未实现；
- 720p60：未实现；
- 任意户外/夜间/HDR：未验证。

## 3. 干净 clone 复现

```bash
bash run_all.sh test
bash run_all.sh eval
```

如果只想跑不需要板子的部分，以上两条即可；板上验证按 `stageXX/VERIFY.md` 和本索引逐项执行。