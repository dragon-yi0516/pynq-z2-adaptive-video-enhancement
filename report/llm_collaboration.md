# 大模型协作记录（初稿）

这份记录按“提示词 → 模型回答（摘要）→ 实际结果 → 自我纠错 → 验证 → 沉淀 Skill”
整理。内容来自当前项目真实的调试过程；提示词为当时的意图复述，数字和现象来自
`README_2024.2.md`、`docs/05_optimization_plan.md`、`docs/07_recollect_and_gate.md`
和板上日志。

## 工作流

```text
读日志/报告/波形
   -> 让模型给出 2~3 个可验证的假设
   -> 在板上一次只改一个变量
   -> 把实测结果回填给模型
   -> 模型修正假设，直到通过验收
   -> 把这次失败/修正提炼成 Skill 或判据
```

关键原则：**模型负责提出假设和解释，板上实测负责裁决**。
下面每个 episode 都有“模型第一次说对了什么、说错了什么”。

---

## Episode 1：Vivado 2024.2 迁移后的四个坑

**提示词**

> 工程从 2018.3 迁到 2024.2。阶段 1 报
> `Project '...' is already open`；阶段 2/3 实现成功但找不到 `.hwh`；
> BD 里出现 `s_axi/Reg` 和 `s_axi/reg0` 两个地址段；还有一个输入时钟频率警告。
> 帮我按现象逐条定位。

**模型回答（摘要）**

1. 2024.2 不允许对已经打开的工程再 `open_project`，先比较路径；
2. `.hwh` 从 `.srcs/.../hw_handoff` 移到了 `.gen/.../hw_handoff`；
3. `ipx::package_project` 会自动生成默认 `reg0` 地址块，和手工建的 `Reg` 重复；
4. 输入时钟频率要直接写在 `create_bd_port -freq_hz` 上。

**实际结果**

四条全部复现；按上述修法后阶段 1/2/3 能连续跑通。
其中第 2 条一开始只改了 `.srcs` 路径，仍然找不到；后来加了
“先找 `.gen`、再找 `.srcs`、最后 `find` 兜底”才稳定。

**自我纠错**

模型最初把 `.hwh` 当成“实现失败”，但日志里明明有
`write_bitstream Complete!`。改为“实现成功、只是产物路径变了”后，
排查方向才正确。

**验证**

阶段 1/2/3 的 `build_overlay.sh` 全部打印 `# 阶段 N 全部完成`；
板上 `VERSION` 读回与阶段号一致。

**沉淀**

`skill/pynq_overlay_preflight` 的“先核对 IP/VERSION，再怀疑逻辑”；
以及 `tools/build_and_copy.tcl` 的 `.gen` 兜底路径。

---

## Episode 2：阶段 3 时序 -5.4 ns，一次切流水不够

**提示词**

> 阶段 3 在 100 MHz 下 WNS=-5.423 ns，路径从 `v_demosaic_0` 输出 mux
> 到 `acc_luma2_reg[45:37]`。帮我看这条路径该怎么切。

**模型回答（摘要）**

把“三个乘法求亮度 → 平方 → 48 位累加”拆成多级流水；
第一版建议只切一刀：亮度/梯度一级、平方一级。

**实际结果**

第一版把 WNS 从 -5.09 改善到 -3.92，但仍然不收敛；
最差路径变成 `v_demosaic -> grad16_a`，说明源头那段长走线还在关键路径上。

**自我纠错**

模型第二次建议把统计源改成**本模块自己的寄存器** `px1_*`，
把 `v_demosaic` 输出 mux 和长走线从路径上摘掉，再分成
亮度 → 梯度 → 平方 → 累加四级。最终 stage7 报告 WNS=+0.134 ns，
失败端点 0。

**验证**

`stage07_reconfig_array/timing_v3.rpt`：
`All user specified timing constraints are met.`，WNS +0.134 ns。

**沉淀**

`skill/pynq_overlay_preflight` 的“先看路径起点是不是上游 IP 的 mux”；
以及 `docs/05` 里的“统计链路四级流水，别再改回去”。

---

## Episode 3：`f_grad` 在真机上恒等于 2

**提示词**

> 三个 MLP 特征里，`f_grad` 在板上一直是 2，std=0。
> 公式是 `GRAD_SUM >> 20`，是不是移位取太大了？

**模型回答（摘要）**

1280×720 帧里平均梯度只有 0~5 的量级，`>>20` 会把典型值压成 0/1/2；
改成 `>>16`，让典型值落到几十，同时仍在 int16 范围内。

**实际结果**

改成 `>>16` 后 `f_grad` 有 10~32 的分布，C2/C8 体检从 FAIL 变成 PASS。

**自我纠错**

模型第一次只改了 Python 的 `MLP_FEAT_SHIFT`，忘了 HDL 里也有一份
`reg_f3_r <= acc_grad >> 16`；板上仍然读到旧值。后来把
“Python/HDL/HLS 三处移位必须一致”写成检查项。

**验证**

`tools/check_features.py` 的“标签内不同取值”从 1 变成十几；
`docs/01_register_map.md` 和 `lib/ai_video_regs.py` 的移位一致。

**沉淀**

`skill/golden_reference_ci` 的“先导出特征分布，再谈模型”。

---

## Episode 4：逆光补偿方向写反

**提示词**

> 我按“对比度越低补偿越强”写了 `stretch_param()`，
> 但板上实测对比度 13 时 PARAM=128、26 时 140、75 时 244，
> 方向好像反了。逆光补偿到底该按什么方向？

**模型回答（摘要）**

逆光补偿做的是“暗部提亮 + 亮部压下”，即压低整体反差；
场景反差越大，越需要强的补偿。因此应该是“对比度越高，PARAM 越大”。
模型最初的方向是错的。

**实际结果**

翻转后 `stretch_param()` 在对比度 20/80 时分别给 128/255，
与板上“逆光档 std 从 64.4 压到 40.0”的现象一致。

**自我纠错**

这是“模型先给了一个听起来合理、但物理方向反了”的典型例子。
纠正依据不是再问一次模型，而是板上 `std` 的实测方向。

**验证**

`docs/08_report_evidence.md` 第 10 节：
逆光档均值 64.7→89.8（+39%），std 64.4→40.0（−38%）。

**沉淀**

`docs/05` 的“参数方向必须用实测的单调性验证”；
以及 `12_verify_adaptive.ipynb` 的 PARAM 扫描表。

---

## Episode 5：PARAM 写得进去、读回一直是 0

**提示词**

> `regs.set_param(192)` 后画面确实变亮了，但 `regs.param()` 一直读 0。
> 写通道用 `aw_addr[5:2]`，读通道是 `case (addr)`，哪里错了？

**模型回答（摘要）**

写通道比较的是**字索引**，读通道比较的是**字节地址**；
新加的 `0x34/0x38/0x3C` 在读通道里写成了 `6'h0D/0E/0F`，永远命中 default。
改成 `6'h34/38/3C`。

**实际结果**

修正后 `regs.param()` 读回 192/255，四象限也能读回非零值。

**自我纠错**

模型同时提醒：`reg_param` 原来只在复位分支赋值，上电值可能是 0；
而 PARAM=0 会让 mode0 增益变成 ×0（整屏黑）。于是加了上电初值 192。

**验证**

`12_verify_adaptive.ipynb` 的 `regs.param()` / `regs.quads()` 读回；
`docs/05` 第 3 节记录了这次 bug。

**沉淀**

`skill/axil_register_contract`：寄存器表 → HDL 地址扫描，专抓这类
“写得进去、读不回来”的问题。

---

## Episode 6：权重更新了，板上还是旧模型

**提示词**

> 我重训并导出了新的 `mlp_weights.h`，但板上 monitor 的判决和旧模型一样。
> 怎么确认 bitstream 里到底是哪份权重？

**模型回答（摘要）**

比较 `weights/mlp_weights.h`、`stage05_mlp_hls/src/mlp_weights.h`
和 `overlay/cv_ov5640.bit` 的修改时间/指纹；bit 比权重旧就说明没重出。

**实际结果**

`tools/check_weight_sync.py` 报“bitstream 比权重旧 7972 分钟”；
重跑 `build_overlay.sh 12` 后三者一致。

**自我纠错**

一开始只比了权重和 HLS 源码，没比 bitstream；漏掉了“板上跑的是 bit”这一层。

**验证**

`tools/check_weight_sync.py` 退出码 0；板上 `VERSION` 与构建阶段一致。

**沉淀**

`skill/pynq_overlay_preflight` 的“VERSION + 权重指纹”双检查。

---

## Episode 7：分屏 rev01 的黑带与左右错位

**提示词**

> 分屏第一版每行都有黑带，左右内容还错位。列计数 `q_col` 在行间消隐期
> 也在自增，是不是这个原因？

**模型回答（摘要）**

是。列计数必须只在**有效像素**（`tvalid & tready`）时递增，
行首清零；否则每行会累积错位。行缓冲的写地址也要用同一个有效列计数。

**实际结果**

rev02 只在有效像素计数后，黑带消失；同帧自洽 RMS=0.09，
错配项 176.0，说明左右配对正确。

**自我纠错**

模型一开始还建议用“行首/行尾”判断，但实际流里 `tlast` 和消隐的关系
需要以仿真/抓帧为准；最后用 `tvalid & tready` 最稳。

**验证**

`13_verify_split.ipynb`：同帧自洽 RMS=0.09（<3），
列剖面中位差 1~2，错配项 176（>100）。

**沉淀**

`docs/06_split_screen_options.md` 的“列计数只在有效像素递增”；
以及 `skill/pynq_overlay_preflight` 的“先看时序/有效信号，再改算法”。

---

## 小结：模型说错的地方

| Episode | 模型第一次的判断 | 板上实测后的修正 |
|---|---|---|
| 2024.2 `.hwh` | 以为实现失败 | 实现成功，路径从 `.srcs` 移到 `.gen` |
| 阶段 3 时序 | 只切一刀流水 | 还要把统计源换成 `px1_*`，共四级 |
| `f_grad` | 只改 Python 移位 | HDL 里的 `reg_f3_r` 也要同步 |
| `stretch_param` | 对比度低→补偿强 | 方向反了：对比度高→补偿强 |
| 分屏列计数 | 行首/行尾判断 | 只在 `tvalid & tready` 时计数 |

这些“说错→实测→修正”的轨迹，就是这个项目大模型协作部分最有价值的内容；
它比“模型一次就写对”更可信，也能直接支撑 `skill/` 里的失效条件。
