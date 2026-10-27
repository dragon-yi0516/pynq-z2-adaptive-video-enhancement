"""把整个工程整理成一份可以直接交出去的 release/ 目录。

跑法：
    cd <ai_video>
    python stage10_release/export_release.py
    python stage10_release/export_release.py --out /tmp/ai_video_release

产物结构（就是方案书阶段 10 要求的那套）：

    release/
      README.md
      overlay/     cv_ov5640.bit, cv_ov5640.hwh
      notebooks/   00..09 全部 notebook（带阶段前缀，顺序一目了然）
      weights/     mlp_weights.h
      data/        features.csv（或示范数据）+ baseline.json
      hw/          最终的 HDL / TCL（别人能重建硬件）
      docs/        设计说明、寄存器表、阶段指南

为什么要有这个脚本而不是手工拷：
  * 手工拷最容易漏东西（尤其是 .hwh —— 少了它 PYNQ 就加载不了 overlay）。
  * 脚本最后会做一次**完整性检查**，缺任何一个必需文件都会报错并告诉你缺什么。
  * 自动算出每个文件的 SHA256 写进 README，交付物可追溯。
"""
import argparse
import datetime
import hashlib
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 哪个阶段目录里有哪些 notebook（按方案书的编号顺序）
#   元组 = (阶段目录, 源文件名, 导出后的文件名)
#   05 那一步有两个用途不同的 notebook（一个在 PC 的 HLS 侧、一个在板上），
#   导出时加 a/b 后缀，避免互相覆盖。
NOTEBOOKS = [
    ("stage00_baseline", "00_baseline_check.ipynb", "00_baseline_check.ipynb"),
    ("stage01_axis_passthrough", "01_axil_regs.ipynb", "01_axil_regs.ipynb"),
    ("stage03_feature_extract", "02_feature_collect.ipynb", "02_feature_collect.ipynb"),
    ("stage04_mlp_train", "03_mlp_train.ipynb", "03_mlp_train.ipynb"),
    ("stage04_mlp_train", "04_mlp_quant_export.ipynb", "04_mlp_quant_export.ipynb"),
    ("stage05_mlp_hls", "05_mlp_verify.ipynb", "05a_mlp_hls_verify.ipynb"),
    ("stage06_mlp_integrate", "05_mlp_verify.ipynb", "05b_mlp_board_verify.ipynb"),
    ("stage07_reconfig_array", "06_mode_manual.ipynb", "06_mode_manual.ipynb"),
    ("stage08_auto_schedule", "07_auto_schedule.ipynb", "07_auto_schedule.ipynb"),
    ("stage09_perf_test", "08_perf_test.ipynb", "08_perf_test.ipynb"),
    ("stage11_demo", "09_demo.ipynb", "09_demo.ipynb"),
    ("stage12_adaptive", "12_verify_adaptive.ipynb", "10_adaptive_verify.ipynb"),
    ("stage13_split", "13_verify_split.ipynb", "11_split_verify.ipynb"),
]

# 最终硬件对应的源文件（stage12 是含「连续参数 + 四象限统计 + MLP」的最终版）
HW_FILES = [
    ("stage12_adaptive/hdl/axis_video_proc.v", "axis_video_proc.v"),
    ("stage12_adaptive/tcl/package_ip.tcl", "package_ip.tcl"),
    ("stage12_adaptive/tcl/insert_adaptive.tcl", "insert_adaptive.tcl"),
    # 最终版 bitstream 能收敛，靠的就是这条约束 —— 必须跟着源码一起交付，
    # 否则别人重建出来的又会掉回 WNS -4.0（async_default 端点违例）。
    ("stage12_adaptive/tcl/timing_waiver.xdc", "timing_waiver.xdc"),
    # 重建流程本身（一键脚本 + 它调用的两个 tcl）
    ("build_overlay.sh", "build_overlay.sh"),
    ("tools/stage_flow.tcl", "stage_flow.tcl"),
    ("tools/build_and_copy.tcl", "build_and_copy.tcl"),
    ("tools/insert_axis_video_proc_common.tcl", "insert_axis_video_proc_common.tcl"),
    ("tools/package_ip_common.tcl", "package_ip_common.tcl"),
    # 上位机侧：连续自适应策略 + 盒子模式曝光控制 + 寄存器封装
    ("lib/adaptive.py", "adaptive.py"),
    ("lib/exposure.py", "exposure.py"),
    ("lib/ai_video_regs.py", "ai_video_regs.py"),
    # HLS 推理引擎
    ("stage05_mlp_hls/src/mlp_engine.cpp", "mlp_engine.cpp"),
    ("stage05_mlp_hls/src/mlp_engine.h", "mlp_engine.h"),
    ("stage05_mlp_hls/src/mlp_engine_tb.cpp", "mlp_engine_tb.cpp"),
    ("stage05_mlp_hls/hls/script.tcl", "hls_script.tcl"),
]

# 可选：时序 / 资源报告。路径指向 <ai_video>/../bitstream 下的 Vivado 输出，
# 有就一起交付，没有只是跳过、不算缺件（缺件检查只管 HW_FILES）。
OPTIONAL_FILES = [
    ("../bitstream/cv_ov5640/cv_ov5640.runs/impl_1/"
     "cv_ov5640_wrapper_timing_summary_routed.rpt", "timing_summary_routed.rpt"),
    ("../bitstream/cv_ov5640/cv_ov5640.runs/impl_1/"
     "cv_ov5640_wrapper_utilization_placed.rpt", "utilization_placed.rpt"),
]

DOC_FILES = [
    "README.md",
    "docs/01_register_map.md",
    "docs/02_why_this_design.md",
    "docs/03_stage_guide.md",
    # 答辩当天照着做的清单（打印出来用）
    "stage11_demo/demo_checklist.md",
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "release"))
    ap.add_argument("--allow-missing-overlay", action="store_true",
                    help="即使 overlay/ 里没有 .bit/.hwh 也继续（只用于自测脚本）")
    args = ap.parse_args()
    out = os.path.abspath(args.out)

    print("== 导出 release ==")
    print("  源:", ROOT)
    print("  目标:", out)

    missing_hard = []
    copied = []

    # ---- overlay -----------------------------------------------------------
    for name in ("cv_ov5640.bit", "cv_ov5640.hwh"):
        src = os.path.join(ROOT, "overlay", name)
        if os.path.exists(src):
            copy(src, os.path.join(out, "overlay", name))
            copied.append(("overlay/" + name, src))
        else:
            missing_hard.append("overlay/" + name)

    # ---- weights / data ----------------------------------------------------
    for name in ("mlp_weights.h",):
        src = os.path.join(ROOT, "weights", name)
        if os.path.exists(src):
            copy(src, os.path.join(out, "weights", name))
            copied.append(("weights/" + name, src))
        else:
            missing_hard.append("weights/" + name)

    for name in ("features.csv", "features_demo.csv", "baseline.json", "mlp_float.npz"):
        src = os.path.join(ROOT, "data", name)
        if os.path.exists(src):
            copy(src, os.path.join(out, "data", name))
            copied.append(("data/" + name, src))

    # ---- notebooks --------------------------------------------------------
    for stage, nb, dst_name in NOTEBOOKS:
        src = os.path.join(ROOT, stage, nb)
        if os.path.exists(src):
            copy(src, os.path.join(out, "notebooks", dst_name))
            copied.append(("notebooks/" + dst_name, src))
        else:
            print("  警告：找不到 notebook %s/%s（跳过）" % (stage, nb))

    # ---- 硬件源码 ---------------------------------------------------------
    for rel, dst_name in HW_FILES:
        src = os.path.join(ROOT, rel)
        if os.path.exists(src):
            copy(src, os.path.join(out, "hw", dst_name))
            copied.append(("hw/" + dst_name, src))
        else:
            missing_hard.append("hw/" + dst_name)

    # ---- 可选报告 ---------------------------------------------------------
    for rel, dst_name in OPTIONAL_FILES:
        src = os.path.join(ROOT, rel)
        if os.path.exists(src):
            copy(src, os.path.join(out, "hw", dst_name))
            copied.append(("hw/" + dst_name, src))
        else:
            print("  提示：没有 %s（跳过，不影响交付完整性）" % dst_name)

    # ---- 文档 -------------------------------------------------------------
    for rel in DOC_FILES:
        src = os.path.join(ROOT, rel)
        if os.path.exists(src):
            copy(src, os.path.join(out, "docs", os.path.basename(rel)))
            copied.append(("docs/" + os.path.basename(rel), src))

    # ---- README -----------------------------------------------------------
    tpl = os.path.join(HERE, "readme_template.md")
    with open(tpl, encoding="utf-8") as f:
        text = f.read()

    used_real = os.path.exists(os.path.join(ROOT, "data", "features.csv"))
    manifest = "\n".join(
        "| `%s` | `%s` |" % (dst, sha256(src)[:16]) for dst, src in sorted(copied)
    )
    text = text.replace("{{DATE}}", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    text = text.replace("{{DATA_SOURCE}}", "真机采集 features.csv" if used_real else "示范数据 features_demo.csv（非真机）")
    text = text.replace("{{MANIFEST}}", manifest)
    with open(os.path.join(out, "README.md"), "w", encoding="utf-8") as f:
        f.write(text)

    print("\n已导出 %d 个文件到 %s" % (len(copied) + 1, out))
    for dst, _ in sorted(copied):
        print("   ", dst)
    print("    README.md")

    if missing_hard and not args.allow_missing_overlay:
        print("\n!! 缺少必需文件，release 不完整：")
        for m in missing_hard:
            print("   -", m)
        print("   overlay/ 里的 .bit/.hwh 请从 Vivado 那边拷过来（见 README.md 第 2 节）")
        return 1

    print("\nrelease 完整性检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
