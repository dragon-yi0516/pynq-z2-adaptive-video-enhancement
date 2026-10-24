// =============================================================================
// MLP 前向推理（3-8-3，Q8.8 定点）
//
// 与 ai_video/stage04_mlp_train/mlp_common.py 的 predict_fixed_raw() **逐位等价**：
//   xq[j] = clamp(x_raw, 0, 32767>>SHIFT) << SHIFT
//   h[i]  = max( b1[i] + Σ_j (w1[j][i] * xq[j]) >> 8 , 0 )
//   y[k]  = b2[k] + Σ_i (w2[i][k] * h[i]) >> 8
//   out   = argmax(y)
//
// 为什么全部用 ap_int 而不是 float：
//   FPGA 上定点的资源/时序好得多；而且要和 Python 的定点参考实现一致，
//   用同一种“算术右移”语义（负数右移是 floor）才不会出现一两个样本的偏差。
// =============================================================================
#include "mlp_engine.h"
#include "mlp_weights.h"

ap_int<16> mlp_engine(ap_int<16> luma,
                      ap_int<16> contrast,
                      ap_int<16> sharpness)
{
#pragma HLS INTERFACE ap_ctrl_hs port=return
#pragma HLS PIPELINE II=1

    ap_int<16> raw[MLP_INPUT_DIM];
    raw[0] = luma;
    raw[1] = contrast;
    raw[2] = sharpness;

    // ---- 1. 输入定点化 -----------------------------------------------------
    ap_int<16> xq[MLP_INPUT_DIM];
    const ap_int<16> X_LIMIT = (ap_int<16>)((32767 >> MLP_INPUT_SHIFT));
    for (int j = 0; j < MLP_INPUT_DIM; j++) {
#pragma HLS UNROLL
        ap_int<16> v = raw[j];
        if (v < 0) v = 0;
        if (v > X_LIMIT) v = X_LIMIT;
        xq[j] = v << MLP_INPUT_SHIFT;
    }

    // ---- 2. 第一层：3 -> 8，ReLU ------------------------------------------
    ap_int<32> h[MLP_HIDDEN_DIM];
    for (int i = 0; i < MLP_HIDDEN_DIM; i++) {
#pragma HLS UNROLL
        ap_int<32> acc = (ap_int<32>)b1[i];
        for (int j = 0; j < MLP_INPUT_DIM; j++) {
#pragma HLS UNROLL
            acc += ((ap_int<32>)w1[j * MLP_HIDDEN_DIM + i] * (ap_int<32>)xq[j])
                   >> MLP_Q_SHIFT;
        }
        h[i] = (acc > 0) ? acc : (ap_int<32>)0;
    }

    // ---- 3. 第二层：8 -> 3 -------------------------------------------------
    ap_int<32> y[MLP_OUTPUT_DIM];
    for (int k = 0; k < MLP_OUTPUT_DIM; k++) {
#pragma HLS UNROLL
        ap_int<32> acc = (ap_int<32>)b2[k];
        for (int i = 0; i < MLP_HIDDEN_DIM; i++) {
#pragma HLS UNROLL
            acc += ((ap_int<32>)w2[i * MLP_OUTPUT_DIM + k] * h[i]) >> MLP_Q_SHIFT;
        }
        y[k] = acc;
    }

    // ---- 4. argmax ---------------------------------------------------------
    ap_int<16> best = 0;
    ap_int<32> best_val = y[0];
    for (int k = 1; k < MLP_OUTPUT_DIM; k++) {
#pragma HLS UNROLL
        if (y[k] > best_val) {
            best_val = y[k];
            best = (ap_int<16>)k;
        }
    }
    return best;
}
