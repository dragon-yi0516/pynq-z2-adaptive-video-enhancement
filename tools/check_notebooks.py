"""轻量 notebook 自检：结构是否符合 nbformat + Python 代码能不能解析。

写它的原因（真实踩过两次坑，记在这别再犯）：
  1. 有两个 notebook 的单元格写成了 "cell": "code"，而不是 "cell_type": "code"，
     Jupyter 7 打开时直接报「加载笔记本出错 / 出现了一个未知的错误」。
     而旧的检查用 c.get("cell_type") == "code" 判断，这俩单元格的 cell_type 是 None，
     于是被**整个跳过**了 —— 既没查结构，也没查语法，一直没发现。
  2. 所以现在明确要求：每个单元格必须有合法的 cell_type 和必需字段，
     并且所有代码格的 Python 语法必须通过。

用法：
    python tools/check_notebooks.py
"""
import ast
import glob
import json
import os
import sys

REQUIRED = {
    "code": ("execution_count", "metadata", "outputs", "source"),
    "markdown": ("metadata", "source"),
    "raw": ("metadata", "source"),
}


def check(path):
    try:
        nb = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        return ["JSON 解析失败: %s" % e]

    problems = []
    for k in ("nbformat", "nbformat_minor"):
        if k not in nb:
            problems.append("缺字段 %s" % k)

    cells = nb.get("cells")
    if not isinstance(cells, list):
        problems.append("没有 cells 数组")
        return problems

    for i, c in enumerate(cells):
        ct = c.get("cell_type")
        if ct not in REQUIRED:
            problems.append("cell %d: cell_type 非法（%r），keys=%s" % (i, ct, sorted(c)))
            continue
        for k in REQUIRED[ct]:
            if k not in c:
                problems.append("cell %d (%s): 缺字段 %s" % (i, ct, k))
        if ct == "code" and isinstance(c.get("source"), list):
            try:
                ast.parse("".join(c["source"]).replace("%matplotlib inline", ""))
            except SyntaxError as e:
                problems.append("cell %d: Python 语法错误 %s" % (i, e))
    return problems


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = sorted(glob.glob(os.path.join(root, "stage*", "*.ipynb"))
                   + glob.glob(os.path.join(root, "tools", "*.ipynb")))
    bad = 0
    for f in files:
        probs = check(f)
        tag = os.path.relpath(f, root)
        if probs:
            bad += 1
            print("FAIL %s" % tag)
            for p in probs:
                print("     %s" % p)
        else:
            print("ok   %s" % tag)
    print("")
    print("检查了 %d 个 notebook，问题文件 %d 个" % (len(files), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
