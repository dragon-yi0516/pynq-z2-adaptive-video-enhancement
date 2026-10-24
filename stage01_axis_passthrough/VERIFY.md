# 阶段 1 验收清单：把直通 IP 插进视频流

对应方案书：阶段 1「视频通路标准化为 AXI4-Stream，插 pass-through IP」。

## PC 侧（Ubuntu + Vivado 2024.2）

```bash
# 只需一次：让 vivado 命令可用（路径按你机器上的实际安装位置改）
source /tools/Xilinx/Vivado/2024.2/settings64.sh

# 跑阶段 1
bash /home/xu/OV5640_capture_only/ai_video/build_overlay.sh 1
```

这一条命令会自动依次完成：

1. 若 `bitstream/cv_ov5640/cv_ov5640.xpr` 还不存在，先跑 `cv_ov5640.tcl` 生成基础 BD；
2. 打包 `axis_video_proc`（版本 1.0）；
3. 把 `v_demosaic_0 → axi_vdma_0` 的直连改成 `v_demosaic_0 → axis_video_proc_0 → axi_vdma_0`；
4. 综合 + 实现 + 生成 bitstream；
5. 把 `cv_ov5640.bit` / `.hwh` 拷到 `bitstream/` 和 `ai_video/overlay/`。

成功标志：最后打印 `#  阶段 1 全部完成`，且 `ai_video/overlay/cv_ov5640.bit` 是刚刚生成的时间。
完整日志在 `ai_video/logs/stage1_<时间戳>.log`。

分步跑法、`clean` 参数、环境变量覆盖等见 `ai_video/README_RUN.md`。

## 板上（Jupyter）

运行 `01_axil_regs.ipynb`。

## 必须满足（缺一不可）

- [ ] BD 里能看到 `axis_video_proc_0`，且 `v_demosaic_0 → axis_video_proc_0 → axi_vdma_0` 连成一条。
- [ ] `00_baseline_check.ipynb` 里「自定义 IP 是否存在」变成 **True**。
- [ ] HDMI 画面和插 IP 之前**完全一致**（这一步 IP 只直通，画面不许有任何变化）。
- [ ] 没有花屏、没有撕裂、没有颜色错位。
- [ ] `01_axil_regs.ipynb` 里能抓到 1280x720 的帧。

## 为什么这一步“画面不许变”

阶段 1 的唯一变量是“视频流是否经过了一个自定义 IP”。
如果画面变了，说明插 IP 的过程本身引入了问题（位宽、时钟、tuser/tlast 接错），
必须先修好再往下走。否则阶段 3 之后出现的任何异常都无法归因。

## 常见失败与处理

| 现象 | 原因 | 处理 |
|------|------|------|
| 打包脚本报 `s_axis_video` 已存在 | 打包装置自动推断成功，脚本里的 `ensure_*` 会跳过 | 正常，忽略 |
| BD 报 “no associated clock” | 打包时 aclk 没关联到 AXIS | 重跑 `package_ip.tcl`，它会把 `ASSOCIATED_BUSIF` 设好 |
| 画面全黑 | 视频流断了（tready 没接反向、或时钟没连） | 检查 `s_axis_video_tready` 是否回了 demosaic |
| 画面水平错位 | `tlast` 没接 | 检查 `m_axis_video_tlast` 连到 VDMA |
