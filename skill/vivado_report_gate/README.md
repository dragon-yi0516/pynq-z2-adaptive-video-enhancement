# vivado_report_gate

## 适用场景

任何 Vivado 工程实现完成后的“门禁检查”：

* 把 `report_timing_summary` 的 WNS/TNS/失败端点解析成一行；
* 把 `report_utilization` 的 LUT/FF/BRAM/DSP 解析成表；
* 同时支持标准 utilization 表和 `-hierarchical` 顶层汇总表；
* 按阈值判断“能不能提交/能不能继续优化”，并生成可直接贴进报告的表。

## 使用方法

先在 Vivado 里生成报告：

```tcl
open_run impl_1
report_timing_summary -file timing_final.rpt
report_utilization -file util_final.rpt
report_drc -file drc_final.rpt
```

再运行：

```bash
python3 check_vivado_reports.py \
  --timing timing_final.rpt \
  --util util_final.rpt
```

可调阈值：

```bash
python3 check_vivado_reports.py ... --min-wns 0 --max-lut 50 --max-bram 60 --max-dsp 30
```

退出码：0 = 全部通过；1 = 有超阈值项；2 = 报告格式/文件错误。

## 失效条件

* 不是 Vivado 的 summary 格式（例如只有 GUI 截图、没有文本报告）；
* 多 corner / 多时钟摘要里第一行不是你想比较的主时钟；
* 报告被手工改过或只截取了局部；
* 它不是 CDC/DRC 的完整签核，只读摘要数字。

## 已验证效果

在本项目 stage13 最终报告上：

```text
WNS +0.120 ns, TNS 0.000, setup failing endpoints 0
LUT 29.82%, FF 19.49%, BRAM 22.50%, DSP 26.36%
```

脚本判定 PASS。该次测试读取的是 Vivado 2024.2 的 `report_utilization -hierarchical`

输出，脚本会从顶层资源行换算百分比。stage7 的 `+0.134 ns / 30.71% / 18.03% / 22.50% / 20.00%`
只保留为历史基线。

## 提炼来源

* stage7 和 stage13 混用时，容易把 stage7 资源当最终用量；
* 只贴 WNS、不贴最终 utilization，会被评委追问；
* 手工从 `.rpt` 抄数字容易把 WNS/TNS、used/available/percent 抄错。

## 边界

这是“摘要门禁 + 报告表生成器”，不是时序签核工具。
真实签核仍要看完整 `report_timing_summary`、`report_drc`、CDC 报告和板上实测。
