"""检查 HDL 读通道的 case 语句是否覆盖 registers.csv 里的所有可读地址。

用法：
    python3 check_hdl.py --csv registers.csv --hdl path/to/axis_video_proc.v

这是静态检查，不解析完整 Verilog；它对“case (addr) + 6'hXX”这种常见写法有效。
"""
import argparse
import csv
import re
import sys


def read_regs(path):
    regs = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            regs.append({
                "offset": int(row["offset"], 0),
                "name": row["name"].strip(),
                "access": row.get("access", "RW").strip().upper(),
            })
    return regs


def main():
    p = argparse.ArgumentParser(description="check HDL read-case offsets")
    p.add_argument("--csv", required=True)
    p.add_argument("--hdl", required=True)
    p.add_argument("--show", type=int, default=8, help="最多打印多少个缺失地址")
    args = p.parse_args()

    regs = [r for r in read_regs(args.csv) if "R" in r["access"]]
    text = open(args.hdl, encoding="utf-8", errors="ignore").read()

    missing = []
    for r in regs:
        # 6'h00 / 8'h00 / 16'h0000，允许前导 0
        pat = re.compile(r"\b\d+'h0*%X\b" % r["offset"], re.IGNORECASE)
        if not pat.search(text):
            missing.append(r)

    print("可读寄存器 %d 个，HDL 中发现 %d 个，缺失 %d 个"
          % (len(regs), len(regs) - len(missing), len(missing)))
    for r in missing[:args.show]:
        print("  MISSING 0x%02X %s" % (r["offset"], r["name"]))
    if len(missing) > args.show:
        print("  ... 还有 %d 个" % (len(missing) - args.show))

    if missing:
        print("FAIL: 地址表与 HDL 读通道不一致")
        return 1
    print("OK: 所有可读地址都在 HDL 中出现")
    return 0


if __name__ == "__main__":
    sys.exit(main())
