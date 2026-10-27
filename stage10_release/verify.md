# 阶段 10 验收清单：整理开源

对应方案书：阶段 10「Jupyter 导出开源与 Skill」。

## 步骤

```bash
cd <ai_video>
python stage10_release/export_release.py
```

## 必须满足（缺一不可）

- 终端最后打印 `release 完整性检查通过`。
  （如果打印“缺少必需文件”，按提示把 `.bit/.hwh` 或 `weights/mlp_weights.h` 补上。）
- `release/` 下六个子目录齐全：`overlay/ notebooks/ weights/ data/ hw/ docs/`。
- `release/notebooks/` 里 00~11 共 **13** 个 notebook，编号连续
      （00~09 是各阶段，10 = 阶段 12 连续自适应验证，11 = 阶段 13 分屏验证）。
- `release/README.md` 里的文件清单表格有 SHA256。
- **别人拿到 release/ 后**：拷到板子、按 README 打开 00 → 09，能跑通。

## 为什么必须自动导出 + 校验

交付物最怕两件事：

1. **漏文件**：尤其 `.hwh`。少了它 PYNQ 加载 overlay 会直接报错，
   而现象是“找不到 IP”，很容易误判成 HDL 问题，白白浪费一天。
2. **版本错乱**：`weights/mlp_weights.h` 必须是**当前 bitstream 里那份**权重，
   否则会出现“笔记本算得对、板子结果不一样”。

`export_release.py` 会一次性把必需文件列表核对一遍，并给出每个文件的 SHA256，
别人拿到后可以逐字节比对。

## 常见失败与处理

| 现象 | 原因 | 处理 |
|------|------|------|
| `missing overlay/cv_ov5640.bit` | 还没把 Vivado 产物拷进 `overlay/` | 见根 `README.md` 第 2 节 |
| `missing weights/mlp_weights.h` | 没跑阶段 4 | 跑 `tools/offline_check.py` 或 04 notebook |
| 05 有两个 notebook | 阶段 5（PC 侧 HLS 验证）与阶段 6（板上验证）同名 | 正常。导出时自动改名为 `05a_mlp_hls_verify.ipynb` 与 `05b_mlp_board_verify.ipynb`，不会互相覆盖 |
