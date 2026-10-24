"""Jupyter 版实时调度验证：一个场景一个 cell。

和 auto_schedule.py 用同一套规则：
  MLP -> 置信度门限 -> 四象限空间决策 -> 防抖/最小驻留
  -> 帧边界写 MODE_SEL -> 连续 PARAM

区别：每个 cell 只跑固定时长（默认 12 秒），跑完返回，
方便你一个场景一个场景地摆环境、看结果。
"""
import collections
import csv
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from lib import adaptive             # noqa: E402
import hard_pair_notebook as hp      # noqa: E402


SCENES = [
    (0, "uniform_dark", 0, (5, 35),
     "均匀暗场：灰卡/白墙/棋盘，目标 f_luma 10~30"),
    (1, "dark_window", 1, (5, 35),
     "暗场+亮窗/灯：房间仍暗，但让窗/灯进入画面；目标 f_luma 10~30"),
    (2, "uniform_normal", 2, (80, 110),
     "均匀正常光：灰卡/白墙/纹理卡，目标 f_luma 90~100"),
    (3, "normal_backlight", 1, (80, 110),
     "正常亮度+逆光：窗/灯进入画面，主体背光；目标 f_luma 90~100"),
]


def setup(skip_camera=False, display=False):
    """复用 hard_pair_notebook 的 overlay/摄像头/VDMA 初始化。"""
    return hp.setup(skip_camera=skip_camera, display=display)


def preview(regs):
    return hp.preview(regs)


def _save_rows(idx, rows):
    path = os.path.join(ROOT, "data", "live_scene%d.csv" % idx)
    header = ["t", "frame_cnt", "f_luma", "f_luma2", "f_grad",
              "q_tl", "q_tr", "q_bl", "q_br", "u",
              "mlp_raw", "decision", "mode", "param", "switched"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    print("已写", path, "（%d 行）" % len(rows))
    return path


def run_scene(regs, idx, duration=12.0, wait=8, debounce=6,
              min_hold=1.0, poll=0.02, param_step=2,
              u_hi=None, u_lo=None):
    """跑一个场景的实时调度，返回 summary dict。

    参数：
      duration : 回车后跑多少秒（默认 12）
      wait     : 回车后的倒计时（默认 8 秒，给你最后确认）
      debounce : 连续多少次同一个决策才切（默认 6）
      min_hold : 两次切换的最小间隔（默认 1.0 秒）
      poll     : 轮询间隔（默认 0.02 秒）
    """
    ridx, name, expected_label, band, hint = SCENES[idx]
    print("=" * 74)
    print("场景 %d：%s（期望 mode=%d）" % (ridx, name, expected_label))
    print("  " + hint)
    print("  目标 f_luma 带：%d~%d" % band)
    print("=" * 74)
    f0, q0, u0 = preview(regs)
    lo, hi = band
    if not (lo <= f0[0] <= hi):
        print("!! 当前 f_luma=%d 不在 %d~%d；先摆场景再跑本 cell。"
              % (f0[0], lo, hi))
        print("   如果确认要跑，直接再跑一次并忽略这条提示。")

    input("准备好后按回车开始实时调度（想准备多久都行；Ctrl+C 取消）...")
    for i in range(int(wait), 0, -1):
        print("\r    倒计时 %2d 秒……" % i, end="", flush=True)
        time.sleep(1)
    print("\r    开始调度！        ")

    t0 = time.time()
    frame0 = regs.frame_cnt()
    current_mode = regs.mode_sel()
    last_mlp = -1
    stable = 0
    last_switch_t = t0 - min_hold
    last_param = -1
    switches = 0
    overrides = 0
    holds = 0
    rejects = 0
    rows = []

    while (time.time() - t0) < duration:
        mlp_raw = regs.mlp_output()
        f = regs.mlp_features()
        q = regs.quads()
        u = adaptive.spatial_unevenness(q)
        mlp = int(mlp_raw)

        # 1) 置信度门限
        if not adaptive.is_confident(f, mlp):
            rejects += 1
            mlp = current_mode

        # 2) 四象限空间决策
        mode_sp, param_sp, why = adaptive.decide_spatial(
            f, q, mlp, u_hi, u_lo)
        if mode_sp is None:
            holds += 1
            decision = current_mode
            param_target = None
        else:
            decision = int(mode_sp)
            param_target = param_sp
            if decision != mlp:
                overrides += 1
                if overrides <= 5:
                    print("  空间覆盖：MLP=%d -> 模式=%d（%s）"
                          % (mlp, decision, why))
        mlp = decision

        # 3) 防抖
        if mlp == last_mlp:
            stable += 1
        else:
            last_mlp, stable = mlp, 1

        # 4) 连续 PARAM（每轮都跟，不等切换）
        if param_target is None:
            p_new, _ = adaptive.param_for(f, mlp)
        else:
            p_new = param_target
        if last_param < 0 or abs(p_new - last_param) >= param_step:
            regs.set_param(p_new)
            last_param = p_new

        # 5) 帧边界切换
        switched = 0
        if (stable >= debounce and mlp != current_mode
                and (time.time() - last_switch_t) >= min_hold):
            try:
                regs.wait_frame_boundary()
            except Exception as exc:
                print("  等帧边界失败：%s" % exc)
                stable = 0
            else:
                regs.set_mode(mlp)
                if param_target is not None:
                    regs.set_param(param_target)
                    last_param = param_target
                current_mode = mlp
                last_switch_t = time.time()
                switches += 1
                stable = 0
                switched = 1
                print("  切换模式 -> %d（t=%.1fs, FRAME_CNT=%d）"
                      % (current_mode, time.time() - t0, regs.frame_cnt()))

        rows.append([
            round(time.time() - t0, 3), regs.frame_cnt(),
            f[0], f[1], f[2], q[0], q[1], q[2], q[3], round(u, 4),
            int(mlp_raw), decision, current_mode, last_param, switched,
        ])
        time.sleep(poll)

    frame1 = regs.frame_cnt()
    dt = max(time.time() - t0, 1e-6)
    fps = (frame1 - frame0) / dt
    f1 = [r[2] for r in rows]
    us = [r[9] for r in rows]
    modes = collections.Counter(r[12] for r in rows)
    print()
    print("场景 %d 汇总：%.1f 秒，%d 帧（%.1f fps）"
          % (idx, dt, frame1 - frame0, fps))
    print("  模式分布: %s" % dict(sorted(modes.items())))
    print("  切换 %d 次，空间覆盖 %d 次，空间保持 %d 次，门限拒绝 %d 次"
          % (switches, overrides, holds, rejects))
    print("  f_luma=%.1f  u=%.3f  最终 MODE=%d  PARAM=%d"
          % (sum(f1) / len(f1), sum(us) / len(us),
             regs.mode_sel(), regs.param()))
    _save_rows(idx, rows)

    return {
        "scene": idx,
        "name": name,
        "seconds": dt,
        "frames": frame1 - frame0,
        "fps": fps,
        "switches": switches,
        "overrides": overrides,
        "holds": holds,
        "rejects": rejects,
        "final_mode": regs.mode_sel(),
        "final_param": regs.param(),
        "f_luma_mean": sum(f1) / len(f1),
        "u_mean": sum(us) / len(us),
    }


def summary_all():
    """读 data/live_scene*.csv，打印一张汇总表。"""
    import glob
    files = sorted(glob.glob(os.path.join(ROOT, "data", "live_scene*.csv")))
    if not files:
        print("还没有 live_scene*.csv")
        return []
    print("| scene | n | f_luma | u | 最终 mode | 切换 | 空间覆盖 | 空间保持 |")
    print("|---|---|---|---|---|---|---|---|")
    out = []
    for path in files:
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            continue
        n = len(rows)
        f_luma = sum(float(r["f_luma"]) for r in rows) / n
        u = sum(float(r["u"]) for r in rows) / n
        final_mode = rows[-1]["mode"]
        switches = sum(int(r["switched"]) for r in rows)
        # 空间覆盖/保持没有逐行字段，用 decision 与 mlp_raw 的关系估算
        overrides = sum(1 for r in rows
                        if r["decision"] != "-1" and r["decision"] != r["mlp_raw"])
        holds = sum(1 for r in rows if r["decision"] == "-1")
        print("| %s | %d | %.1f | %.3f | %s | %d | %d | %d |"
              % (os.path.basename(path), n, f_luma, u,
                 final_mode, switches, overrides, holds))
        out.append({"file": path, "n": n, "f_luma": f_luma, "u": u,
                    "final_mode": final_mode, "switches": switches,
                    "overrides": overrides, "holds": holds})
    return out


def cleanup(ol, vdma0, vdma1):
    return hp.cleanup(ol, vdma0, vdma1)
