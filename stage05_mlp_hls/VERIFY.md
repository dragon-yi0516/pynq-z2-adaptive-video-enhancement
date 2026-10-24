# 阶段 5 验收清单：Vitis HLS MLP 推理引擎

对应方案书：阶段 5「Vitis HLS 实现 MLP 推理引擎」。

## 步骤

**第 1 步：生成测试向量 `src/tv_mlp.h`**（二选一）

```bash
# A) 在板子上跑 notebook（板子一定有 numpy）
#    打开 stage05_mlp_hls/05_mlp_verify.ipynb，从上到下跑完

# B) 在虚拟机里直接跑脚本（需要 numpy；没有就 sudo apt install -y python3-numpy）
cd /home/xu/OV5640_capture_only
python3 ai_video/stage05_mlp_hls/make_tv.py
```

两种方式做的事一样：把 `weights/mlp_weights.h` 同步到 `src/`，再从 `data/features.csv`
每类抽 40 条 + 4 条边界样本，用 **Python 定点参考实现** 算出期望类别，写成 `src/tv_mlp.h`。
跑完会打印 `测试向量数: 124 期望类别分布: {...}`。

**第 2 步：跑 HLS**

```bash
source /tools/Xilinx/Vivado/2024.2/settings64.sh     # 把 vivado_hls 加进 PATH
cd /home/xu/OV5640_capture_only/ai_video/stage05_mlp_hls/hls
vivado_hls -f script.tcl
```

`script.tcl` 会先检查 `src/` 下的四个文件在不在（缺了会直接告诉你该先跑什么），
然后 C 仿真 → C 综合 → 导出 IP。日志留在 `stage05_mlp_hls/hls/` 下。

## 必须满足（缺一不可）

- [ ] `csim_design` 通过，打印 `TV_N=124  fail=0` 与
      `CSIM PASSED: HLS 与 Python 定点参考完全一致`。
      （脚本还会去 csim 的输出目录里搜这个字符串做双保险，找不到就 `exit 1`。）
- [ ] `csynth_design` 成功，`solution1/syn/report/mlp_engine_csynth.rpt` 里
      延迟远小于 1ms（本设计每帧只跑一次，指标非常宽松）。
- [ ] 导出 IP 出现在 `mlp_engine_prj/solution1/impl/ip/`。
- [ ] `stage05_mlp_hls/src/mlp_weights.h` 和板子上跑的那份**是同一个文件**
      （重新训练过模型的话，必须重跑第 1 步再综合）。

## 为什么 csim 是这一阶段唯一的验收标准

HLS 里最容易出错的两件事：**下标约定**（`w1[j*8+i]` 还是 `w1[i*3+j]`）和
**负数右移语义**（算术移位 vs 逻辑移位）。这两件事光看代码很难发现，
但只要让 Python 生成期望值、HLS 去比对，立刻暴露。

所以 `mlp_engine_tb.cpp` 不是"打印几个数看看"，而是**逐条断言**，
`csim_design` 返回非 0 就算失败，`script.tcl` 里也会 `exit 1`。

## 与方案书示例的两处差异（都有原因）

| 方案书写法 | 本工程写法 | 原因 |
|-----------|-----------|------|
| `void mlp_engine(..., ap_int<16> *mlp_out)` | `ap_int<16> mlp_engine(...)` 返回值 | 指针输出会多一个 `mlp_out_ap_vld` 端口，BD 接线更繁琐也更容易接错 |
| 输入直接用寄存器原始累加值 | 输入是右移后的三个特征（见 `lib/ai_video_regs.py`） | 定点输入必须落在 int16 内，且三个特征量级要相近，否则 Q8.8 权重会量化成 0 |

## 常见失败与处理

| 现象 | 原因 | 处理 |
|------|------|------|
| 大量 MISMATCH | `w1/w2` 下标约定与 Python 不同 | 对照 `mlp_common.predict_fixed_raw` 逐行核对 `mlp_engine.cpp` |
| 只有边界样本 MISMATCH | 输入的截断/饱和处理不同 | 检查 `X_LIMIT` 那三行 |
| `tv_mlp.h` 找不到 | 没先跑 `05_mlp_verify.ipynb` | 回去跑一次 |
| 综合报 `ap_int.h` 找不到 | HLS 工程没按 script.tcl 建 | 用 `vitis_hls -f script.tcl` / `vivado_hls -f script.tcl` |
