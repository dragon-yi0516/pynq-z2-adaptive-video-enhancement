# 性能

## 板上实测

| 项 | 实测 | 说明 / 出处 |
|---|---|---|
| 帧率 | **29.61 fps** | 89 帧 / 3.01 s，720p30 标称的 98.7% |
| 单次 AXI-Lite 读 | **24.09 µs** | PS 读一次 IP 寄存器的往返 |
| 模式切换延迟 | **≤ 1 帧 = 33.8 ms** | 切换落在帧边界（`tuser` 重采样）→ 不撕裂 |
| MLP 推理 | **II=1 / Depth=7 @100 MHz** | 约 70 ns，远小于 1 ms |
| 视频格式 | 1280×720，24-bit RGB | 与 `v_demosaic`/`v_axi4s_vid_out` 一致 |

出处：`stage09_perf_test/08_perf_test.ipynb`、`docs/08_report_evidence.md`。

## 端到端延迟口径

没有高速相机时，按保守上界写：

```
采集/统计：1 帧
推理：      < 1 µs
切换：      ≤ 1 帧
显示：      1 帧
合计：      约 3 帧 ≈ 100 ms @30 fps
```

如果比赛要求更小的数字，需要用外部仪器（高速相机/光电二极管）实测，
不要用 Python `time.time()` 反推。

## 与基线的对比

* 固定 3 模式（stage 7）vs 连续自适应（stage 12/13）：见 `step5_compare.md`；
* 3 特征 MLP vs 固定亮度阈值：见 `eval_rounds.md`；
* PL 逐像素统计 vs PS NumPy：建议在答辩前补一组“PS 每帧耗时”的实测，
  这是“为什么用 FPGA”的直接证据。
