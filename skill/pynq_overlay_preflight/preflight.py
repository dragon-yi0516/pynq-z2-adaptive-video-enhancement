"""PYNQ overlay 上板前检查：IP 清单 / VERSION / VDMA 残留。

依赖：pynq（只在板子上有）。PC 上可以 `python3 -m py_compile preflight.py`
检查语法，但运行需要 PYNQ 环境。
"""
import argparse
import sys


def parse_args():
    p = argparse.ArgumentParser(description="PYNQ overlay preflight")
    p.add_argument("--bit", required=True, help="overlay .bit 路径")
    p.add_argument("--ip", action="append", default=[],
                   help="期望存在的 IP 名，可重复")
    p.add_argument("--version-ip", default="",
                   help="读 VERSION（偏移 0x0C）的 IP 名")
    p.add_argument("--expect-version", type=lambda s: int(s, 0), default=None,
                   help="期望的 VERSION，例如 0x0001020D")
    p.add_argument("--stop-vdma", action="store_true",
                   help="尝试停止所有 VDMA 的读写通道")
    return p.parse_args()


def stop_vdma(ol):
    stopped = []
    for name in sorted(ol.ip_dict):
        if "vdma" not in name.lower():
            continue
        ip = getattr(ol, name)
        for ch_name in ("writechannel", "readchannel"):
            ch = getattr(ip, ch_name, None)
            if ch is None:
                continue
            try:
                if ch.running:
                    ch.stop()
                    stopped.append("%s.%s" % (name, ch_name))
            except Exception as exc:
                print("  [warn] %s.%s stop: %s" % (name, ch_name, exc))
    return stopped


def main():
    args = parse_args()
    try:
        from pynq import Overlay
    except Exception as exc:
        print("需要 PYNQ 环境：%s" % exc)
        return 2

    print("加载 overlay:", args.bit)
    ol = Overlay(args.bit)
    ips = sorted(ol.ip_dict.keys())
    print("IP 清单 (%d): %s" % (len(ips), ", ".join(ips)))

    missing = [n for n in args.ip if n not in ol.ip_dict]
    if missing:
        print("FAIL: 缺少 IP %s" % missing)
        return 1
    if args.ip:
        print("OK: 期望的 IP 都在")

    if args.version_ip:
        if args.version_ip not in ol.ip_dict:
            print("FAIL: 找不到 --version-ip %s" % args.version_ip)
            return 1
        ip = getattr(ol, args.version_ip)
        try:
            v = int(ip.read(0x0C)) & 0xFFFFFFFF
        except Exception as exc:
            print("FAIL: 读 %s VERSION(0x0C) 失败：%s" % (args.version_ip, exc))
            return 1
        print("VERSION = 0x%08X" % v)
        if args.expect_version is not None and v != args.expect_version:
            print("FAIL: 期望 0x%08X，实际 0x%08X" % (args.expect_version, v))
            return 1
        print("OK: VERSION 匹配")

    if args.stop_vdma:
        stopped = stop_vdma(ol)
        print("已停止 VDMA 通道: %s" % (stopped or "无（本来就没在跑）"))

    print("PREFLIGHT OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
