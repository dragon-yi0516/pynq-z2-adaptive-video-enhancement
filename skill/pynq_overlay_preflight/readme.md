# pynq_overlay_preflight

## 适用场景

任何 PYNQ overlay 上板前的第一分钟检查：

* 板上加载的是不是最新 `.bit`；
* overlay 里有没有你期待的 IP；
* `VERSION` 寄存器是不是你以为的那一版；
* VDMA 通道有没有残留、是否还在跑；
* 出现 `Allocate failed: 4294967295` 时先做什么。

## 使用方法

```bash
python3 preflight.py --bit /home/xilinx/overlay/cv_ov5640.bit \
  --ip axis_video_proc_0 --ip axi_vdma_0 \
  --version-ip axis_video_proc_0 --expect-version 0x0001020D \
  --stop-vdma
```

参数：

| 参数 | 作用 |
|---|---|
| `--bit` | overlay 路径（必填） |
| `--ip` | 期望存在的 IP 名，可重复 |
| `--version-ip` | 要读 `VERSION`（偏移 0x0C）的 IP |
| `--expect-version` | 期望值，可用 `0x` 前缀 |
| `--stop-vdma` | 尝试停止所有 VDMA 的读写通道 |

## 失效条件

* IP 的 `VERSION` 不在偏移 `0x0C`（本脚本按这个约定写）；
* 你的 VDMA IP 名不含 `vdma`，或驱动不是 PYNQ 的 `AxiVDMA`；
* overlay 需要额外时钟/电源配置才能加载。

## 已验证效果

在本项目 PYNQ-Z2 + `cv_ov5640.bit` 上：

* 能列出 `axis_video_proc_0`、`axi_vdma_0/1`、`v_demosaic_0` 等 IP；
* 能读回 `VERSION=0x0001020D`（stage13）；
* `--stop-vdma` 后重新加载 overlay 不再报 `Allocate failed`。

## 提炼来源

* 2026-10-11：训练完新权重但忘了重出 bit，板上一直跑旧模型；
* 2026-10-12：多次加载 overlay 后 VDMA 缓冲没释放，出现
  `Allocate failed: 4294967295`；
* 2026-10-13：`VERSION` 读回 stage12/13 才能确认 `PARAM`/四象限寄存器存在。

## 边界

这只是一个“上板前 1 分钟”的检查，不替代完整的驱动初始化；
它不会帮你配置摄像头、VDMA 地址或中断。
