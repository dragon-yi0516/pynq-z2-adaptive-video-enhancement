# OV5640 自适应图像增强系统（PYNQ-Z2）

构建时间：{{DATE}}
训练数据来源：{{DATA_SOURCE}}

## 这是什么

在 PYNQ-Z2 + OV5640 上做的一条“感知—决策—执行”闭环视频流水线：

```
OV5640 -> v_demosaic -> axis_video_proc -> axi_vdma_0 -> DDR
        -> axi_vdma_0(MM2S) -> axi_vdma_1 -> v_axi4s_vid_out -> rgb2dvi -> HDMI
```

`axis_video_proc` 一个 IP 里做了四件事：

1. 每帧统计亮度/亮度平方/梯度三个特征（纯加法器，无 BRAM）；
2. 在帧边界把特征交给 HLS 的 `mlp_engine`（3-8-3，Q8.8 定点）做场景分类；
3. 按 `MODE_SEL` 用可重构阵列做三种增强（暗光增强 / 逆光补偿 / 细节锐化）；
4. 除像素处理外全部寄存器通过 AXI-Lite 暴露给 PYNQ，Jupyter 可读可写。

## 目录

| 目录 | 内容 |
|------|------|
| `overlay/` | `cv_ov5640.bit` + `cv_ov5640.hwh`，PYNQ 加载用 |
| `notebooks/` | 00~09 全部 notebook，编号即执行顺序 |
| `weights/` | `mlp_weights.h`（Q8.8 定点权重） |
| `data/` | 训练特征 `features.csv`、`features_demo.csv`、`mlp_float.npz`；`baseline.json` 由 `00_baseline_check.ipynb` 生成（可选） |
| `hw/` | 自定义 IP 的 HDL/HLS 源码、Vivado/HLS 脚本、**重建必须的时序约束** `timing_waiver.xdc`，以及最终版时序/资源报告 `timing_v3.rpt` / `util_v3.rpt` |
| `docs/` | 设计说明、寄存器表、阶段指南 |

## 快速开始

1. 把整个目录拷到板子：`/home/xilinx/jupyter_notebooks/ai_video/`
2. 依次打开 `notebooks/` 里的 notebook：

   ```
   00_baseline_check.ipynb     确认 overlay 和 IP
   01_axil_regs.ipynb          确认视频通路 + 寄存器
   02_feature_collect.ipynb    采三类场景特征（可选，用于重训）
   03_mlp_train.ipynb          训练
   04_mlp_quant_export.ipynb   量化导出
   05a_mlp_hls_verify.ipynb    PC 侧：HLS csim 对测试向量
   05b_mlp_board_verify.ipynb  板上：MLP 输出随场景变化
   06_mode_manual.ipynb        手动切三种模式
   07_auto_schedule.ipynb      自动调度闭环
   08_perf_test.ipynb          性能测试
   09_demo.ipynb               答辩演示流程
   ```

3. 演示时先 `Restart Kernel`，再按 `09_demo.ipynb` 的流程走。

## 结果速览（验收数据）

| 项目 | 数值 | 出处 |
|------|------|------|
| 时序 | 收敛：`All user specified timing constraints are met`，WNS **+0.134 ns**，失败端点 0 | `timing_v3.rpt` |
| 资源占用 | LUT **30.71%** / BRAM **22.50%** / DSP **20.00%**（7z020） | `util_v3.rpt` |
| 帧率 | **29.6 fps**（1280×720@30；60 秒长跑 27.3~29.8） | `08_perf_test.ipynb` |
| 模式切换响应 | **1 帧**（≈33 ms，帧边界重采样） | `08_perf_test.ipynb` |
| 寄存器读延迟 | **21~25 µs**（PYNQ 3.0 走 XRT/pl_server 软件路径，硬件 AXI-Lite 亚微秒级） | `08_perf_test.ipynb` |
| 自动调度闭环 | MLP → 防抖（连续 8 次一致）→ 时间闸（2 s）→ 帧边界写 `MODE_SEL` | `07_auto_schedule.ipynb` + `sched.log` |

## 硬件重建

```bash
# 1) 自定义视频处理 IP（最终版 = 含重构阵列 + MLP 握手）
vivado -mode batch -source hw/package_ip.tcl

# 2) HLS MLP 引擎（需要 Vitis HLS 2024.2）
vitis_hls -f hw/hls_script.tcl

# 3) 重建 BD 并插 IP
vivado -mode batch -source <原始工程的 cv_ov5640.tcl>
vivado -mode batch -source hw/insert_reconfig.tcl
vivado -mode batch -source <原始工程的 build_bitstream.tcl>
```

原始 BD 来自开源工程 `Pynq-CV-OV5640`，本交付只替换其中“算法链”那一段。

⚠️ **重建时必须把 `hw/timing_waiver.xdc` 加进 `constrs_1` 再跑实现**：

* 施工内容：把 PS 时钟域 `clk_fpga_0` 与摄像头像素时钟域
  `clk_out1_cv_ov5640_clk_wiz_0_0` 之间的路径声明为 false path。
  两域之间只有 Xilinx IP 内部的异步 FIFO（结构性安全），
  而这两个时钟本来没有固定相位关系（Xilinx 自己的 PS 约束文件里也写着
  "The clocks are asynchronous, user should constrain them appropriately"）。
* 不加的后果：报告里会有 3 个 `async_default` 违例（WNS **-4.044**）；
  加上之后是 `All user specified timing constraints are met`（WNS **+0.134**）。
* 文件里还有一条**被注释掉**的 `create_clock -name vid_pclk ...`：顶层确实缺
  摄像头像素时钟的约束（原来那 152 个寄存器处于"不检查"状态），补上会引入新的
  时序要求，属可选改进，本次交付未启用。
* 想复现本次结果，实现策略建议用 place=`Explore`、route/phys_opt=`AggressiveExplore`。

## 文件清单（SHA256 前 16 位）

| 文件 | SHA256 |
|------|--------|
{{MANIFEST}}

## 许可与致谢

基础 BD、`rgb2dvi`、OV5640 配置表来自开源工程 `Pynq-CV-OV5640`（BSD-3-Clause）。
当前项目新增部分：`axis_video_proc`（Verilog）、`mlp_engine`（Vitis HLS）、
以及全部 Jupyter 流程与训练/量化工具链。
