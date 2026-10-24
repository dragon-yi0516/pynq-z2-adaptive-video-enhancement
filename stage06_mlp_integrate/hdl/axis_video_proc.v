//=============================================================================
// axis_video_proc —— 阶段 6：接入 MLP 推理
//
// 在阶段 2（直通 + AXI-Lite）基础上，每个像素顺便统计三个特征：
//   亮度   : Y = (77*R + 150*G + 29*B) >> 8
//   对比度 : 累加 sumY2，软件算标准差
//   清晰度 : 累加相邻像素 |Y(x) - Y(x-1)|
//
// 关键设计（为什么这么做见 docs/02_why_this_design.md）：
//   * 硬件只累加，不做除法和开方，省 DSP，公式调整只改 Python。
//   * 每个 tuser（帧起始）把活累加器**锁存**到读数寄存器再清零：
//     软件读到的永远是“上一整帧”的完整统计，不会读到算了一半的值。
//   * 累加只在 beat（tvalid & tready）时进行，避免反压时重复计数。
//   * 统计用的是**处理前**的输入像素（mode_active 还没作用到像素上），
//     这样不管当前是哪种增强模式，特征都是对“原始场景”的描述，
//     不会出现“换了模式 → 特征变了 → MLP 又换模式”的自激振荡。
//
// 字节序说明（重要）：
//   这条流水线里 tdata 的字节顺序是 [23:16]=R, [15:8]=B, [7:0]=G，
//   与本工程 notebook 里 `frame_to_rgb()` 的 BGR->RGB 换位一致。
//   如果以后换摄像头/改 demosaic 配置导致颜色不对，
//   只需改下面 C_R_BYTE / C_G_BYTE / C_B_BYTE 三个参数即可，不用懂算法。
//
// 阶段 6 相对阶段 3 多出来的部分：
//   * 每个帧边界用「上一帧的特征」触发一次 MLP 推理（mlp_start / mlp_done 握手）；
//   * MLP 结果写进 MLP_OUTPUT 寄存器，并置 STATUS.bit0（推理完成）。
//   * 推理有 1 帧延迟：帧 N 结束时算帧 N 的特征，在帧 N+1 的边界发起推理。
//     这是故意的——统计必须等一帧结束才能算完，硬件不需要额外缓存。
//
// 喂给 MLP 的三个数是「右移后的累加值」（见 lib/ai_video_regs.py 的 MLP_FEAT_SHIFT）：
//     f1 = sumY   >> 20
//     f2 = sumY2  >> 28
//     f3 = sumGrad>> 20
// 它们和 Python 训练/量化时用的三个输入**完全同一套定义**，否则板上结果会错。
//
// VERSION = 0x0001_0306（家族 0x000100 + 修订 03 + 阶段 6）
//
// 修订 03（2026-10-05）：给统计链路加流水线，修时序。
//   和阶段 3 是同一个坑：亮度/平方/48 位累加全压在一条组合路径上，
//   实测 WNS 约 -5.4ns（100MHz 周期 10ns）。阶段 7 的 HDL（v1.6）早就修过，
//   这里照搬同一套分级，详见下面第 3 节的注释。
//=============================================================================
`timescale 1ns / 1ps

module axis_video_proc #(
    parameter integer C_TDATA_WIDTH = 24,
    // 0x0001_RRSS：家族号 0x0001，RR=修订号 02，SS=阶段号 06
    // （修订号 02 = 把握手从「1拍脉冲+等ap_ready」改成「保持 start 到 done」，
    //   并加了两个诊断计数器，用来定位 MLP_OUTPUT 一直是 0 的问题）
    parameter [31:0]  C_VERSION     = 32'h0001_0306,
    // tdata 里 R/G/B 分别位于第几个字节
    parameter integer C_R_BYTE      = 2,
    parameter integer C_G_BYTE      = 0,
    parameter integer C_B_BYTE      = 1
) (
    input  wire                        aclk,
    input  wire                        aresetn,

    // AXI4-Lite
    input  wire [5:0]                  s_axi_awaddr,
    input  wire                        s_axi_awvalid,
    output wire                        s_axi_awready,
    input  wire [31:0]                 s_axi_wdata,
    input  wire [3:0]                  s_axi_wstrb,
    input  wire                        s_axi_wvalid,
    output wire                        s_axi_wready,
    output wire [1:0]                  s_axi_bresp,
    output wire                        s_axi_bvalid,
    input  wire                        s_axi_bready,
    input  wire [5:0]                  s_axi_araddr,
    input  wire                        s_axi_arvalid,
    output wire                        s_axi_arready,
    output wire [31:0]                 s_axi_rdata,
    output wire [1:0]                  s_axi_rresp,
    output wire                        s_axi_rvalid,
    input  wire                        s_axi_rready,

    // 视频输入 / 输出
    input  wire [C_TDATA_WIDTH-1:0]    s_axis_video_tdata,
    input  wire                        s_axis_video_tvalid,
    output wire                        s_axis_video_tready,
    input  wire                        s_axis_video_tuser,
    input  wire                        s_axis_video_tlast,
    output wire [C_TDATA_WIDTH-1:0]    m_axis_video_tdata,
    output wire                        m_axis_video_tvalid,
    input  wire                        m_axis_video_tready,
    output wire                        m_axis_video_tuser,
    output wire                        m_axis_video_tlast,

    // ---- 与 HLS mlp_engine IP 的握手（BD 里逐根连过去）-------------------
    output wire                        mlp_start,
    input  wire                        mlp_ready,
    output wire [15:0]                 mlp_luma,
    output wire [15:0]                 mlp_contrast,
    output wire [15:0]                 mlp_sharpness,
    input  wire                        mlp_done,
    input  wire [15:0]                 mlp_result
);

    //=========================================================================
    // 1. 视频直通（阶段 3 仍然不改像素，改像素是阶段 7 的事）
    //=========================================================================
    assign m_axis_video_tdata  = s_axis_video_tdata;
    assign m_axis_video_tvalid = s_axis_video_tvalid;
    assign m_axis_video_tuser  = s_axis_video_tuser;
    assign m_axis_video_tlast  = s_axis_video_tlast;
    assign s_axis_video_tready = m_axis_video_tready;

    //=========================================================================
    // 2. beat / 帧首 / 行末
    //    只在 beat（真正传输）时更新状态，避免反压时重复计数。
    //=========================================================================
    wire beat       = s_axis_video_tvalid & s_axis_video_tready;
    wire tlast_beat = beat & s_axis_video_tlast;

    reg  tuser_d;
    wire sof_beat   = beat & s_axis_video_tuser & ~tuser_d;

    always @(posedge aclk) begin
        if (!aresetn)
            tuser_d <= 1'b0;
        else if (beat)
            tuser_d <= s_axis_video_tuser;
    end

    //=========================================================================
    // 3. 亮度与梯度（统计流水线，修时序用，务必保留）
    //
    // 与阶段 3 修订 01 完全相同的分级：
    //   第 0 级：px1_*  —— 本模块自己的寄存器，把 demosaic 的输出 mux 和
    //                     那段长走线从关键路径上摘掉
    //   第 1 级：亮度（三个乘加 + 右移）        -> luma16_s1
    //   第 2 级：梯度（|Δ|，源是 luma16_s1）    -> grad16_s2
    //   第 3 级：平方 + 透传（必须同一拍登记）  -> luma_sq_s3 / luma16_s3 / grad16_s3
    //   第 4 级：累加（第 4 节的 acc_*）
    // 代价：统计值比像素晚 4 拍，帧边界锁存也要跟着用 sof_s3。
    //=========================================================================
    wire [7:0] px_r = s_axis_video_tdata[C_R_BYTE*8 +: 8];
    wire [7:0] px_g = s_axis_video_tdata[C_G_BYTE*8 +: 8];
    wire [7:0] px_b = s_axis_video_tdata[C_B_BYTE*8 +: 8];

    wire line_start = sof_beat | tlast_beat;   // 行首（帧首或上一行的 tlast 之后）

    // ---- 第 0 级：像素寄存器（统计的源头换成这里，不再直接用输入端口）----
    reg [7:0] px1_r, px1_g, px1_b;
    reg       ls1_r;            // 行首标志，与 px1_* 对齐

    // ---- 第 1~3 级：统计流水线 ----
    reg        beat_s0, sof_s0;
    reg        beat_s1, sof_s1;
    reg [15:0] luma16_s1;
    reg  [7:0] luma_prev_s1;    // 左邻像素的亮度（与 luma16_s1 同级）
    reg        ls2_r;           // 行首标志，与 luma16_s1 对齐
    reg        beat_s2, sof_s2;
    reg [15:0] luma16_s2, grad16_s2;
    reg        beat_s3, sof_s3;
    reg [15:0] luma16_s3, grad16_s3;
    reg [31:0] luma_sq_s3;      // 最大 65025

    // 77+150+29 = 256，所以右移 8 位正好还原到 0~255，不会溢出（最大 65280）
    wire [15:0] y_raw  = 77 * px1_r + 150 * px1_g + 29 * px1_b;
    wire [15:0] luma16 = {8'd0, y_raw[15:8]};

    always @(posedge aclk) begin
        if (!aresetn) begin
            px1_r <= 8'd0; px1_g <= 8'd0; px1_b <= 8'd0; ls1_r <= 1'b0;
            beat_s0 <= 1'b0; sof_s0 <= 1'b0;
            beat_s1 <= 1'b0; sof_s1 <= 1'b0; luma16_s1 <= 16'd0;
            luma_prev_s1 <= 8'd0; ls2_r <= 1'b0;
            beat_s2 <= 1'b0; sof_s2 <= 1'b0;
            luma16_s2 <= 16'd0; grad16_s2 <= 16'd0;
            beat_s3 <= 1'b0; sof_s3 <= 1'b0;
            luma16_s3 <= 16'd0; grad16_s3 <= 16'd0; luma_sq_s3 <= 32'd0;
        end else begin
            // ---- 第 0 级：像素 ----
            if (beat) begin
                px1_r <= px_r; px1_g <= px_g; px1_b <= px_b;
                ls1_r <= line_start;
            end

            // ---- 第 1 级：亮度 ----
            luma16_s1 <= luma16;
            beat_s0   <= beat;
            sof_s0    <= sof_beat;
            beat_s1   <= beat_s0;
            sof_s1    <= sof_s0;
            ls2_r     <= ls1_r;
            if (beat_s1)
                luma_prev_s1 <= luma16_s1[7:0];

            // ---- 第 2 级：梯度 ----
            luma16_s2 <= luma16_s1;
            grad16_s2 <= ls2_r ? 16'd0 :
                         {8'd0, (luma16_s1[7:0] > luma_prev_s1
                                 ? (luma16_s1[7:0] - luma_prev_s1)
                                 : (luma_prev_s1 - luma16_s1[7:0]))};
            beat_s2   <= beat_s1;
            sof_s2    <= sof_s1;

            // ---- 第 3 级：平方 + 透传（同一拍登记，否则三个量会错开一个像素）----
            luma16_s3  <= luma16_s2;
            grad16_s3  <= grad16_s2;
            luma_sq_s3 <= luma16_s2 * luma16_s2;
            beat_s3    <= beat_s2;
            sof_s3     <= sof_s2;
        end
    end

    //=========================================================================
    // 4. 累加器 + 帧边界锁存
    //=========================================================================
    reg [31:0] acc_luma;     // sumY    最大 921600*255  ~ 2.35e8  -> 32bit 够
    reg [47:0] acc_luma2;    // sumY2   最大 921600*65025 ~ 6.0e10  -> 48bit 够
    reg [31:0] acc_grad;     // sumGrad 同上
    reg [31:0] acc_pixels;

    reg [31:0] reg_luma_sum_r;
    reg [47:0] reg_luma_sq_r;
    reg [31:0] reg_grad_sum_r;
    reg [31:0] reg_pixel_cnt_r;
    reg        reg_stats_ok_r;
    // 喂给 MLP 的三个特征（帧边界锁存，与 Python 的 MLP_FEAT_SHIFT 一致）
    reg [15:0] reg_f1_r;
    reg [15:0] reg_f2_r;
    reg [15:0] reg_f3_r;

    always @(posedge aclk) begin
        if (!aresetn) begin
            acc_luma      <= 32'd0;
            acc_luma2     <= 48'd0;
            acc_grad      <= 32'd0;
            acc_pixels    <= 32'd0;
            reg_luma_sum_r  <= 32'd0;
            reg_luma_sq_r   <= 48'd0;
            reg_grad_sum_r  <= 32'd0;
            reg_pixel_cnt_r <= 32'd0;
            reg_stats_ok_r  <= 1'b0;
            reg_f1_r        <= 16'd0;
            reg_f2_r        <= 16'd0;
            reg_f3_r        <= 16'd0;
        end else begin
            // 帧起始：先把上一帧的结果搬进读数寄存器。
            // 用 sof_s3 而不是 sof_beat：统计被上面三级流水推后了 4 拍，
            // 锁存必须跟着推后，否则会漏掉最后几拍的统计。
            if (sof_s3) begin
                reg_luma_sum_r  <= acc_luma;
                reg_luma_sq_r   <= acc_luma2;
                reg_grad_sum_r  <= acc_grad;
                reg_pixel_cnt_r <= acc_pixels;
                reg_stats_ok_r  <= 1'b1;
                // 这三个移位必须和 lib/ai_video_regs.py 里的 MLP_FEAT_SHIFT 一致。
                // f3 用 16 而不是 20：平均梯度只有 0~5 的量级，移位太大就没有分辨率了
                // （真机第一次采集时 f_grad 恒等于 2，特征直接废掉）。
                reg_f1_r        <= acc_luma[31:0]  >> 20;
                reg_f2_r        <= acc_luma2[47:0] >> 28;
                reg_f3_r        <= acc_grad[31:0]  >> 16;
            end

            if (beat_s3) begin
                if (sof_s3) begin
                    // 本拍既是帧首又是有效像素：新一帧的累加从这一拍开始
                    acc_luma   <= {16'd0, luma16_s3};
                    acc_luma2  <= {16'd0, luma_sq_s3};
                    acc_grad   <= 32'd0;
                    acc_pixels <= 32'd1;
                end else begin
                    acc_luma   <= acc_luma   + {16'd0, luma16_s3};
                    acc_luma2  <= acc_luma2  + {16'd0, luma_sq_s3};
                    acc_grad   <= acc_grad   + {16'd0, grad16_s3};
                    acc_pixels <= acc_pixels + 32'd1;
                end
            end
        end
    end

    //=========================================================================
    // 5. 其余寄存器（阶段 2 的部分保持不变）
    //=========================================================================
    reg  [31:0] reg_mode_sel;
    reg  [31:0] reg_frame_cnt;
    reg  [31:0] reg_vblank_cnt;
    reg         vblank_flag;
    reg  [1:0]  mode_active;

    // ---- MLP 推理握手（阶段 6，修订 02）----------------------------------
    // 握手策略：**把 ap_start 拉高并一直保持，直到 ap_done 到来才放开**。
    //
    // 为什么不用「1 拍脉冲 + 等 ap_ready 为高」：
    //   ap_ctrl_hs 的 ap_ready 到底是「空闲时一直高」还是「结束时脉冲一下」，
    //   不同 HLS 版本/配置并不一致。如果它是后者，拿 ap_ready 去开门就永远开不了
    //   —— 实测就踩了这个坑：特征 (f) 明明随场景在变，但 MLP_OUTPUT 和 done
    //   一直是 0，等于推理一次都没跑。
    //   改成「保持 start 到 done」之后两种时序都成立：start 一直高，
    //   只要 ap_ready 出现过一次就会被采样到。
    //   mlp_ready 端口保留（BD 里连着），但不再参与判断。
    reg  [31:0] reg_mlp_output_r;
    reg         reg_mlp_done_r;
    reg         mlp_pending;
    reg         mlp_busy;
    reg         mlp_start_r;
    reg         mlp_done_d;
    // 诊断用计数器：看「发出过几次 start」和「收到过几次 done」，
    // 就能判断卡在哪一环（见 stage06 的 VERIFY.md 里的排查表）。
    reg  [31:0] reg_mlp_start_cnt;
    reg  [31:0] reg_mlp_done_cnt;
    // AXI 读 STATUS 时产生的 1 拍清除脉冲（在下面第 7 节里驱动）
    reg         status_clear;

    wire [31:0] reg_mlp_output = reg_mlp_output_r;
    wire        reg_mlp_done   = reg_mlp_done_r;

    assign mlp_start     = mlp_start_r;
    assign mlp_luma      = reg_f1_r;
    assign mlp_contrast  = reg_f2_r;
    assign mlp_sharpness = reg_f3_r;

    wire mlp_done_rise = mlp_done & ~mlp_done_d;

    always @(posedge aclk) begin
        if (!aresetn) begin
            reg_mlp_output_r  <= 32'd0;
            reg_mlp_done_r    <= 1'b0;
            mlp_pending       <= 1'b0;
            mlp_busy          <= 1'b0;
            mlp_start_r       <= 1'b0;
            mlp_done_d        <= 1'b0;
            reg_mlp_start_cnt <= 32'd0;
            reg_mlp_done_cnt  <= 32'd0;
        end else begin
            mlp_done_d  <= mlp_done;

            // 每个帧边界记一个“待推理”请求
            if (sof_beat)
                mlp_pending <= 1'b1;

            if (mlp_done_rise) begin
                mlp_busy          <= 1'b0;
                mlp_start_r       <= 1'b0;             // 收到 done 才放开 start
                reg_mlp_output_r  <= {16'd0, mlp_result};
                reg_mlp_done_r    <= 1'b1;             // STATUS.bit0
                reg_mlp_done_cnt  <= reg_mlp_done_cnt + 32'd1;
            end else if (status_clear) begin
                reg_mlp_done_r    <= 1'b0;             // 读 STATUS 时清掉
            end

            // 有请求且没在跑 → 拉高 start 并**保持**（由上面 done 那一支放开）
            if (mlp_pending && !mlp_busy) begin
                mlp_start_r       <= 1'b1;
                mlp_busy          <= 1'b1;
                mlp_pending       <= 1'b0;
                reg_mlp_start_cnt <= reg_mlp_start_cnt + 32'd1;
            end
        end
    end

    wire [31:0] reg_status = {29'd0, reg_stats_ok_r, vblank_flag, reg_mlp_done};

    always @(posedge aclk) begin
        if (!aresetn) begin
            reg_frame_cnt  <= 32'd0;
            reg_vblank_cnt <= 32'd0;
            vblank_flag    <= 1'b0;
            mode_active    <= 2'd0;
        end else if (sof_beat) begin
            reg_frame_cnt  <= reg_frame_cnt  + 32'd1;
            reg_vblank_cnt <= reg_vblank_cnt + 32'd1;
            vblank_flag    <= 1'b1;
            mode_active    <= reg_mode_sel[1:0];   // 帧边界才生效 -> 不撕裂
        end else if (status_clear) begin
            vblank_flag    <= 1'b0;
        end
    end

    function [31:0] reg_read;
        input [5:0] addr;
        begin
            case (addr)
                6'h00:   reg_read = reg_mlp_output;
                6'h04:   reg_read = reg_mode_sel;
                6'h08:   reg_read = reg_status;
                6'h0C:   reg_read = C_VERSION;
                6'h10:   reg_read = reg_luma_sum_r;
                6'h14:   reg_read = reg_luma_sq_r[31:0];
                6'h18:   reg_read = reg_grad_sum_r;
                6'h1C:   reg_read = reg_frame_cnt;
                6'h20:   reg_read = reg_vblank_cnt;
                6'h24:   reg_read = {16'd0, reg_luma_sq_r[47:32]};
                6'h28:   reg_read = reg_pixel_cnt_r;
                6'h2C:   reg_read = reg_mlp_start_cnt;
                6'h30:   reg_read = reg_mlp_done_cnt;
                default: reg_read = 32'd0;
            endcase
        end
    endfunction

    //=========================================================================
    // 6. AXI4-Lite 写通道
    //=========================================================================
    reg        aw_have;
    reg        w_have;
    reg [5:0]  aw_addr;
    reg [31:0] w_data;
    reg [3:0]  w_strb;
    reg        bvalid_r;

    wire write_fire = aw_have & w_have;

    always @(posedge aclk) begin
        if (!aresetn) begin
            aw_have  <= 1'b0;
            w_have   <= 1'b0;
            bvalid_r <= 1'b0;
            aw_addr  <= 6'd0;
            w_data   <= 32'd0;
            w_strb   <= 4'd0;
        end else begin
            if (s_axi_awvalid && !aw_have && !bvalid_r) begin
                aw_addr <= s_axi_awaddr;
                aw_have <= 1'b1;
            end
            if (s_axi_wvalid && !w_have && !bvalid_r) begin
                w_data <= s_axi_wdata;
                w_strb <= s_axi_wstrb;
                w_have <= 1'b1;
            end
            if (write_fire) begin
                aw_have  <= 1'b0;
                w_have   <= 1'b0;
                bvalid_r <= 1'b1;
            end else if (bvalid_r && s_axi_bready) begin
                bvalid_r <= 1'b0;
            end
        end
    end

    assign s_axi_awready = !aw_have && !bvalid_r;
    assign s_axi_wready  = !w_have  && !bvalid_r;
    assign s_axi_bvalid  = bvalid_r;
    assign s_axi_bresp   = 2'b00;

    integer bi;
    always @(posedge aclk) begin
        if (!aresetn) begin
            reg_mode_sel <= 32'd0;
        end else if (write_fire && (aw_addr[5:2] == 4'h1)) begin   // 0x04 MODE_SEL
            for (bi = 0; bi < 4; bi = bi + 1) begin
                if (w_strb[bi])
                    reg_mode_sel[bi*8 +: 8] <= w_data[bi*8 +: 8];
            end
        end
    end

    //=========================================================================
    // 7. AXI4-Lite 读通道
    //=========================================================================
    reg [31:0] rdata_r;
    reg        rvalid_r;

    always @(posedge aclk) begin
        if (!aresetn) begin
            rdata_r      <= 32'd0;
            rvalid_r     <= 1'b0;
            status_clear <= 1'b0;
        end else begin
            status_clear <= 1'b0;
            if (s_axi_arvalid && !rvalid_r) begin
                rdata_r  <= reg_read(s_axi_araddr);
                rvalid_r <= 1'b1;
                if (s_axi_araddr[5:0] == 6'h08)
                    status_clear <= 1'b1;
            end else if (rvalid_r && s_axi_rready) begin
                rvalid_r <= 1'b0;
            end
        end
    end

    assign s_axi_arready = !rvalid_r;
    assign s_axi_rvalid  = rvalid_r;
    assign s_axi_rdata   = rdata_r;
    assign s_axi_rresp   = 2'b00;

    wire _mode_in_use = ^mode_active;   // 阶段 7 会真正使用

endmodule
