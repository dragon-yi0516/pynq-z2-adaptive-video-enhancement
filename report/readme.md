# 报告与数据说明

`report/` 目录里放的是项目正文、数据底表和 AI 协作记录。写比赛报告时，建议先看这里，再按需引用 `docs/` 里的结果页。

| 文件 | 用途 |
|---|---|
| `design_report.md` | 当前设计报告正文，新的叙述和结论已更新到这个文件 |
| `report_data_sheet.md` | 主要实测数据、来源和口径，写报告时优先从这里取数 |
| `ai_collaboration_record.md` | 大模型协作过程，包括问题、修改、验证和 Skill 提炼 |
| `llm_collaboration.md` | 较早的精简版协作记录，可作为补充材料 |
| `model_card.md` | MLP 的输入、输出、数据、指标和限制 |
| `related_work.md` | 与 mini-ISP、video-pipeline-core 等公开工程的对比 |
| `assets/` | 架构图、系统连接图和画图脚本 |

## 写作口径

- 实测数据从 `docs/results/` 和 `report_data_sheet.md` 取，不要重新估算；
- 不能把 stage7 的资源数据当成 stage13 最终数据；
- 不能把“用户已指定约束内时序通过”写成“整个设计零 Critical Warning”；
- 1 小时 soak 的总帧增量是 107,137，不能和 CSV 的绝对帧计数直接相减；
- hard pair 的 pair 0 是主证据，pair 1 只作辅助。

## 关于 Word 版

仓库不保留早期的报告骨架 docx。该文件的内容与当前正文不一致，已经移除。需要通过比赛模板提交 Word 版时，以 `design_report.md` 为正文底稿，按当届模板重新排版。