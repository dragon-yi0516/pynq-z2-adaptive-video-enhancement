# 在 Ubuntu 虚拟机里怎么跑（一条命令一个阶段）

## 你的目录长这样

```
OV5640_capture_only/                 <-- 这就是 /home/xu/OV5640_capture_only
├── ai_video/                        <-- 本工程（我改好的这套）
│   ├── build_overlay.sh             <-- 一键入口：bash build_overlay.sh 1
│   ├── tools/
│   │   ├── stage_flow.tcl           建基础BD -> 打包IP -> 插BD -> 出bitstream
│   │   ├── build_and_copy.tcl       综合/实现/拷产物（被 stage_flow 调用）
│   │   ├── package_ip_common.tcl    各阶段共用的 IP 打包逻辑
│   │   └── insert_axis_video_proc_common.tcl  找 bitstream 目录 + 插 IP
│   ├── stage01_axis_passthrough/    hdl/ + tcl/ + notebook
│   ├── stage02_axil_regs/
│   ├── stage03_feature_extract/
│   ├── stage05_mlp_hls/             Vitis HLS 工程（阶段 5/6/7 用）
│   ├── stage06_mlp_integrate/
│   ├── stage07_reconfig_array/
│   ├── lib/                         notebook 用的 Python 库
│   ├── overlay/                     自动写入 cv_ov5640.bit / .hwh
│   └── logs/                        每次跑 Vivado 的日志
└── bitstream/                       <-- 原工程（cv_ov5640.tcl 在这里）
    ├── cv_ov5640.tcl / .xdc / build_bitstream.tcl
    ├── cv_ov5640/                   Vivado 工程
    └── cv_ov5640.bit / .hwh         每次重建都会被覆盖成最新版
```

**你不需要挪任何文件，也不需要 cd 到某个目录。** 所有脚本都按“自己所在的位置”去推算路径。

## 一次性准备

```bash
# 让 vivado 命令可用（路径按你机器上的实际安装改）
source /tools/Xilinx/Vivado/2024.2/settings64.sh

# 确认脚本有换行/LF 且可执行（一般不用管，保险起见）
cd /home/xu/OV5640_capture_only/ai_video
chmod +x build_overlay.sh
```

## 每个阶段一条命令

```bash
cd /home/xu/OV5640_capture_only/ai_video

bash build_overlay.sh 1      # 阶段1：纯直通 IP
bash build_overlay.sh 2      # 阶段2：AXI-Lite 寄存器（在阶段1 工程上继续）
bash build_overlay.sh 3      # 阶段3：特征提取
bash build_overlay.sh 6      # 阶段6：MLP 集成（必须先跑完阶段5 的 HLS）
bash build_overlay.sh 7      # 阶段7：可重构阵列
```

每条命令内部按顺序做四件事：

1. **基础 BD**：如果 `bitstream/cv_ov5640/cv_ov5640.xpr` 不存在（或你加了 `clean`），
   先跑 `cv_ov5640.tcl` 生成；
2. **打包 IP**：把该阶段的 `axis_video_proc.v` 打包成 Vivado IP；
3. **插进 BD**：新建 `axis_video_proc_0`，把 `v_demosaic_0 → axi_vdma_0` 的直连
   改成 `v_demosaic_0 → axis_video_proc_0 → axi_vdma_0`（阶段 2 起再挂 AXI-Lite；
   阶段 6/7 还额外插入 HLS 的 `mlp_engine_0`）；
4. **出 bitstream**：重新综合 + 实现 + 生成，然后把 `cv_ov5640.bit/.hwh`
   **同时**拷到 `bitstream/` 和 `ai_video/overlay/`。

跑完最后一行会打印：

```
############################################################
#  阶段 1 全部完成
#  .../bitstream/cv_ov5640.bit  /  .hwh
#  .../ai_video/overlay/cv_ov5640.bit  /  .hwh
############################################################
```

## 阶段 5（HLS）怎么跑

阶段 6/7 需要一个 HLS 导出的 `mlp_engine` IP，所以中间要跑一次 HLS：

```bash
source /tools/Xilinx/Vitis_HLS/2024.2/settings64.sh    # 或者直接用 Vivado 自带的 vivado_hls
cd /home/xu/OV5640_capture_only/ai_video/stage05_mlp_hls/hls
vivado_hls -f script.tcl
```

必须看到 `CSIM PASSED` 才能继续。产物在
`stage05_mlp_hls/mlp_engine_prj/solution1/impl/ip/`，`build_overlay.sh 6` 会自动找到它。

## 产物怎么拿到主机

每次跑完，最新的两个文件就是：

```
OV5640_capture_only/ai_video/overlay/cv_ov5640.bit
OV5640_capture_only/ai_video/overlay/cv_ov5640.hwh
```

把这两个（以及整个 `ai_video/` 目录）拷到主机 → 再放到板子上即可。
**notebook 不用改任何路径**：它们会从当前目录往上找 `lib/video_setup.py`，
并且在 `overlay/`、`bitstream/`、`ai_video/overlay/` 里自动找 `cv_ov5640.bit`。

## 想分步跑（调试用）

```bash
# 1) 只生成基础 BD（可选；想从干净状态重来时用）
cd /home/xu/OV5640_capture_only/bitstream
vivado -mode batch -source cv_ov5640.tcl -notrace

# 2) 只打包 IP
vivado -mode batch -notrace \
  -source /home/xu/OV5640_capture_only/ai_video/stage01_axis_passthrough/tcl/package_ip.tcl

# 3) 只插 IP
vivado -mode batch -notrace \
  -source /home/xu/OV5640_capture_only/ai_video/stage01_axis_passthrough/tcl/insert_axis_video_proc.tcl

# 4) 只出 bitstream 并拷产物
vivado -mode batch -notrace \
  -source /home/xu/OV5640_capture_only/ai_video/tools/build_and_copy.tcl
```

这四步都不需要 `cd`（第 1 步除外，因为它里面用的是相对路径）。

## 出错时看什么

| 现象 | 看哪里 / 怎么处理 |
|------|------------------|
| `找不到 vivado 命令` | 先 `source .../settings64.sh` |
| `在 ... 里找不到 cv_ov5640.tcl` | 你的 `bitstream/` 不在 `ai_video/` 的隔壁。设环境变量：`export AI_VIDEO_BITSTREAM_DIR=/path/to/bitstream` |
| `找不到 HLS 导出的 IP` | 阶段 6/7 前先跑 `stage05_mlp_hls/hls/script.tcl` |
| `insert_*.tcl` 报缺少端口 | 脚本会把该 IP 的真实端口全列出来，按实际名字改一行即可 |
| 实现没跑完 | `bitstream/cv_ov5640/cv_ov5640.runs/impl_1/runme.log` |
| 想推翻重来 | `bash build_overlay.sh 1 clean`（会重新生成基础 BD 再插 IP） |

所有 Vivado 输出也有留档：`ai_video/logs/stage<N>_<时间戳>.log`。
