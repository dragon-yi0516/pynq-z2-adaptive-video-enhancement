#!/usr/bin/env bash
# 清理残留的 Python/Jupyter 进程，并打印 DMA/内存状态。
# 只在板子上运行；不会删除任何工程文件。
set -u

echo "== 残留 python/jupyter 进程 =="
ps -ef | grep -E "python|jupyter" | grep -v grep || true

echo
echo "== 尝试结束 auto_schedule / step5_compare =="
pkill -f "auto_schedule.py" 2>/dev/null || true
pkill -f "step5_compare.py" 2>/dev/null || true

echo
echo "== CMA / 内存 =="
grep -E "CmaTotal|CmaFree|MemFree" /proc/meminfo 2>/dev/null || true

echo
echo "如果仍然 Allocate failed，再考虑 sudo reboot。"
