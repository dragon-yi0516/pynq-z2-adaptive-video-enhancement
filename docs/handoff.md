# 开发交接说明
# 基于 PYNQ-Z2 的场景自适应视频增强系统

## 1. 这是什么

OV5640 → demosaic → axis_video_proc（逐像素统计/四象限/三模式/PARAM/分屏）
→ 两组 VDMA/DDR → HDMI；PS 用 3-8-3 Q8.8 MLP + 四象限规则做场景自适应。

## 2. 当前状态（2026-10-22）

| 项 | 状态 |
|---|---|
| stage13 bit/hwh | 已验证，`VERSION=0x0001020D` |
| 720p30 HDMI 采集/显示 | 已验证，约 29.76 fps |
| 同亮度 hard pair | 主证据，pair 0 干净；pair 1 为辅助 |
| 真实场景 holdout | 120 帧，MLP/组合均 1.000 |
| 失败/边界 probe | 过曝 30/30 置信度拒绝；白墙无误切；遮镜头判暗光 |
| 1 小时 soak | 3600 s / 107,137 帧 / 29.76 fps / 3 次切换 / 无停流 |
| 同源分屏 | RMS 0.09（判据 <3） |
| 温度 | 本次测试镜像没有 thermal zone，结果不包含温度 |
| 最终 stage13 timing/util/DRC/methodology | 已补，报告在 `stage13_split/reports/stage13/` |
| White Balance / Gamma LUT / TNR | 后续功能方向 |
| 720p60 | 后续性能方向 |

## 3. 30 秒快速开始

```bash
# PC/Ubuntu：不需要板子
bash run_all.sh test
bash run_all.sh eval

# Ubuntu + Vivado 2024.2：重建
bash build_overlay.sh 13
```

## 4. 板子上的顺序

1. 把 `overlay/cv_ov5640.bit` + `.hwh` 换成 **stage13**（`0x0001020D`）；
2. `00_baseline_check.ipynb` 确认 overlay/IP/VERSION；
3. `06_mode_manual.ipynb` 看三模式；
4. `09_demo.ipynb` 走演示；
5. `tools/verify_live_scheduler.ipynb` 看实时闭环；
6. `tools/soak_test.ipynb` 做长时运行。

## 5. 目录

```text
lib/                 PYNQ/寄存器/视频通路/自适应逻辑
tools/               数据采集、评估、soak、实时调度、技能脚本
stage00..13/         分阶段 HDL/HLS/notebook/VERIFY
stage13_split/       最终 stage13 bit/hwh 与分屏验证
data/                特征、hard pair、真实场景、失败场景、live、soak
docs/                设计说明、寄存器、结果页
report/              报告正文、数据底表、AI 协作记录
skill/               4 个通用 PYNQ Skill
overlay/             板上默认加载的 bit/hwh（提交前必须是 stage13）
```

## 6. 证据在哪

- 总数据底表：`report/report_data_sheet.md`
- 实现限制：`docs/results/timing.md`
- AI 协作：`report/ai_collaboration_record.md`
- 结果页：`docs/results/`
- 验证索引：`docs/verification_index.md`
- 技能包：`skill/readme.md`

## 7. 已知问题 / 不要误读

- `overlay/cv_ov5640.bit/.hwh` 已于 2026-10-22 与 `stage13_split/` 同步，
  两边 SHA-256 一致；下次上板仍应读回 `VERSION=0x0001020D` 做最终复核。
- 用户已指定约束内 setup/hold/pulse-width 全过：WNS +0.120 ns、WHS +0.016 ns、失败端点 0。
- methodology 不是“只剩 rgb2dvi”：152 项 TIMING-17 来自 `vid_pclk` 无顶层时钟覆盖；
  另有 clk_wiz 重复主时钟 2 项和 rgb2dvi SerialClk 1 项。报告里必须如实写这个边界。
- DRC 为 0 Error / 0 Critical Warning，但有 195 个 Warning；主要是 DSP 流水建议、
  LUT 配对布局和 `vid_pclk` 非 CCIO 时钟放置提示。
- `soak.csv` 只有 59 条心跳（60–3540 s），3600 s 总结在 `data/soak.log`；
  107,137 是总帧增量，不是最终绝对帧计数；没有“末尾停流”。
- 四象限只有 4 块，不能定位小面积高光。
- 3 类、540 帧盒子数据；真实场景 120 帧只代表本次 3 个场景。
- 720p30，不是 60 fps；IP 理论吞吐 100 Mpixel/s，720p30 只用约 27.4%。

## 8. 调参入口

- 空间阈值：`lib/adaptive.py` 的 `SPATIAL_U_LO/HI`（当前 0.30/0.55）
- 连续强度：`lib/adaptive.py` 的 `gain_param/stretch_param/sharpen_param`
- 调度防抖：`stage08_auto_schedule/auto_schedule.py` 或 `tools/live_scheduler_notebook.py`
- 采集协议：`tools/collect_dataset.py`、`tools/collect_hard_pairs.py`、`tools/collect_real_scene.ipynb`

## 9. 发布状态

- stage13 `overlay/cv_ov5640.bit/.hwh` 已与 `stage13_split/` 同步，SHA-256 一致；
- stage13 `timing_final/util_final/drc_final` 已归档到 `stage13_split/reports/stage13/`；
- 报告、数据底表、AI 协作记录和 4 个 Skill 已进入仓库；
- `eval_spatial.json` 使用当前 0.30/0.55 阈值；
- GitHub Actions 的离线检查与评估流程通过；
- 实物照片和演示视频适合放在比赛提交附件及发布页，不放进源码仓库。