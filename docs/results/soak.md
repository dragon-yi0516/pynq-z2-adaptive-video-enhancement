# 1 小时 soak（2026-10-20 实测）

## 方式 A：Jupyter（推荐）

打开 `tools/soak_test.ipynb`：

1. setup（`display=True` 可同时看 HDMI）；
2. preview；
3. 跑 `soak.run_soak(regs, duration=3600, heartbeat=60)`；
4. 跑 `soak.summary(result)`。

会写 `soak.log` 和 `data/soak.csv`，每 60 秒一条心跳和一条 CSV 记录。

## 方式 B：终端

```bash
sudo -E env PATH="$PATH" python3 stage08_auto_schedule/auto_schedule.py \
  --adaptive --duration 3600 --heartbeat 60 --min-hold 2.0 \
  --log soak.log
```

运行期间可以缓慢改变场景；不要动 HDL/overlay。

## 实测结果

| 项 | 实测 |
|---|---|
| 运行时长 | **3600 s（1 小时）** |
| 总处理帧数 | **107,137** |
| 平均 FPS | **29.76** |
| 模式切换 | **3 次** |
| 空间覆盖（轮询计数） | 64,412 |
| 空间保持（轮询计数） | 13 |
| 门限拒绝（轮询计数） | 63,390 |
| 最终 mode / PARAM | **1 / 138** |
| 温度 | 未采集（镜像没有 thermal zone） |
| 卡死 / 花屏 / Allocate failed / Traceback | **均未记录** |

## 关于 CSV 的最后一行

`data/soak.csv` 的 `frame_cnt` 是**绝对帧计数**，不是本次运行的增量。

- CSV 最后一行：`t=3540, frame_cnt=106290`
- `soak.log` 最终总结：`t=3600, frames=107137`
- 其中 `107137` 是 `frame1 - frame0` 的**总处理帧增量**

因此不能直接用 `107137 - 106290 = 847` 当作最后一分钟增量。按启动计数约 938
换算，最后 60 秒的绝对计数增加约 1,785～1,786 帧，对应约 29.76～29.77 fps，
与前面各分钟一致。

## 结论

> 系统在 stage13（0x0001020D）上连续运行 3600 s，共处理 107,137 帧，
> 平均 29.76 fps；全程未记录卡死、花屏、Allocate failed、Traceback 或停流。
> 运行中发生 3 次模式切换，最终 mode 1 / PARAM 138。温度因镜像无 thermal zone 未采集。

日志中 `overrides/rejects` 是轮询计数，不是帧数，也不代表振荡。