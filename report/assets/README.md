# 报告图表素材

## 已有

| 文件 | 用途 | 备注 |
|---|---|---|
| `architecture.png` | 系统架构图 | 来自上游 Pynq-CV-OV5640；建议按当前项目重画，标出 `axis_video_proc` 和四象限 |
| `system_diagram.png` | 板卡/摄像头/HDMI 连接示意 | 来自上游工程；现场照片更好 |

## 建议补拍/补画

1. **现场照片**：PYNQ-Z2 + OV5640 + HDMI 显示器 + 演示盒/光源；
2. **VERSION 截图**：`setup` 格输出 `VERSION = 0x0001020D`；
3. **preview 截图**：`f=(...) quads=(...) u=...`；
4. **live 汇总截图**：`live.summary_all()` 的四行表；
5. **分屏截图**：HDMI 左原始/右处理后的同一区域；
6. **失败案例**：遮镜头/均匀白墙 → 门限拒绝或保持。

## 建议生成的图

如果环境有可用的 matplotlib，可运行：

```bash
python3 report/assets/make_figures.py
```

会生成：

* `hard_pair_f_luma.png`：四个场景的 f_luma 柱状图；
* `hard_pair_u.png`：四个场景的 u 柱状图；
* `hard_pair_decisions.png`：MLP vs 空间决策的堆叠柱状图；
* `live_mode_timeline.png`：四场景 mode 随时间变化；
* `live_u_timeline.png`：四场景 u 随时间变化；
* `fixed_vs_adaptive_saturation.png`：29.4% vs 0.4%。

如果 matplotlib 不可用，直接用 `report/report_data_sheet.md` 的表，
在 Excel/PPT 里画同样的图即可；数字不要改。
