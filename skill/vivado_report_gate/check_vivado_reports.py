"""Parse Vivado timing/utilization summary reports into a pass/fail table.

Usage:
    python3 check_vivado_reports.py --timing timing.rpt --util util.rpt
    python3 check_vivado_reports.py ... --min-wns 0 --max-lut 50 --max-bram 60 --max-dsp 30
"""
import argparse
import os
import re
import sys


def _last_float(line):
    vals = re.findall(r"-?\d+(?:\.\d+)?", line)
    return float(vals[-1]) if vals else None


def parse_timing(path):
    text = open(path, encoding="utf-8", errors="ignore").read()
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if "WNS(ns)" in line and "TNS(ns)" in line:
            for candidate in lines[idx + 1:idx + 6]:
                row = re.match(
                    r"\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(\d+)\s+(\d+)\b",
                    candidate,
                )
                if row:
                    return float(row.group(1)), float(row.group(2)), int(row.group(3))
            break
    raise ValueError("找不到 WNS/TNS 摘要行；请确认是 report_timing_summary 文本报告")


def parse_util(path):
    text = open(path, encoding="utf-8", errors="ignore").read()
    labels = {
        "LUT": "Slice LUTs",
        "FF": "Slice Registers",
        "BRAM": "Block RAM Tile",
        "DSP": "DSPs",
    }
    out = {}
    for key, label in labels.items():
        found = None
        for line in text.splitlines():
            if label in line and "|" in line:
                found = _last_float(line)
                break
        if found is None:
            break
        out[key] = found
    if len(out) == len(labels):
        return out

    # report_utilization -hierarchical has used counts but no percentages.
    # Parse the top row and derive percentages from the target capacity.
    capacities = {
        "7z010": (17600, 35200, 60, 80),
        "7z020": (53200, 106400, 140, 220),
        "7z030": (78600, 157200, 265, 400),
        "7z045": (218600, 437200, 545, 900),
        "7z100": (277400, 554800, 755, 2020),
    }
    device_match = re.search(r"\|\s*Device\s*:\s*(\S+)", text)
    device = device_match.group(1).lower() if device_match else ""
    cap_key = next((key for key in capacities if key in device), None)
    if cap_key is None:
        raise ValueError("层次化 utilization 报告需要已知器件容量；当前器件: %s" % device)
    cap_lut, cap_ff, cap_bram, cap_dsp = capacities[cap_key]

    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        fields = [field.strip() for field in line.strip("|").split("|")]
        if len(fields) >= 10 and fields[1] == "(top)":
            try:
                total_lut = int(fields[2])
                ff = int(fields[6])
                bram36 = int(fields[7])
                bram18 = int(fields[8])
                dsp = int(fields[9])
            except ValueError:
                continue
            bram_tiles = bram36 + bram18 / 2.0
            return {
                "LUT": total_lut / cap_lut * 100.0,
                "FF": ff / cap_ff * 100.0,
                "BRAM": bram_tiles / cap_bram * 100.0,
                "DSP": dsp / cap_dsp * 100.0,
            }

    raise ValueError("找不到标准或层次化 utilization 表的顶层资源行: %s" % path)


def main():
    p = argparse.ArgumentParser(description="Vivado timing/utilization gate")
    p.add_argument("--timing", required=True)
    p.add_argument("--util", required=True)
    p.add_argument("--min-wns", type=float, default=0.0)
    p.add_argument("--max-lut", type=float, default=50.0)
    p.add_argument("--max-bram", type=float, default=60.0)
    p.add_argument("--max-dsp", type=float, default=30.0)
    args = p.parse_args()

    try:
        wns, tns, fail = parse_timing(args.timing)
        util = parse_util(args.util)
    except Exception as exc:
        print("ERROR:", exc)
        return 2

    rows = [
        ("WNS (ns)", wns, ">= %.2f" % args.min_wns, wns >= args.min_wns),
        ("TNS (ns)", tns, "<= 0", tns <= 0),
        ("Failing endpoints", fail, "= 0", fail == 0),
        ("LUT (%)", util["LUT"], "<= %.1f" % args.max_lut, util["LUT"] <= args.max_lut),
        ("FF (%)", util["FF"], "informational", True),
        ("BRAM (%)", util["BRAM"], "<= %.1f" % args.max_bram, util["BRAM"] <= args.max_bram),
        ("DSP (%)", util["DSP"], "<= %.1f" % args.max_dsp, util["DSP"] <= args.max_dsp),
    ]

    print("| Item | Value | Threshold | Result |")
    print("|---|---|---|---|")
    for name, val, threshold, ok in rows:
        print("| %s | %.3f | %s | %s |"
              % (name, val, threshold, "PASS" if ok else "FAIL"))

    bad = [name for name, _, _, ok in rows if not ok]
    if bad:
        print("FAIL:", ", ".join(bad))
        return 1
    print("PASS: timing/utilization gate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
