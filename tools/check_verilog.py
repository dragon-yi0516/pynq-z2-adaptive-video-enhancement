"""轻量 Verilog 自检：括号、begin/end、case/endcase、function/endfunction 是否配对。

不是完整的语法分析器，但能抓住「少一个括号」这类最常见的低级错误。
写它的原因：stage07 的 HDL 少了一个右括号，一直到 Vivado 打包时才报
[HDL 9-806] Syntax error，白等一次综合。以后改完 HDL 先跑一遍这个。

用法：
    python tools/check_verilog.py
（默认扫描本工程里所有的 axis_video_proc.v）
"""
import glob
import os
import re
import sys


def strip_comments(src):
    """去掉 // 和 /* */ 注释、保留字符串字面量，避免注释里的括号干扰计数。"""
    out = []
    i = 0
    n = len(src)
    while i < n:
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif src[i] == '"':
            j = i + 1
            while j < n and src[j] != '"':
                if src[j] == "\\":
                    j += 1
                j += 1
            out.append(src[i:j + 1])
            i = j + 1
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


def check(path):
    src = strip_comments(open(path, encoding="utf-8").read())
    problems = []
    for open_c, close_c in (("(", ")"), ("[", "]"), ("{", "}")):
        a, b = src.count(open_c), src.count(close_c)
        if a != b:
            problems.append("%s=%d  %s=%d" % (open_c, a, close_c, b))
    for kw, endkw in (("begin", "end"), ("case", "endcase"),
                      ("function", "endfunction"), ("module", "endmodule"),
                      ("generate", "endgenerate")):
        a = len(re.findall(r"\b%s\b" % kw, src))
        b = len(re.findall(r"\b%s\b" % endkw, src))
        if a != b:
            problems.append("%s=%d  %s=%d" % (kw, a, endkw, b))
    return problems


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = sorted(glob.glob(os.path.join(root, "stage*", "hdl", "*.v")))
    files += sorted(glob.glob(os.path.join(root, "stage*", "hl*", "src", "*.cpp")))
    bad = 0
    for f in files:
        if f.endswith(".cpp"):
            continue                      # C++ 用 gcc 编译，不用这个检查
        probs = check(f)
        tag = os.path.relpath(f, root)
        if probs:
            bad += 1
            print("FAIL %-46s  %s" % (tag, "; ".join(probs)))
        else:
            print("ok   %s" % tag)
    print("")
    print("检查了 %d 个 Verilog 文件，问题文件 %d 个" % (len([f for f in files if f.endswith('.v')]), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
