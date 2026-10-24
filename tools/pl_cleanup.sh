#!/bin/bash
# PL / XRT 清理助手 —— "跑几次就不行"的时候先用它，别急着重启板子。
#
# 它只做三件只读的事 + 一件事有点破坏性（但只针对本项目那一个脚本模式）：
#   1) 列出并杀掉**残留的 tools/step5_compare.py 进程**
#      （这类进程如果被 SIGKILL，手里那几十 MB 的 DMA 缓冲就不会被正常释放）
#   2) 打印内存 / CMA / XRT 驱动日志（判断到底是"连续内存不够"还是"驱动脏了"）
#   3) 打印接下来在 Jupyter 里该敲什么
#
# 用法（在板子上，任意目录）：
#     bash tools/pl_cleanup.sh              # 需要 root，脚本会自己 sudo
#     bash tools/pl_cleanup.sh --dry-run    # 只看不杀
#
# ⚠️ 它**不会**碰 Jupyter 内核：匹配模式只有 "step5_compare\.py"。
#    千万别自己在终端敲 `pkill -f python3` / `pkill -f jupyter` —— 那会把内核一起杀掉。
set -u

DRY=0
for a in "$@"; do
    case "$a" in
        --dry-run|-n) DRY=1 ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "未知参数: $a"; exit 2 ;;
    esac
done

if [ "$(id -u)" -ne 0 ]; then
    exec sudo -E bash "$0" "$@"
fi

echo "=================================================="
echo " PL / XRT 清理助手"
echo "=================================================="

echo
echo "--- 1) 残留的采集脚本进程 ---"
if pgrep -af "step5_compare\.py" >/dev/null 2>&1; then
    pgrep -af "step5_compare\.py" | sed 's/^/    /'
    if [ "$DRY" -eq 1 ]; then
        echo "    (--dry-run：不杀)"
    else
        pkill -9 -f "step5_compare\.py" && echo "    -> 已杀掉（它们手里的 DMA 缓冲由驱动回收）"
    fi
else
    echo "    没有残留（好）"
fi

echo
echo "--- 1.5) 还开着的 Jupyter 内核（**多半就是这个占着缓冲**）---"
KERNELS=$(pgrep -af "ipykernel" 2>/dev/null || true)
if [ -n "$KERNELS" ]; then
    echo "$KERNELS" | sed 's/^/    /'
    echo "    每个内核都自己占着一份 DMA 缓冲。用不到的就去 Jupyter 里点它 -> Shut Down Kernel；"
    echo "    留着当前这一个，Restart Kernel 之后从上往下重跑。"
else
    echo "    没有别的内核在跑"
fi

echo
echo "--- 2) 内存 / CMA ---"
free -m | sed 's/^/    /'
if grep -qi '^Cma' /proc/meminfo; then
    grep -i '^Cma' /proc/meminfo | sed 's/^/    /'
else
    echo "    （这个内核没有 CMA 字段 —— PYNQ-Z2 的 XRT 走的是自己的 buffer 池）"
fi

echo
echo "--- 3) XRT / 驱动最近日志（有没有 allocation 相关的报错）---"
dmesg 2>/dev/null | tail -20 | sed 's/^/    /' || echo "    （读不到 dmesg，跳过）"

echo
echo "--- 4) 接下来在 Jupyter 里做这些 ---"
cat <<'EOF'
     1) 关掉上面列出、用不到的 Jupyter 内核（Shut Down Kernel）；
     2) 当前这个 notebook：Kernel -> Restart Kernel，然后从上往下重跑；
     3) 还报 Allocate failed -> sudo reboot（约 40 秒）。

   判据：
     * 关掉别的内核 + Restart 之后能跑通 -> 就是缓冲被别的内核占着，以后别同时开一堆 notebook；
     * 还报 Allocate failed              -> 驱动层脏了，reboot；
     * 采集类 notebook 报 -11            -> 那是两个进程抢 PL，不是内存问题，看 demo_checklist 第 8.5 节。

   ⚠ 别再指望 ol.free() / s5.release() 救场：实测 free 完之后再分配更容易失败。
EOF
echo
echo "=================================================="
