# ai_video —— Vivado / Vitis HLS 2024.2 升级版

这是你比赛工程 **`ai_video`（OV5640 自适应图像增强，stage00~stage11）** 从
Vivado **2018.3** 迁到 **2024.2** 的完整可运行副本。

原始工程一个字节都没动，这份是新目录 `ai_video_2024.2/`。

工具路径（和你给的一致）：

```
/tools/Xilinx/Vivado/2024.2/settings64.sh
/tools/Xilinx/Vitis_HLS/2024.2/settings64.sh
```

---

## 0. 和上一版的关系（重要）

`ai_video` 不是独立工程，它的 `tools/stage_flow.tcl` 第一步是：

```tcl
set base_tcl [file join $bs_dir "${overlay_name}.tcl"]   ;# bitstream/cv_ov5640.tcl
source $base_tcl                                          ;# 建基础 Block Design
```

也就是说**每个阶段都要先跑一遍 `bitstream/cv_ov5640.tcl` 建底板**。
那个底板脚本（2018.3 生成的 BD 脚本）也在这次升级范围里，已经放在
`bitstream_2024_2/` 里，并且是**已经在 2024.2 上实跑过、修过 bug 的版本**。

---

## 1. 目录结构

```
ai_video_2024.2/
├── README_2024.2.md          ← 你正在看的这份
├── README.md                 ← 原工程总览（版本号已更新）
├── README_RUN.md             ← 原工程跑法（命令已更新）
├── build_overlay.sh          ← ★ 已升级：自动 source 2024.2 环境
├── tools/                    ← ★ 已升级：建基础BD/打包IP/插BD/出bitstream
├── stage00_baseline/ ~ stage11_demo/
├── stage05_mlp_hls/hls/script.tcl   ← ★ 已升级：Vitis HLS 2024.2
├── release/                  ← 打包发布副本（hw/ 里的脚本已同步升级）
├── lib/  data/  weights/  docs/     ← 板子侧用的，不用改
├── overlay/                  ← 放 cv_ov5640.bit/.hwh
└── bitstream_2024_2/         ← ★ 新增：2024.2 版基础 BD 脚本 + rgb2dvi IP 仓库
    ├── cv_ov5640.tcl
    ├── cv_ov5640.xdc
    ├── build_bitstream.tcl
    ├── check_cv_ov5640.tcl
    └── ip_repo/              ← rgb2dvi_v1_2 + if/tmds_v1_0
```

---

## 2. 这次到底改了什么

| # | 位置 | 2018.3 原状 | 2024.2 处理 |
| --- | --- | --- | --- |
| 1 | `build_overlay.sh` | 写死 `/tools/Xilinx/Vivado/2018.3/settings64.sh`，找不到就退出 | 改成 2024.2；**找不到 vivado 时会自动 source**，也支持 `export VIVADO_SETTINGS=...` 覆盖 |
| 2 | `bitstream_2024_2/cv_ov5640.tcl` | 2018.3 生成的 BD 脚本，版本检查写死 2018.3 | 版本检查改 2024.2；IP 版本改成运行时解析最新版（`axi_iic` 已经是 2.1）；IP 仓库路径改成自动搜索 |
| 2b | 同上 | IP 存在性检查用无版本 VLNV，**在 2024.2 会误报"所有 IP 都缺失"** | 改用 `xilinx.com:ip:xxx:*` 通配符（这个坑我们已经在 2024.2 上实测踩过并修好） |
| 3 | `tools/stage_flow.tcl` | 工程存在就直接用 | **新增版本检查**：发现工程是旧版本建的，直接报错让你加 `clean`，不让它在跨版本打开上耗时间 |
| 3b | 同上 | `clean` 只重跑建 BD | `clean` 现在会先删掉旧工程目录，杜绝 `runs/`、`.gen/` 残留导致的"改了脚本结果没变" |
| 4 | `tools/build_and_copy.tcl` | `-jobs 4` 写死 | 支持 `export VIVADO_JOBS=8` |
| 5 | `stage05_mlp_hls/hls/script.tcl` | 注释写 `vivado_hls`；`export_design` 不带 `-rtl` | 改用 `vitis_hls`；`export_design -rtl verilog -format ip_catalog` |
| 6 | `tools/package_ip_common.tcl`、`tools/insert_axis_video_proc_common.tcl` | 调 `ipx::*` / `create_bd_cell` 等 | API 在 2024.2 仍在，逻辑不变；只更新版本说明（**这两块需要实跑验证**，见第 8 节） |
| 7 | 各处文档 / VERIFY.md / notebook 文字 | 通篇 2018.3 | 全部更新为 2024.2 |
| 8 | `bitstream_2024_2/ip_repo/` | 原来指向 `boards/src/ip` | 自带一份 rgb2dvi + tmds，不再依赖旧仓库路径 |

### 2.1 2024.2 实跑暴露出来的问题（已修）

第一轮在 2024.2 上试跑，底板 BD 和 IP 打包都顺利过了，但下面 4 个跨版本差异
把流程卡住了。全部已修，你重新拷一次这几个文件即可：

| 现象 | 原因 | 修法 |
| --- | --- | --- |
| 阶段 1 报 `ERROR: [Coretcl 2-101] Project '...' is already open.` | 底板 `cv_ov5640.tcl` 跑完时工程本来就是打开的，2024.2 不允许再 `open_project` 同一个工程（2018.3 不报） | `tools/insert_axis_video_proc_common.tcl` 里新增 `open_project_if_needed`，先比路径，是同一个就跳过 |
| 同上（BD 层面） | 底板脚本结尾 `save_bd_design` 后 BD 仍是开着的，再 `open_bd_design` 会重复打开 | 新增 `close_open_bd`，打开前先关掉 |
| 阶段 2/3 报 `没找到产物 .../cv_ov5640.srcs/.../hw_handoff/cv_ov5640.hwh` | 实现其实**成功了**（日志里有 `write_bitstream Complete!`），但 2024.2 把 `.hwh` 放到了 `.gen/sources_1/bd/<bd>/hw_handoff/`，不再是 `.srcs/` | `tools/build_and_copy.tcl` 改成先找 `.gen`、再找 `.srcs`，最后用 `find` 兜底 |
| BD 里出现两个地址段：`s_axi/Reg`(0x43C1_0000) 和 `s_axi/reg0`(0x4000_0000) | 2024.2 的 `ipx::package_project` 会自动多生成一个默认地址块 `reg0`，和脚本手工建的 `Reg` 重复，会让 PYNQ 解析 `.hwh` 时挑错基地址 | `tools/package_ip_common.tcl` 里删掉非 `Reg` 的地址块；`insert_*` 里再加一层兜底，删掉 BD 里多余的 `reg0` 段 |
| `WARNING: [BD 5-670] It is required to provide a frequency value for a user created input clock port` | 2024.2 要求输入时钟频率直接在 `create_bd_port` 上给，光靠后面 `set_property CONFIG.FREQ_HZ` 落不进去，74.25 MHz 会被当成默认值，跨时钟域检查按错的频率算 | `cv_ov5640.tcl` 里改成 `create_bd_port -dir I -type clk -freq_hz 74250000 vid_pclk`（`vid_xclk` 同理 23809525） |

`lib/*.py`（`dma.py` 的 2018 是 Xilinx 版权年份）和 notebook 里的 Python 逻辑
**不需要改**——它们跑在板子上，与 Vivado 版本无关。

### 2.2 阶段 3 / 阶段 6 的时序问题（原工程遗留，已修）

第一次在 2024.2 上跑完阶段 1/2/3，结果是：

| 阶段 | 结果 |
| --- | --- |
| 阶段 1 | 时序收敛，WNS ≈ +0.59 ns |
| 阶段 2 | 时序收敛，WNS ≈ +0.5 ns |
| 阶段 3 | **时序不收敛，WNS = -5.423 ns，TNS = -289 ns** |

**这不是升级到 2024.2 引入的。** 你自己那份 2018.3 的老日志
（`stage03_feature_extract/stage3_20260930_204300.log`）里就是：

```
2018.3 阶段3:  WNS=-4.776 | TNS=-402.834 | the design failed to meet the timing requirements
2024.2 阶段3:  WNS=-5.423 | TNS=-289.257 | the design failed to meet the timing requirements
```

**根因**：违例路径的起点是 `v_demosaic_0` 的输出 mux 寄存器，终点是本模块的
`acc_luma2_reg[45:37]`。也就是

```
demosaic 输出 mux + 长走线 + 三个乘法求亮度 + 平方 + 48 位累加
```

全挤在同一个 100 MHz（10 ns）周期里，实测约 15.4 ns。

**阶段 7 的 HDL 早就修过同一个坑**（它的 v1.6 注释写着"统计链路再切一级"），
阶段 3 / 阶段 6 没跟上。这次把阶段 7 的那套 4 级流水照搬到阶段 3 和阶段 6：

| 级 | 内容 |
| --- | --- |
| 第 0 级 | `px1_*` —— 本模块自己的寄存器，把 demosaic 的输出 mux 和长走线摘出关键路径 |
| 第 1 级 | 亮度（三个乘加 + 右移）→ `luma16_s1` |
| 第 2 级 | 梯度（\|Δ\|，源是 `luma16_s1`）→ `grad16_s2` |
| 第 3 级 | 平方 + 透传（同一拍登记）→ `luma_sq_s3` / `luma16_s3` / `grad16_s3` |
| 第 4 级 | 累加（`acc_*`） |

代价：统计值比像素晚 4 拍，所以帧边界锁存也要跟着用 `sof_s3`（否则会漏掉
帧尾那几拍）。帧内总和不变。

同时按工程自己的规矩抬了 IP 版本号（`package_ip_common.tcl` 里删旧目录 + 重建，
但版本号不变时工程可能继续用缓存里的旧 IP）：

| 阶段 | IP 版本 | HDL 里的 VERSION |
| --- | --- | --- |
| 阶段 3 | 1.2 → **1.7** | `0x0001_0003` → **`0x0001_0103`** |
| 阶段 6 | 1.3 → **1.4** | `0x0001_0206` → **`0x0001_0306`** |

> 阶段 3 的 IP 版本跳到 1.7 而不是 1.3，是因为 1.3 被阶段 6 占了、1.6 被阶段 7
> 占了；几个阶段的 `ip_repo` 会同时挂进同一个工程，同 VLNV 不同内容会打架。

### 2.3 阶段 7 的两个"手工步骤"已自动化

阶段 7 在 2018.3 上最终能收敛（WNS **+0.134 ns**、失败端点 0），靠的是三件事：

1. HDL 4 级统计流水（v1.6，一直在 `hdl/axis_video_proc.v` 里）
2. `tcl/timing_waiver.xdc` —— 把 `clk_out1_cv_ov5640_clk_wiz_0_0 ↔ clk_fpga_0`
   这两对真异步时钟设成 false path
3. 实现策略 place = `Explore`、phys_opt / post_route_phys_opt = `AggressiveExplore`

**第 2、3 步当时是手工在 GUI 里做的，脚本里没有。** 换机器或换 Vivado 版本重跑
时特别容易漏，漏了就是一句 `Timing 38-282` 淹没在几千行日志里。

现在 `stage07_reconfig_array/tcl/insert_reconfig.tcl`（以及 `release/hw/` 里的副本）
会自动做这两件事：

* 把 `tcl/timing_waiver.xdc` 加进工程 `constrs_1`（已经在里面就不重复加）；
* 给 `impl_1` 设实现策略。directive 名字各版本略有差异，所以给了候选值列表，
  设不上就打印提示并保持默认，不会让整个流程失败。

跑阶段 7 时日志里应该能看到：

```
  把时序约束加进 constrs_1：.../stage07_reconfig_array/tcl/timing_waiver.xdc
  设置实现策略
    PLACE_DESIGN.DIRECTIVE = Explore
    ROUTE_DESIGN.DIRECTIVE = ...
    PHYS_OPT_DESIGN.DIRECTIVE = AggressiveExplore
    POST_ROUTE_PHYS_OPT_DESIGN.DIRECTIVE = AggressiveExplore
```

最后要看到 `== 时序收敛：OK ==`。

### 2.4 新增：密闭演示盒 + 可控光源（盒子模式）

现场演示有两个老问题：**手遮镜头调不到合适的暗度**，以及**特征落在训练没见过的
中间地带时判决不稳**。根因是摄像头默认 **AEC/AGC 全自动**（`0x3503 = 0x00`）——
你把灯调暗，它会自动拉长曝光补偿，画面亮度被顶回去。实测遮镜头 `f_luma` 最低
只到 **27**，而暗光类的中心是 **10**。

新增三个文件（不动原有流程，默认行为完全不变）：

| 文件 | 作用 |
| --- | --- |
| `lib/exposure.py` | OV5640 曝光/增益控制。`set_manual()` 进盒子模式，`set_auto()` 恢复 |
| `tools/box_calibration.ipynb` | 标定用 notebook：切手动曝光 → 调灯 → 三档记录 → 达标判定 → 抓帧对比 |
| `docs/04_demo_box.md` | **材料清单** + 装配要点 + 三档怎么造 + 标定流程 + 常见坑 |

另外 `lib/video_setup.bring_up()` 多了一个可选参数，一行进盒子模式：

```python
ol, iic, ... = vs.bring_up(ROOT, manual_exposure=dict(exposure=512, gain=0x10))
```

不传就还是自动曝光。`lib/ov5640/ov5640_config.py` 里也加了注释，
说明"想开机就手动"该怎么改（不推荐，运行时切换更灵活）。

**关键好处**：标定的目标就是原来的三个类别中心，所以标定成功后
**现有模型和阶段 7 的 bitstream 直接可用，不用重训、不用重出 bit**。

---

## 3. 放到虚拟机的哪里

原工程的 VM 布局是这样（`README_RUN.md` 里写的）：

```
/home/xu/OV5640_capture_only/
├── ai_video/          <- 这份 ai_video_2024.2 覆盖到这里
└── bitstream/         <- bitstream_2024_2/ 里的东西覆盖到这里
```

所以：

```bash
# 1) 把 ai_video_2024.2 里的全部内容（含 tools/stageXX/release/...）拷到 ai_video/
# 2) 把 bitstream_2024_2 里的内容（cv_ov5640.tcl / .xdc / build_bitstream.tcl /
#    check_cv_ov5640.tcl / ip_repo/）拷到 bitstream/
```

> **关键**：`bitstream/cv_ov5640/` 这个旧的 Vivado 工程目录如果是 2018.3 建的，
> 第一次跑一定要带 `clean`（它会被自动删掉重建）。新脚本检测到旧版本会直接
> 报错提醒你，不会硬着头皮打开。

---

## 4. 一次性准备

```bash
# 确认 2024.2 环境（两个都 source，HLS 阶段要用）
source /tools/Xilinx/Vivado/2024.2/settings64.sh
source /tools/Xilinx/Vitis_HLS/2024.2/settings64.sh
vivado -version      # 应显示 Vivado v2024.2
vitis_hls -version   # 应显示 Vitis HLS 2024.2

cd /home/xu/OV5640_capture_only/ai_video
chmod +x build_overlay.sh
```

`build_overlay.sh` 现在会自己 source 环境，所以平时**不 source 也能跑**。

PYNQ-Z2 board files 建议装一下（不装也能跑，只是日志里多一行 WARNING）：

```bash
sudo mkdir -p /tools/Xilinx/Vivado/2024.2/data/boards/board_files/pynq-z2
sudo cp -r PYNQ-Z2/1.0 /tools/Xilinx/Vivado/2024.2/data/boards/board_files/pynq-z2/
```

---

## 5. 跑硬件阶段（阶段 1 / 2 / 3）

```bash
cd /home/xu/OV5640_capture_only/ai_video

bash build_overlay.sh 1 clean    # 阶段1：纯直通 IP（clean = 重建底板，第一次必须加）
bash build_overlay.sh 2          # 阶段2：AXI-Lite 寄存器
bash build_overlay.sh 3          # 阶段3：特征提取
```

每条命令内部依次做四件事（和原来一样）：

1. **基础 BD**：`bitstream/cv_ov5640.tcl` → 建 2024.2 工程；
2. **打包 IP**：把该阶段的 `axis_video_proc.v` 打成 Vivado IP；
3. **插进 BD**：`v_demosaic_0 → axis_video_proc_0 → axi_vdma_0`，阶段 2 起再挂 AXI-Lite；
4. **出 bitstream**：综合 + 实现 + 出比特流，并把 `.bit/.hwh` 同时拷到
   `bitstream/` 和 `ai_video/overlay/`。

阶段成功会打印：

```
############################################################
#  阶段 N 全部完成
#  .../bitstream/cv_ov5640.bit  /  .hwh
#  .../ai_video/overlay/cv_ov5640.bit  /  .hwh
############################################################
```

日志在 `ai_video/logs/stage<N>_<时间戳>.log`。

---

## 6. 跑阶段 5（Vitis HLS）

阶段 6/7 需要 HLS 导出的 `mlp_engine` IP，所以要中间跑一次 HLS：

```bash
source /tools/Xilinx/Vitis_HLS/2024.2/settings64.sh
cd /home/xu/OV5640_capture_only/ai_video/stage05_mlp_hls/hls
vitis_hls -f script.tcl
```

必须看到 `CSIM PASSED` 才能继续。产物在
`stage05_mlp_hls/mlp_engine_prj/solution1/impl/ip/`，阶段 6/7 会自动找到它。

如果提示缺少 `mlp_weights.h` / `tv_mlp.h`，先在虚拟机里跑：

```bash
cd /home/xu/OV5640_capture_only/ai_video/stage05_mlp_hls
python3 make_tv.py
```

> 2024.2 的 `vitis_hls` 会打印一条
> `WARNING: [HLS 200-2053] The vitis_hls executable is deprecated`
> —— 忽略即可，功能正常。

---

## 7. 跑阶段 6 / 7

```bash
cd /home/xu/OV5640_capture_only/ai_video
bash build_overlay.sh 6     # 阶段6：MLP 集成
bash build_overlay.sh 7     # 阶段7：可重构阵列（答辩主阶段）
```

阶段 7 出了名地难收敛（原工程里 WNS 是 -5.093 → 逐步优化到 v1.6）。
`build_and_copy.tcl` 会在时序不收敛时把 WNS/TNS 和最差路径直接打到屏幕上，
**不要划过去**——报告也留在 `bitstream/cv_ov5640/cv_ov5640.runs/impl_1/`。

想加快并行度：

```bash
export VIVADO_JOBS=8
```

---

## 8. 需要你实跑验证的两处（我这边没有 Vivado）

我能在没工具的环境里做的都做了：路径/版本/通配符/IP 仓库定位这些**逻辑问题**
已经全部改掉，并且其中"IP 检查误报"那个 bug 是你上一轮在 2024.2 上实测暴露、
我这边修完的。但下面两块**必须由你在 2024.2 上跑一次**才能确认：

| 要验证的 | 在哪 | 通过标准 |
| --- | --- | --- |
| `ipx::package_project` 系列 API | `bash build_overlay.sh 1` 的步骤 2 | 没有 ERROR，能生成 `stage01_axis_passthrough/ip_repo/user.org_user_axis_video_proc_1.0/component.xml` |
| BD 插入与地址分配 | 同上的步骤 3 | `validate_bd_design` 通过，日志里打印出 `axis_video_proc_0` 的地址段基地址 |
| `export_design` 导出 HLS IP | 阶段 5 | 出现 `xilinx_com_hls_mlp_engine_1_0.zip` 或 `impl/ip/` 里有 `component.xml` |
| 阶段 7 时序 | 阶段 7 | 时报告里 "All user specified timing constraints are met"（或至少 WNS > -0.5） |

如果 `ipx::package_project` 在 2024.2 上报错，把报错原文发我，
通常是某个属性名/参数变了，我按报错改一行就行。

---

## 9. 出错时先看这里

| 现象 | 原因 / 处理 |
| --- | --- |
| `找不到 vivado 命令` | `source /tools/Xilinx/Vivado/2024.2/settings64.sh`，或 `export VIVADO_SETTINGS=/你的路径/settings64.sh` |
| `现有工程是 Vivado v2018.3 建的` | 正常拦截。按提示 `bash build_overlay.sh <阶段> clean` 重建 |
| `在 ... 里找不到 cv_ov5640.tcl` | `bitstream/` 不在 `ai_video/` 旁边。`export AI_VIDEO_BITSTREAM_DIR=/path/to/bitstream` |
| `找不到自定义 IP 仓库（需要 rgb2dvi* 和 if/）` | `bitstream/ip_repo/` 没拷对。把 `bitstream_2024_2/ip_repo/` 拷过去，或 `export AI_VIDEO_IP_REPO=/path/to/ip_repo` |
| `ERROR: [BD_TCL-115] The following IPs are not found` | 用了旧的 `cv_ov5640.tcl`。用 `bitstream_2024_2/` 里那份 |
| `ERROR: [DRC INBB-3] Black Box Instances` | 连带症状，说明基础 BD 没建出来，先解决上一条 |
| 找不到 HLS 导出的 IP | 阶段 6/7 前先跑 `stage05_mlp_hls/hls/script.tcl` |
| `insert_*.tcl` 报缺少端口 | 脚本会把该 IP 的实际端口全列出来，按实际名字改一行 |
| 实现没跑完 | `bitstream/cv_ov5640/cv_ov5640.runs/impl_1/runme.log` |

---

## 10. 上板

把 `ai_video/`（整个目录）和 `overlay/cv_ov5640.bit` + `.hwh` 拷到板上：

```
/home/xilinx/jupyter_notebooks/ai_video/
```

notebook 不用改任何路径：它们会从当前目录往上找 `lib/video_setup.py`，
再在 `overlay/`、`bitstream/` 里自动找 `cv_ov5640.bit`。

---

## 11. 仓库与构建产物说明

仓库保留 2024.2 的源码、Tcl 构建脚本和最终 stage13 overlay。Vivado 的工程缓存、
运行目录和中间网表属于构建产物，不进入 Git，重新执行 `bash build_overlay.sh 13`
即可生成。

早期 2018.3 的 bit/hwh 仅用于历史版本对照，最终运行和报告数据以 stage13
（`VERSION=0x0001020D`）为准。
