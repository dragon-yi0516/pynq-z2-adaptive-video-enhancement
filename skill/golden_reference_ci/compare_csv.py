"""Compare a golden-reference CSV with an implementation CSV.

用法：
    python3 compare_csv.py --expected expected.csv --actual actual.csv --key case
    python3 compare_csv.py ... --max-mismatch 1   # 允许 1 条已知差异

退出码：0 = 差异数 <= max_mismatch；1 = 超过；2 = 文件/列错误。
"""
import argparse
import csv
import sys


def load(path, key, col):
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if key not in (reader.fieldnames or []):
            raise ValueError("%s 缺少 key 列 %s" % (path, key))
        if col not in (reader.fieldnames or []):
            raise ValueError("%s 缺少比较列 %s" % (path, col))
        for row in reader:
            out[row[key]] = row[col].strip()
    return out


def main():
    p = argparse.ArgumentParser(description="golden reference CSV diff")
    p.add_argument("--expected", required=True)
    p.add_argument("--actual", required=True)
    p.add_argument("--key", default="case")
    p.add_argument("--expected-col", default="expected")
    p.add_argument("--actual-col", default="actual")
    p.add_argument("--max-mismatch", type=int, default=0)
    p.add_argument("--show", type=int, default=10)
    args = p.parse_args()

    try:
        exp = load(args.expected, args.key, args.expected_col)
        act = load(args.actual, args.key, args.actual_col)
    except Exception as exc:
        print("ERROR:", exc)
        return 2

    missing = sorted(set(exp) - set(act))
    extra = sorted(set(act) - set(exp))
    common = sorted(set(exp) & set(act), key=lambda x: (len(x), x))
    bad = [(k, exp[k], act[k]) for k in common if exp[k] != act[k]]

    print("expected: %d, actual: %d, common: %d" % (len(exp), len(act), len(common)))
    if missing:
        print("MISSING in actual: %s" % missing[:args.show])
    if extra:
        print("EXTRA in actual: %s" % extra[:args.show])
    print("mismatches: %d" % len(bad))
    for k, e, a in bad[:args.show]:
        print("  %s: expected=%s actual=%s" % (k, e, a))
    if len(bad) > args.show:
        print("  ... %d more" % (len(bad) - args.show))

    if not common:
        print("FAIL: 没有可比较的 key")
        return 1
    if missing or extra:
        print("FAIL: key 集合不一致")
        return 1
    if len(bad) > args.max_mismatch:
        print("FAIL: 差异超过 max-mismatch=%d" % args.max_mismatch)
        return 1
    print("OK: %d/%d 一致（允许差异 %d）"
          % (len(common) - len(bad), len(common), args.max_mismatch))
    return 0


if __name__ == "__main__":
    sys.exit(main())
