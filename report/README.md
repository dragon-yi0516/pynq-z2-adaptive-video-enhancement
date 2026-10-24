# 报告材料索引

## 先确认写哪一套

| 报告 | 模板 | 用哪些文件 |
|---|---|---|
| FPGA 设计报告 | `自主选题初级赛道报告模板.md` | `design_report.md` + `AI_COLLABORATION_RECORD.md` |
| 作品报告 | `参考文档.docx` | `WORKS_REPORT_OUTLINE.md`（不含 LLM 章节） |

两套共用 `report_data_sheet.md`，不要把章节名混在一起。

## 给写手（先读第一项）

| 文件 | 用途 |
|---|---|
| `REPORT_HANDOFF.md` | **先读**：写作顺序、评分表对照、口径、图表、待补项 |
| `report_data_sheet.md` | 唯一数字底表；所有表格/数字从这里抄 |
| `design_report.md` | 完整正文草稿，可直接改写/扩写 |
| `design_report_outline.md` | 按评分表分的 10 节提纲 |
| `presentation_outline.md` | 10 页 PPT + 60 秒视频分镜 + Q&A |
| `AI_COLLABORATION_RECORD.md` | **完整版**：报告第 4 章 + 附录 11.2，含设计/实现/调试/总结、12 条交互索引、Prompt 模板 |
| `llm_collaboration.md` | 早期 7 episode 精简版，可作素材 |
| `WORKS_REPORT_OUTLINE.md` | **作品报告**（参考文档.docx）五部分提纲：作品概述/系统组成/完成情况/总结/参考文献 |
| `SCORE_IMPROVEMENT_PLAN.md` | 两周提分计划：真实场景/失败案例/soak/视频/可选第 4 模式 |
| `MODEL_CARD.md` | 模型卡：用途、数据、指标、限制、隐私、复现 |
| `REPORT_REVIEW_20261021.md` | 作品报告审阅：P0/P1 修改清单、soak 口径纠正、提交前检查 |
| `PAPER_OUTLINE.md` | **论文大纲**：标题/贡献/10 节结构/实验矩阵/投稿策略 |
| `VENUE_RECOMMENDATION.md` | 投稿 venue 推荐：首选 Microprocessors and Microsystems，次选 JRTIP/ISCAS |
| `ICTA_PAPER_PLAN.md` | ICTA 4 页会议短文方案：结构/图表预算/最低实验集/CFP 核对清单 |
| `ICTA_PAPER_DRAFT.md` | ICTA 4 页英文初稿（Abstract/Intro/Architecture/Implementation/Results） |
| `ICTA_SUBMISSION_CHECKLIST.md` | ICTA 投稿清单：CFP/页数/双盲/实验/两周排期 |
| `assets/README.md` | 图表素材与补拍清单 |
| `assets/make_figures.py` | 从 CSV 生成报告图（需要可用 matplotlib） |

## 已有 Word 文件

* `design_report.docx`：最终报告目标文件（把 `design_report.md` 的内容搬进去）；
* `report_writing_plan.docx`：早先的写作计划，可作参考。

## 一句话交接

> 报告不要从零写：以 `design_report.md` 为底稿，
> 数字全部以 `report_data_sheet.md` 为准，
> 口径与禁止说法看 `REPORT_HANDOFF.md` 第 5 节。

## GitHub 调研与工程交付

- `RELATED_WORK.md`：mini-ISP、video-pipeline-core、gesture_pl、64feature、OV7670、TileLab 对照与定位；
- `GITHUB_OPTIMIZATION_REVIEW_20261022.md`：GitHub 调研后的一周优先级；
- 根目录 `HANDOFF.md`：第一次打开先看；
- `docs/verification_index.md`：每项验证的命令/判据/证据；
- `.github/workflows/ci.yml`：离线单测与评估 CI。