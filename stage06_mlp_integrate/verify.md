# 阶段 6 验收清单：MLP IP 集成

对应方案书：阶段 6「MLP IP 集成，Jupyter 读推理结果」。

## PC 侧（Ubuntu + Vivado 2024.2，分两步）

**第一步：先跑 HLS，导出 `mlp_engine` IP**（这一步必须做，否则阶段 6 插不进去）

```bash
source /tools/Xilinx/Vitis_HLS/2024.2/settings64.sh     # 或 Vivado 2024.2 自带的 vivado_hls
cd /home/xu/OV5640_capture_only/ai_video/stage05_mlp_hls/hls
vivado_hls -f script.tcl
```

必须看到 `CSIM PASSED: HLS 与 Python 定点参考完全一致`。
导出产物会在 `stage05_mlp_hls/mlp_engine_prj/solution1/impl/ip/`。

> `script.tcl` 里的测试向量 `src/tv_mlp.h` 和权重 `src/mlp_weights.h`
> 已经由 notebook `05_mlp_verify.ipynb`（阶段 5）自动生成好了，
> 如果你重新训练过模型，要先重跑那个 notebook 再跑 HLS。

**第二步：一条命令出 bitstream**

```bash
source /tools/Xilinx/Vivado/2024.2/settings64.sh
bash /home/xu/OV5640_capture_only/ai_video/build_overlay.sh 6
```

它会打包 `axis_video_proc` 版本 1.3、插入 `axis_video_proc_0` **和** `mlp_engine_0`
（外加一个复位反相器，因为 HLS 的 `ap_rst` 是高有效），连好 8 根握手线，
然后综合/实现/出 bitstream。

成功标志：最后打印 `#  阶段 6 全部完成`。

## 板上（Jupyter）

运行 `05_mlp_verify.ipynb`。

## 必须满足（缺一不可）

- `VERSION` 读回 `0x00010206`（`0x0001`=家族，`02`=修订，`06`=阶段）。
      注意修订号：`0x0001_0006` 是握手有问题的第一版，**必须是 `0x00010206`**。
- `MLP_OUTPUT` 能读出 0/1/2；改变场景（遮镜头 / 逆光 / 移动）时**会变化**。
- `STATUS.bit0`（推理完成）在读到新结果后为 1，读一次后自动清零。
- `MLP_START_CNT`(0x2C) 和 `MLP_DONE_CNT`(0x30) **都在持续递增**
      （30 秒里大约各涨 1800 次，帧率 60 时）。
- HDMI 画面和阶段 3/7 相比没有异常（直通不受影响、不花屏、不撕裂）。
- `FRAME_CNT` 仍以约 60/秒 递增（说明插 IP 没把帧率拖垮）。

## 为什么推理有 1 帧延迟

统计量必须等一帧**结束**才算完。所以流程是：

```
帧 N 结束(tuser) -> 锁存帧 N 的统计 -> 触发 MLP -> 结果属于"帧 N"
帧 N+1 期间      -> MLP_OUTPUT 里是帧 N 的结论
```

对演示没有影响（人眼看不出 16ms），但**做数据分析时要注意**：
`MLP_OUTPUT` 对应的是上一帧，不是当前正在显示的那一帧。

## 常见失败与处理

| 现象 | 原因 | 处理 |
|------|------|------|
| `MLP_OUTPUT` 恒为 0，且 `MLP_START_CNT` 不动 | 启动请求没发出去 | 先看 `FRAME_CNT` 是否在涨（视频流在不在），再查 `mlp_start` 连线 |
| `MLP_OUTPUT` 恒为 0，`START` 在涨但 `DONE` 不动 | 启动了但没完成 | 查 `mlp_engine_0` 的 `ap_clk` / `ap_rst`（**`ap_rst` 是高有效，必须经反相器**），以及 `ap_done` 是否连到 `mlp_done` |
| 两个计数器都在涨，但 `MLP_OUTPUT` 不变 | 结果线接错 | 查 `ap_return` → `mlp_result` 那一根 |
| `insert_mlp.tcl` 报 “缺少端口” | HLS 导出的端口名和预期不同 | 脚本会自动列出该 cell 的真实端口，按实际名字改脚本里的 `need_pin` |
| `MLP_OUTPUT` 恒为同一个值 | 特征没更新 | 确认 `FRAME_CNT` 在涨、`STATUS.bit1` 有出现过 |
| 画面出现上下抖动 | v_axi4s_vid_out 时序被 IP 延迟影响 | 本设计像素通路是组合直通（阶段 6 还没改像素），出现抖动说明是 VDMA 侧问题 |
