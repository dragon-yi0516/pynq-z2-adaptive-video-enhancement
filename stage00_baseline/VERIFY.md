# 阶段 0 验收清单：冻结基线

对应方案书：阶段 0「在当前 Jupyter 里冻结基线」。

## 跑之前

把本工程目录（`ai_video/`）拷到板子的 `/home/xilinx/jupyter_notebooks/` 下，
并确保 `ai_video/overlay/cv_ov5640.bit` + `.hwh` 就是你现在能出图的那一版。

## 跑

打开 `00_baseline_check.ipynb`，从上到下依次运行。

## 必须满足（缺一不可）

- `IP 列表` 打印出来了，并且至少包含
      `axi_iic_0`、`axi_vdma_0`、`axi_vdma_1`、`v_demosaic_0`、`v_tc_0`、`rgb2dvi_0`。
- 脚本自动判定并打印：当前 overlay **是/不是** 本工程自己生成的。
- 打印出「有 AXI-Lite 接口的 IP」清单（后面阶段要控制的就是这一类）。
- `ai_video/data/baseline.json` 生成成功，里面记录了 `.bit` / `.hwh` 的 SHA256。
- 终端明确告诉你下一步该做什么（阶段 1 或先生成 overlay）。

## 阶段 0 通过的标准结论

* 如果 `axis_video_proc_0` **不存在** → 正常，说明还没加自定义 IP，
  直接进入阶段 1 用 Vivado 加。
* 如果 `axis_video_proc_0` **已经存在** 且 `VERSION` 能读出 `0x00010000`
  → 说明阶段 1/2 已经做过，直接跳到阶段 3。

## 为什么要先做这一步

后面所有阶段都要读寄存器、抓帧。如果连“现在板子上到底是哪个 overlay”
都没确认，出现问题时无法判断是 HDL 的锅还是 notebook 的锅。
`baseline.json` 里的 SHA256 就是你的“存档点”，任何一个阶段出问题都可以对照它回退。
