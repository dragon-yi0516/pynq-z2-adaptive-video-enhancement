// =============================================================================
// C 仿真测试台
//
// 测试向量 tv_mlp.h 由 05_mlp_verify.ipynb 生成：
//   期望值 TV_Y 是 **Python 定点参考实现** 算出来的。
// 所以 csim 通过 == “HLS 实现与 Python 参考逐位一致”。
// =============================================================================
#include <cstdio>
#include "mlp_engine.h"
#include "tv_mlp.h"

int main()
{
    int fail = 0;
    for (int t = 0; t < TV_N; t++) {
        ap_int<16> out = mlp_engine((ap_int<16>)TV_X[t][0],
                                    (ap_int<16>)TV_X[t][1],
                                    (ap_int<16>)TV_X[t][2]);
        if ((int)out != (int)TV_Y[t]) {
            fail++;
            if (fail <= 20) {
                printf("MISMATCH #%d raw=(%d,%d,%d) got=%d expect=%d\n",
                       t, (int)TV_X[t][0], (int)TV_X[t][1], (int)TV_X[t][2],
                       (int)out, (int)TV_Y[t]);
            }
        }
    }
    printf("TV_N=%d  fail=%d\n", TV_N, fail);
    if (fail == 0) {
        printf("CSIM PASSED: HLS 与 Python 定点参考完全一致\n");
        return 0;
    }
    printf("CSIM FAILED\n");
    return 1;
}
