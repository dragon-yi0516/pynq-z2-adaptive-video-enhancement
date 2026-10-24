# axil_register_contract

## 适用场景

任何带 AXI-Lite 寄存器的自定义 IP：

* 寄存器地址/位宽在 HDL、Python、文档三处各写一套，改一处忘一处；
* `VERSION` 读回 0，或者某个新寄存器永远读不到；
* 想给寄存器表自动生成 Python 封装、Markdown 表和 HDL 一致性检查。

## 使用方法

1. 把寄存器表写成 `registers.csv`：

```csv
offset,name,access,width,description
0x00,MLP_OUTPUT,R,32,分类结果
0x04,MODE_SEL,RW,32,模式选择
0x0C,VERSION,R,32,版本
```

2. 生成 Python 封装和 Markdown：

```bash
python3 gen_host.py --csv registers.csv --out regs_gen.py --md regs.md
```

3. 检查 HDL 读通道是否覆盖了所有可读地址：

```bash
python3 check_hdl.py --csv registers.csv --hdl ../../stage07_reconfig_array/hdl/axis_video_proc.v
```

## 失效条件

* HDL 的地址译码不是 `case (addr)` 形式（例如用 if/else 或函数）；
* 地址宽度不是常见的 `6'h`/`8'h`/`16'h` 写法；
* 寄存器是“写-only 但读回常量”或“地址由参数拼接”，静态检查会误报/漏报。

## 已验证效果

在本项目上：

* 用 `docs/01_register_map.md` 的偏移生成 Python 常量；
* `check_hdl.py` 抓到了 `PARAM` 读地址写成 `6'h0D`（应为 `6'h34`）这一类错误；
* 生成的头文件/封装与手写 `lib/ai_video_regs.py` 的偏移一致。

## 提炼来源

2026-10-08 的 stage12 修订 02：`PARAM` 写通道用 `aw_addr[5:2]`（字索引）是对的，
读通道 `reg_read` 却把 `0x34` 写成 `6'h0D`，于是参数写得进去、读回恒为 0。
这个 bug 靠人眼很难发现，用“寄存器表 → HDL 地址扫描”一遍就能抓出来。

## 边界

这是静态契约检查，不是形式验证；它保证“地址出现了”，
不保证读写语义、位宽、复位值正确。后者仍要靠 testbench / 板上读回。
