# Skill package

这四个 Skill 是从本项目的真实调试过程中提炼的，**不绑定本题目**：
换一个 PYNQ overlay、换一块 Zynq 板卡仍然可用。

每个 Skill 的 README 都包含：

* 适用场景
* 使用方法
* 失效条件
* 已验证效果
* 提炼来源（从哪些失败/观察中总结）
* 边界

| Skill | 一句话 | 目录 |
|---|---|---|
| `pynq_overlay_preflight` | 加载 overlay 后先核对 IP 清单、VERSION、VDMA 状态，避免“代码没错但板上跑的是旧 bit” | `pynq_overlay_preflight/` |
| `axil_register_contract` | 一份寄存器表同时生成 Python 封装和 HDL 一致性检查，防止地址/位宽两边写岔 | `axil_register_contract/` |
| `golden_reference_ci` | Python 定点参考 vs HLS/板上输出的逐条比对，输出可进报告的差异表 | `golden_reference_ci/` |
| `vivado_report_gate` | 解析 Vivado WNS/TNS 与资源占用，按阈值生成可提交的 PASS/FAIL 表 | `vivado_report_gate/` |

## 怎么在自己的题目里用

1. 复制对应目录到你的工程；
2. 按 README 改 2~3 个路径/参数；
3. 先跑目录里的 `example/` 或 `--help`，确认脚本本身能跑；
4. 再把你的 overlay / 寄存器表 / 参考模型接进去。

## 已验证范围

* `pynq_overlay_preflight`：本项目的 stage13 overlay 上做过 IP 清单/VERSION/VDMA 检查；
* `axil_register_contract`：本项目的 `docs/01_register_map.md` + `axis_video_proc.v` 上做过地址一致性检查；
* `golden_reference_ci`：本项目 124 条 MLP 测试向量上做过 Python vs HLS CSim 的逐条比对。
* `vivado_report_gate`：在 stage13 最终报告上复现 WNS `+0.120 ns`、TNS `0.000`、LUT `29.82%`、FF `19.49%`、BRAM `22.50%`、DSP `26.36%`，门禁 PASS；stage7 数据作为历史基线保留。

具体数字和失败案例见各子目录 README。
