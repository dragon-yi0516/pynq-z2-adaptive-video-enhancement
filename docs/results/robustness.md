# 失败/边界场景（2026-10-20）

数据：`data/robust_lens_covered.csv`、`robust_overexposed.csv`、
`robust_uniform_wall.csv`；每 case 30 帧，probe 不写 `MODE_SEL`。

复现：

```bash
python3 -c "import sys; sys.path.insert(0,'tools'); import robustness_notebook as r; r.summary_all()"
```

## 汇总

| case | n | f_luma | u | MLP | confident | decision | 实际 mode | 结论 |
|---|---|---|---|---|---|---|---|---|
| 遮镜头/全黑 | 30 | 3.0 | 0.005 | 0 | 30/30 | 0 | 0 | 语义上是暗光，保持 mode 0；没有误切 |
| 均匀白墙 | 30 | 12.0 | 0.271 | 0 | 30/30 | 0:23 / hold:7 | 0 | u 低，信任 MLP；7 帧保持，没有误切 |
| 过曝 | 30 | 213.6 | 0.116 | 1 | **0/30** | 1:30（目标） | 0 | 门限 30/30 拒绝，实际模式保持 0 |

## 怎么解读

### 过曝：门限有效

`confident=0` 表示 30 帧全部被置信度门限拒绝；
`decision=1` 只是空间规则的目标，**没有**被采纳；
实际 `mode` 保持 0。这是“过曝不导致乱切”的直接证据。

### 遮镜头：语义上是暗光，不是 unknown

f_luma=3、f_grad=3~5，MLP 判 0（暗光），门限接受。
这不算错：遮镜头本来就是“全黑”。
如果希望显式 `unknown`，可以加一个黑帧守卫：
`f_luma < 5 且 f_grad < 6 -> not confident`。
这部分属于 PS 侧规则增强，改动量约 3 行，不需要重出 bit，放在后续版本继续验证。

### 均匀白墙：没有误切

u=0.271，23 帧信任 MLP、7 帧落在 0.30~0.55 的保持带；
实际 mode 一直是 0。说明迟滞在边界上工作，不会因为 u 的小抖动乱切。

### 快速切换

快速切换的补充实验可以在 `check_robustness.ipynb` 最后一格运行 20 秒，记录切换次数、模式序列和是否振荡。
