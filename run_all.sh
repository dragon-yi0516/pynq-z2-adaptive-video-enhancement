#!/usr/bin/env bash
# 一条命令跑一类检查。所有路径都相对本文件，不依赖当前目录。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

case "${1:-help}" in
  test)
    python3 lib/test_regs.py
    python3 lib/test_hwh.py
    python3 lib/test_spatial.py
    tmp="$(mktemp)"
    python3 tools/offline_check.py --weights "$tmp"
    rm -f "$tmp"
    echo "[OK] offline tests passed"
    ;;
  data)
    python3 tools/check_features.py
    ;;
  eval)
    python3 tools/eval_rounds.py
    if [ -f data/hard_pairs.csv ]; then
      python3 tools/eval_spatial.py --csv data/hard_pairs.csv
      python3 tools/eval_holdout.py --csv data/hard_pairs.csv
    else
      echo "[skip] data/hard_pairs.csv not found; run tools/collect_hard_pairs.py on the board"
    fi
    if [ -f data/real_scene.csv ]; then
      python3 tools/eval_holdout.py --csv data/real_scene.csv
    fi
    ;;
  build)
    bash build_overlay.sh 13
    ;;
  release)
    python3 stage10_release/export_release.py
    ;;
  *)
    echo "usage: $0 {test|data|eval|build|release}"
    exit 1
    ;;
esac
