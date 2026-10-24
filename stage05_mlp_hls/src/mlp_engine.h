#ifndef MLP_ENGINE_H
#define MLP_ENGINE_H

#include <ap_int.h>

// 每帧调用一次：输入三个原始特征，返回分类结果 0/1/2。
//
// 为什么接口用「3 个标量 + 返回值」而不是 AXI4-Stream：
//   推理每帧只做一次，数据量极小（3 个数），用流接口反而要额外写握手逻辑。
//   用默认的 ap_ctrl_hs 块级协议（ap_start/ap_done），
//   片上只要一个状态机就能驱动。
//
// 与方案书示例的差异：方案书写的是 `ap_int<16> *mlp_out`（指针输出）。
//   指针型输出会被 HLS 额外生成一个 `mlp_out_ap_vld` 端口，
//   在 BD 里要多连一根线还容易接错；改成返回值后端口就是
//   ap_clk / ap_rst / ap_start / ap_done / ap_idle / ap_ready /
//   luma / contrast / sharpness / ap_return，接线最干净。
ap_int<16> mlp_engine(ap_int<16> luma,
                      ap_int<16> contrast,
                      ap_int<16> sharpness);

#endif
