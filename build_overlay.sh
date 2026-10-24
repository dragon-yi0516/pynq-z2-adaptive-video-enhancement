#!/usr/bin/env bash
# =============================================================================
# 一条命令跑完一个硬件阶段（Ubuntu / Vivado 2024.2）
#
# 用法：
#   bash ai_video/build_overlay.sh 1          # 阶段 1
#   bash ai_video/build_overlay.sh 2          # 阶段 2（在阶段 1 的基础上继续）
#   bash ai_video/build_overlay.sh 3
#   bash ai_video/build_overlay.sh 6          # 需要先跑完 HLS
#   bash ai_video/build_overlay.sh 7
#   bash ai_video/build_overlay.sh 1 clean    # 先重建基础 BD 再跑阶段 1
#
# 它会自动：找到 bitstream 工程 -> (需要时)建基础 BD -> 打包 IP -> 插进 BD
#           -> 综合实现 -> 把 .bit/.hwh 拷到 bitstream/ 和 ai_video/overlay/
#
# 前提：vivado 命令在 PATH 里。没有就先执行
#   source /tools/Xilinx/Vivado/2024.2/settings64.sh
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

STAGE="${1:-}"
if [ -z "$STAGE" ]; then
    echo "用法: bash build_overlay.sh <1|2|3|6|7> [clean]"
    exit 2
fi
shift

# --- 2024.2：找不到 vivado 时自动 source settings64.sh，省得每次手动 source ---
VIVADO_SETTINGS="${VIVADO_SETTINGS:-/tools/Xilinx/Vivado/2024.2/settings64.sh}"
VITIS_HLS_SETTINGS="${VITIS_HLS_SETTINGS:-/tools/Xilinx/Vitis_HLS/2024.2/settings64.sh}"

if ! command -v vivado >/dev/null 2>&1 && [ -f "$VIVADO_SETTINGS" ]; then
    # shellcheck disable=SC1090
    source "$VIVADO_SETTINGS"
fi

if ! command -v vivado >/dev/null 2>&1; then
    echo "[ERROR] 找不到 vivado 命令。"
    echo "        先执行:  source /tools/Xilinx/Vivado/2024.2/settings64.sh"
    echo "        或者    export VIVADO_SETTINGS=/你的安装路径/settings64.sh"
    exit 1
fi

echo "[i] vivado  : $(command -v vivado)"
echo "[i] 版本    : $(vivado -version 2>/dev/null | head -n 1)"

mkdir -p "$HERE/logs"
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG="$HERE/logs/stage${STAGE}_${STAMP}.log"

echo "[i] 阶段      : $STAGE"
echo "[i] ai_video  : $HERE"
echo "[i] 日志      : $LOG"

if [ "$#" -gt 0 ]; then
    vivado -mode batch -nojournal -notrace -log "$LOG" \
        -source "$HERE/tools/stage_flow.tcl" -tclargs "$STAGE" "$@"
else
    vivado -mode batch -nojournal -notrace -log "$LOG" \
        -source "$HERE/tools/stage_flow.tcl" -tclargs "$STAGE"
fi

echo ""
echo "[i] 完成。产物在："
echo "    $HERE/../bitstream/cv_ov5640.bit  (及 .hwh)"
echo "    $HERE/overlay/cv_ov5640.bit       (及 .hwh)"
