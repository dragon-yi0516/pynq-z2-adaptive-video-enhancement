# 阶段依赖与执行顺序

## 依赖图

```
阶段0 基线
  └─ 阶段1 纯直通IP ── 阶段2 AXI-Lite ── 阶段3 特征提取 ── 阶段4 MLP训练/量化
                                                              │
                                                              └─ 阶段5 HLS引擎 ── 阶段6 MLP集成
                                                                                     │
                                              阶段7 可重构阵列 ───────────────────────┘
                                                              │
                                                              └─ 阶段8 自动调度 ── 阶段9 性能测试
                                                                                     │
                                                       阶段10 整理开源 ── 阶段11 答辩演示
```

* 阶段 1~3、6、7 每完成一个都要**重新生成 bitstream**，把新 `.bit/.hwh` 覆盖到
  `overlay/`。
* 阶段 4、5、8、9、10、11 **不需要**重新生成硬件（阶段 5 例外：它要综合 HLS IP，
  但那次综合的产物是给阶段 6 用的）。
* 每个阶段目录里的 `VERIFY.md` 是硬性验收条件，不通过不要进入下一阶段。

## 每个阶段的“硬件动作 / 软件动作”对照

| 阶段 | PC(Vivado/HLS) | PYNQ(Jupyter) | 需要重新出 bit？ |
|------|----------------|---------------|------------------|
| 0 | 无 | `00_baseline_check.ipynb` | 否 |
| 1 | 加直通 IP、出 bit | `01_axil_regs.ipynb` | **是** |
| 2 | IP 加 AXI-Lite、出 bit | `01_axil_regs.ipynb` | **是** |
| 3 | 加 `feature_extract`、出 bit | `02_feature_collect.ipynb` | **是** |
| 4 | 无 | `03_mlp_train.ipynb`、`04_mlp_quant_export.ipynb` | 否 |
| 5 | HLS 综合 `mlp_engine` | `05_mlp_verify.ipynb`（生成测试向量） | 否（但要合成 IP） |
| 6 | 例化 MLP IP、出 bit | `05_mlp_verify.ipynb` | **是** |
| 7 | 加 `reconfig_processor`、出 bit | `06_mode_manual.ipynb` | **是** |
| 8 | 无 | `07_auto_schedule.ipynb` / `auto_schedule.py` | 否 |
| 9 | 看 Utilization 报告 | `08_perf_test.ipynb` | 否 |
| 10 | 无 | 导出脚本 | 否 |
| 11 | 无 | 演示 notebook | 否 |

## 建议的工作节奏

1. **一次只改一个阶段**，改完立刻用该阶段的 `VERIFY.md` 验收并备份 `.bit/.hwh`。
2. 备份命名建议：`overlay/backup/cv_ov5640_stage03_YYYYMMDD.bit`。
   （一旦某个阶段出问题，可以立刻回退到上一版 overlay，不用重新综合。）
3. 每次换 overlay 前，先在 Jupyter 里把 VDMA/overlay 释放：

   ```python
   for ch in (vdma0.writechannel, vdma0.readchannel, vdma1.writechannel, vdma1.readchannel):
       try:
           if ch.running: ch.stop()
       except Exception: pass
   ```

   然后 `Restart Kernel`，再重新加载 overlay。原因见 `docs/02_why_this_design.md` 第 7 节。

## 时间不够时的最小可交付路径

如果比赛前时间紧，优先做：阶段 0 → 1 → 2 → 3 → 4 → 6 → 7 → 8 → 11，
即“直通 + 寄存器 + 特征 + 训练 + 集成 + 可重构 + 自动调度 + 演示”。
阶段 5 可以先跳过（用阶段 4 在 Jupyter 里跑定点推理代替），
阶段 9/10 属于加分项。
