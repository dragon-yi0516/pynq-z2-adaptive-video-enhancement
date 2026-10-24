# 结果证据索引

这份目录只放“报告里能直接引用的数字”，每个数字都要能追到命令或原始日志。

| 文件 | 内容 | 生成方式 |
|---|---|---|
| `eval_rounds.md` | 按采集轮次留出的 MLP vs 亮度阈值 | `python3 tools/eval_rounds.py` |
| `hard_pairs.md` | 同亮度、不同空间布局的 hard pair 实测（2026-10-19） | `python3 tools/collect_hard_pairs.py` + `python3 tools/eval_spatial.py` |
| `live_scheduler.md` | 四场景 12 秒实时闭环稳定性（2026-10-19） | `tools/verify_live_scheduler.ipynb` |
| `real_scene.md` | 真实房间 holdout | `tools/collect_real_scene.ipynb` + `tools/eval_holdout.py` |
| `robustness.md` | 失败/边界场景 | `tools/check_robustness.ipynb` |
| `soak.md` | 1 小时连续运行 | `tools/soak_test.ipynb` 或 `auto_schedule.py --duration 3600` |
| `timing.md` | WNS / TNS / 资源占用 | Vivado `report_timing_summary` / `report_utilization` |
| `perf.md` | FPS / AXI 读延迟 / 切换延迟 | `stage09_perf_test/08_perf_test.ipynb` |
| `step5_compare.md` | 固定强度 vs 连续自适应 | `tools/step5_compare.py` |

原则：

1. 报告里的每个数字都能在这里找到出处；
2. 同一张表只在同一次运行、同一档曝光下成对比较；
3. 结果页只写已经跑过的数据，新实验按相同格式追加。
