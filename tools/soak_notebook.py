"""Jupyter 版 1 小时 soak test。

和 auto_schedule.py 用同一套规则：
  MLP -> 置信度门限 -> 四象限 -> 防抖/最小驻留
  -> 帧边界写 MODE_SEL -> 连续 PARAM

额外：每 heartbeat 秒写一条心跳（FRAME_CNT/FPS/特征/u/mode/param/温度）
到 soak.log 和 data/soak.csv；Ctrl+C 可提前结束并保留数据。
"""
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


def setup(skip_camera=False, display=False):
    return hp.setup(skip_camera=skip_camera, display=display)


def preview(regs):
    return hp.preview(regs)


def _temp_c():
    """读 Zynq 温度（Linux）；读不到返回 None。"""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as fh:
            return int(fh.read().strip()) / 1000.0
    except Exception:
        return None


def _write_csv(path, rows):
    header = ["t", "frame_cnt", "delta_frames", "fps",
              "f_luma", "f_luma2", "f_grad",
              "q_tl", "q_tr", "q_bl", "q_br", "u", "mlp", "decision",
              "mode", "param", "temp_c", "switches", "overrides",
              "holds", "rejects", "stalls"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def run_soak(regs, duration=3600.0, heartbeat=60.0, poll=0.02,
             debounce=6, min_hold=1.0, param_step=2, log_path=None):
    """跑 soak；返回 summary dict。Ctrl+C 可提前结束。"""
    log_path = log_path or os.path.join(ROOT, "soak.log")
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    csv_path = os.path.join(ROOT, "data", "soak.csv")
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)

    fh = open(log_path, "w", encoding="utf-8")

    def log(msg):
        line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
        print(line, flush=True)
        fh.write(line + "\n")
        fh.flush()

    version = 0
    try:
        version = regs.version()
    except Exception:
        pass
    log("soak start  VERSION=0x%08X  duration=%.1fs  heartbeat=%.1fs  "
        "u_lo=%.2f u_hi=%.2f"
        % (version, duration, heartbeat,
           getattr(adaptive, "SPATIAL_U_LO", 0.30),
           getattr(adaptive, "SPATIAL_U_HI", 0.55)))

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
    stalls = 0
    rows = []
    next_hb = t0 + heartbeat
    prev_hb_fc = frame0
    last_fc = frame0
    last_fc_t = t0
    stall_reported = False
    temp0 = _temp_c()
    interrupted = False

    try:
        while (time.time() - t0) < duration:
            mlp_raw = regs.mlp_output()
            f = regs.mlp_features()
            q = regs.quads()
            u = adaptive.spatial_unevenness(q)
            mlp = int(mlp_raw)

            if not adaptive.is_confident(f, mlp):
                rejects += 1
                mlp = current_mode

            mode_sp, param_sp, why = adaptive.decide_spatial(f, q, mlp)
            if mode_sp is None:
                holds += 1
                decision = current_mode
                param_target = None
            else:
                decision = int(mode_sp)
                param_target = param_sp
                if decision != mlp:
                    overrides += 1
            mlp = decision

            if mlp == last_mlp:
                stable += 1
            else:
                last_mlp, stable = mlp, 1

            if param_target is None:
                p_new, _ = adaptive.param_for(f, mlp)
            else:
                p_new = param_target
            if last_param < 0 or abs(p_new - last_param) >= param_step:
                regs.set_param(p_new)
                last_param = p_new

            if (stable >= debounce and mlp != current_mode
                    and (time.time() - last_switch_t) >= min_hold):
                try:
                    regs.wait_frame_boundary()
                except Exception:
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

            now = time.time()
            fc_now = regs.frame_cnt()
            if fc_now == last_fc:
                if (now - last_fc_t) > 2.0 and not stall_reported:
                    stalls += 1
                    log("警告：FRAME_CNT 已经 %.1f 秒没动（视频流可能停了）"
                        % (now - last_fc_t))
                    stall_reported = True
            else:
                last_fc = fc_now
                last_fc_t = now
                stall_reported = False

            if now >= next_hb:
                next_hb += heartbeat
                fc = fc_now
                delta = fc - prev_hb_fc
                prev_hb_fc = fc
                dt = max(now - t0, 1e-6)
                fps = (fc - frame0) / dt
                temp = _temp_c()
                rows.append([
                    round(dt, 1), fc, delta, round(fps, 3),
                    f[0], f[1], f[2], q[0], q[1], q[2], q[3],
                    round(u, 4), int(mlp_raw), decision, current_mode,
                    last_param, "" if temp is None else round(temp, 2),
                    switches, overrides, holds, rejects, stalls,
                ])
                _write_csv(csv_path, rows)
                if heartbeat >= 5 and delta < heartbeat * 20:
                    log("警告：本区间帧数偏低 delta=%d（正常约 %.0f）"
                        % (delta, heartbeat * 29.7))
                log("t=%7.1fs FRAME=%d dFRAME=%d FPS=%.2f MLP=%d mode=%d PARAM=%d "
                    "u=%.3f f=(%d,%d,%d)%s"
                    % (dt, fc, delta, fps, int(mlp_raw), current_mode, last_param,
                       u, f[0], f[1], f[2],
                       "" if temp is None else " temp=%.1fC" % temp))
            time.sleep(poll)
    except KeyboardInterrupt:
        interrupted = True
        log("KeyboardInterrupt：提前结束，已保留数据")

    dt = max(time.time() - t0, 1e-6)
    frame1 = regs.frame_cnt()
    fps = (frame1 - frame0) / dt
    temp1 = _temp_c()
    delta_end = frame1 - prev_hb_fc
    if heartbeat >= 5 and delta_end < heartbeat * 20:
        log("警告：最后一个区间帧数偏低 delta=%d（正常约 %.0f）"
            % (delta_end, heartbeat * 29.7))
    if not rows or abs(rows[-1][0] - round(dt, 1)) > 0.5:
        f_end = regs.mlp_features()
        q_end = regs.quads()
        u_end = adaptive.spatial_unevenness(q_end)
        rows.append([
            round(dt, 1), frame1, delta_end, round(fps, 3),
            f_end[0], f_end[1], f_end[2],
            q_end[0], q_end[1], q_end[2], q_end[3],
            round(u_end, 4), regs.mlp_output(), current_mode,
            regs.param(), "" if temp1 is None else round(temp1, 2),
            switches, overrides, holds, rejects, stalls,
        ])
    log("soak end  t=%.1fs frames=%d fps=%.2f switches=%d overrides=%d "
        "holds=%d rejects=%d stalls=%d final_mode=%d final_param=%d temp0=%s temp1=%s"
        % (dt, frame1 - frame0, fps, switches, overrides, holds, rejects,
           stalls,
           regs.mode_sel(), regs.param(),
           "" if temp0 is None else "%.1fC" % temp0,
           "" if temp1 is None else "%.1fC" % temp1))
    _write_csv(csv_path, rows)
    fh.close()

    return {
        "interrupted": interrupted,
        "seconds": dt,
        "frames": frame1 - frame0,
        "fps": fps,
        "switches": switches,
        "overrides": overrides,
        "holds": holds,
        "rejects": rejects,
        "stalls": stalls,
        "final_mode": regs.mode_sel(),
        "final_param": regs.param(),
        "temp_start": temp0,
        "temp_end": temp1,
        "log": log_path,
        "csv": csv_path,
    }


def summary(result):
    print("=" * 60)
    print("soak summary")
    print("=" * 60)
    print("duration   : %.1f s" % result["seconds"])
    print("frames     : %d" % result["frames"])
    print("FPS        : %.2f" % result["fps"])
    print("switches   : %d" % result["switches"])
    print("overrides  : %d" % result["overrides"])
    print("holds      : %d" % result["holds"])
    print("rejects    : %d" % result["rejects"])
    print("stalls     : %d" % result["stalls"])
    print("final mode : %d / PARAM=%d"
          % (result["final_mode"], result["final_param"]))
    print("temp       : %s -> %s"
          % (result["temp_start"], result["temp_end"]))
    print("log        : %s" % result["log"])
    print("csv        : %s" % result["csv"])


def cleanup(ol, vdma0, vdma1):
    return hp.cleanup(ol, vdma0, vdma1)
