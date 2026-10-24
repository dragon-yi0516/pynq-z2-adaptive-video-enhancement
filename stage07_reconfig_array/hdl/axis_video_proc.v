//=============================================================================
// axis_video_proc —— 阶段 7：可重构处理阵列（三模式）
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
// 阶段 7 新增：真正去改像素了。按 MODE_SEL 选三种处理：
//   mode 0  暗光增强   : 每个通道 ×1.5（3/2），带饱和
//   mode 1  逆光补偿   : 暗部提亮 + 亮部压制
//   mode 2  细节锐化   : 1 维高通（当前像素 - 左邻像素）/2 叠加
//
// 三个关键点：
//   * mode_active 是**帧边界**重采样过的，所以切换永远发生在帧与帧之间 → 不撕裂。
//   * 像素通路是组合逻辑（只有“左邻像素”是寄存器），
//     所以 tvalid/tuser/tlast/tready 完全不用改，AXIS 时序和直通版一模一样。
//   * 特征提取用的仍然是**处理前**的输入像素，不会出现
//     “换模式 → 特征变 → MLP 又换模式”的自激（见 docs/02 第 4 节）。
//
// VERSION = 0x0001_0407（家族 0x000100 + 修订 04 + 阶段 7）
//   修订 02 = 时序违例最严重（WNS -5.093）、mode2 画面被采坏的那一版
//   修订 03 = 像素通路两级流水 + mode2 改写成无符号算式（WNS 降到 -3.923，
//             但 v_demosaic -> grad16_a 仍然违例 -2.324）
//   修订 04 = 统计链路再切一级：亮度/梯度分开，源头改成 px1_*（本模块寄存器），
//             把 v_demosaic 的输出 mux 和长走线从这条路径上摘掉
//=============================================================================
`timescale 1ns / 1ps

module axis_video_proc #(
    parameter integer C_TDATA_WIDTH = 24,
    // 0x0001_RRSS：家族号 0x0001，RR=修订号 02，SS=阶段号 07
    parameter [31:0]  C_VERSION     = 32'h0001_0407,
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
    // 1. 握手信号
    //    tready 直通：输入只有在“输出这一级被接收”时才前进。
    //    tvalid/tuser/tlast/tdata 由文件末尾的“重构处理阵列”那两级流水寄存产生
    //    （不再是直通，见第 8 节的说明）。
    //=========================================================================
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
    // 3. 亮度与梯度
    //=========================================================================
    wire [7:0] px_r = s_axis_video_tdata[C_R_BYTE*8 +: 8];
    wire [7:0] px_g = s_axis_video_tdata[C_G_BYTE*8 +: 8];
    wire [7:0] px_b = s_axis_video_tdata[C_B_BYTE*8 +: 8];

    // 亮度/梯度的**源是本模块自己的寄存器 px1_***（像素流水线第 1 级），
    // 不是输入端口 s_axis_video_tdata。
    //
    // 为什么：真机时序报告里违例路径的起点是 v_demosaic 的输出多路选择寄存器，
    // 终点是本模块的 grad16_a_reg —— 也就是「v_demosaic 输出 mux + 长走线 +
    // 本模块三个乘法 + 求亮度 + 求梯度」全压在一条组合路径上。
    // 从 px1_* 出发之后，v_demosaic 的输出 mux 和那段长走线就不在这条路径上了。
    // （px1_*/ls1_r 在第 8 节声明；Verilog 模块内声明顺序不影响可见性。）
    wire [15:0] y_raw  = 77 * px1_r + 150 * px1_g + 29 * px1_b;
    wire [7:0]  luma   = y_raw[15:8];
    wire [15:0] luma16 = {8'd0, luma};

    wire line_start = sof_beat | tlast_beat;   // 行首（帧首或上一行的 tlast 之后）

    //=========================================================================
    // 3b. 统计流水线（修时序用，务必保留）
    //
    // 三段教训都留在这里，别再改回去：
    //   1) 初版把「三个乘加求亮度 → luma² → 48 位累加」全挤在一个 100MHz 周期里，
    //      实测 14.663ns（WNS=-5.088），上板 mode2 画面是一片噪声。
    //   2) 只切一刀（亮度/梯度一级 + 平方一级）后 WNS 改善到 -3.923，
    //      但最差路径变成 v_demosaic -> grad16_a（-2.324ns）。
    //   3) 现在把"求梯度"从"求亮度"那一级拆出来，且源头换成 px1_*：
    //        第 0 级：px1_*（像素流水线第 1 级，已经是寄存器）
    //        第 1 级：亮度（三个乘加 + 右移）       -> luma16_s1
    //        第 2 级：梯度（|Δ|，源是 luma16_s1）   -> grad16_s2
    //        第 3 级：平方 + 透传（同一拍登记）     -> luma_sq_s3
    //        第 4 级：累加（第 4 节 acc_*）
    //      每级只跨一个寄存器，单级约 2~5ns。
    //   代价：统计值比像素晚 4 拍。帧内累加的总和不变，只是帧边界锁存也跟着晚，
    //   所以第 4 节锁存用的是 sof_s3。
    //=========================================================================
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

    always @(posedge aclk) begin
        if (!aresetn) begin
            beat_s0 <= 1'b0; sof_s0 <= 1'b0;
            beat_s1 <= 1'b0; sof_s1 <= 1'b0; luma16_s1 <= 16'd0;
            luma_prev_s1 <= 8'd0; ls2_r <= 1'b0;
            beat_s2 <= 1'b0; sof_s2 <= 1'b0;
            luma16_s2 <= 16'd0; grad16_s2 <= 16'd0;
            beat_s3 <= 1'b0; sof_s3 <= 1'b0;
            luma16_s3 <= 16'd0; grad16_s3 <= 16'd0; luma_sq_s3 <= 32'd0;
        end else begin
            beat_s0 <= beat;                 // 与 px1_* 对齐的有效标志
            sof_s0  <= sof_beat;
            // ---- 第 1 级：亮度 ----
            luma16_s1 <= luma16;
            beat_s1   <= beat_s0;
            sof_s1    <= sof_s0;
            ls2_r     <= ls1_r;              // 行首标志跟着延迟一级
            if (beat_s1)
                luma_prev_s1 <= luma16_s1[7:0];
            // ---- 第 2 级：梯度 ----
            luma16_s2  <= luma16_s1;
            grad16_s2  <= ls2_r ? 16'd0 :
                          {8'd0, (luma16_s1[7:0] > luma_prev_s1
                                  ? (luma16_s1[7:0] - luma_prev_s1)
                                  : (luma_prev_s1 - luma16_s1[7:0]))};
            beat_s2    <= beat_s1;
            sof_s2     <= sof_s1;
            // ---- 第 3 级：平方 + 透传（必须同一拍登记，否则三个量会错开一个像素）----
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
            // 为什么用 sof_s3 而不是 sof_beat：统计被上面那几级流水推后了 4 拍，
            // 锁存也必须跟着推后，否则会漏掉最后几拍的统计。
            // 这一拍 acc_* 里正好是上一帧的完整结果（本帧首像素还没加进去）。
            if (sof_s3) begin
                reg_luma_sum_r  <= acc_luma;
                reg_luma_sq_r   <= acc_luma2;
                reg_grad_sum_r  <= acc_grad;
                reg_pixel_cnt_r <= acc_pixels;
                reg_stats_ok_r  <= 1'b1;
                // 这三个移位必须和 lib/ai_video_regs.py 里的 MLP_FEAT_SHIFT 一致。
                // f3 用 16 而不是 20：平均梯度只有 0~5 的量级，移位太大就没有分辨率了。
                reg_f1_r        <= acc_luma[31:0]  >> 20;
                reg_f2_r        <= acc_luma2[47:0] >> 28;
                reg_f3_r        <= acc_grad[31:0]  >> 16;
            end

            if (beat_s3) begin
                if (sof_s3) begin
                    // 本拍既是帧首又是有效像素：新一帧的累加从这一拍开始
                    acc_luma   <= {16'd0, luma16_s3};
                    acc_luma2  <= {16'd0, luma_sq_s3};
                    acc_grad   <= 32'd0;      // 与阶段 3 起的老行为一致（首像素梯度不计）
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

    // ---- MLP 推理握手（阶段 6/7 共用，修订 02）--------------------------
    // 握手策略：把 ap_start 拉高并**保持**，直到 ap_done 到来才放开。
    // 原因见 stage06 的 HDL 注释：ap_ctrl_hs 的 ap_ready 在不同版本上时序不一致，
    // 拿它去开门可能永远开不了（实测踩过：特征在变但 MLP_OUTPUT 一直为 0）。
    reg  [31:0] reg_mlp_output_r;
    reg         reg_mlp_done_r;
    reg         mlp_pending;
    reg         mlp_busy;
    reg         mlp_start_r;
    reg         mlp_done_d;
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
                mlp_start_r       <= 1'b0;
                reg_mlp_output_r  <= {16'd0, mlp_result};
                reg_mlp_done_r    <= 1'b1;      // STATUS.bit0
                reg_mlp_done_cnt  <= reg_mlp_done_cnt + 32'd1;
            end else if (status_clear) begin
                reg_mlp_done_r    <= 1'b0;      // 读 STATUS 时清掉
            end

            // 有请求且没在跑 → 拉高 start 并保持（由上面 done 那一支放开）
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

    //=========================================================================
    // 8. 可重构处理阵列（阶段 7）
    //    组合处理：out = f(当前像素, 左邻像素, mode_active)
    //=========================================================================
    //-------------------------------------------------------------------------
    // 像素通路两级流水（修时序用，务必保留）
    //
    // 为什么加这一段：上面那条 14.66ns 的违例路径已经证明本模块的组合逻辑太长；
    // 可重构阵列原来更是从输入端口 s_axis_video_tdata 直接组合算到
    // m_axis_video_tdata，模式 2 的算式又是三种模式里最长的
    // （减法 + 移位 + 加法 + 两次比较）。真机表现：抓到的 mode2 画面成了一片噪声
    // —— 诊断格显示 38.5% 的像素被采成 0、水平差分 62.8（正常只有 2.7~3.5），
    // 而三档的输入亮度完全一样（112.1/112.0/111.5）。这是"数据在采样时被采坏"，
    // 不是"算式算得不一样"。
    //
    // 现在切成两级：
    //   第 1 级（本模块的寄存器）：px1_* = 当前像素；px2_* = 左邻像素
    //   第 2 级：输出寄存器 + 跟着一起延迟的 tvalid/tuser/tlast
    // 这样每条组合路径都只跨"寄存器 -> 一级逻辑 -> 寄存器"。
    //-------------------------------------------------------------------------
    reg [7:0] px1_r, px1_g, px1_b;      // 当前像素（延迟 1 拍）
    reg [7:0] px2_r, px2_g, px2_b;      // 左邻像素（延迟 2 拍）
    reg       v1_r, u1_r, l1_r, ls1_r;  // valid / tuser / tlast / line_start
    reg [1:0] mode1_r;

    always @(posedge aclk) begin
        if (!aresetn) begin
            px1_r <= 8'd0; px1_g <= 8'd0; px1_b <= 8'd0;
            px2_r <= 8'd0; px2_g <= 8'd0; px2_b <= 8'd0;
            v1_r  <= 1'b0; u1_r  <= 1'b0; l1_r  <= 1'b0; ls1_r <= 1'b0;
            mode1_r <= 2'd0;
        end else if (beat) begin
            px1_r  <= px_r;  px1_g  <= px_g;  px1_b  <= px_b;
            px2_r  <= px1_r; px2_g  <= px1_g; px2_b  <= px1_b;
            v1_r   <= 1'b1;
            u1_r   <= s_axis_video_tuser;
            l1_r   <= s_axis_video_tlast;
            ls1_r  <= line_start;
            mode1_r <= mode_active;
        end else if (m_axis_video_tready) begin
            // 输入没有新数据、而下游可以接收：把 valid 撤掉（避免重复计数）
            v1_r <= 1'b0;
        end
    end

    // 单通道处理 + 饱和到 0~255
    function [7:0] reconfig_ch;
        input [7:0] c;          // 当前像素
        input [7:0] p;          // 左邻像素
        input [1:0] mode;
        input       lstart;     // 行首（没有左邻）
        integer v;
        integer t;
        begin
            case (mode)
                2'd0: v = (c * 3) >> 1;                        // ×1.5
                2'd1: begin
                    if (c < 96)        v = c + (c >> 1);       // 暗部提亮
                    else if (c > 160)  v = c - ((c - 160) >> 2); // 亮部压制
                    else               v = c;
                end
                2'd2: begin
                    // 一维高通：out = c + (c - 左邻)/2，全程按无符号算。
                    // 原来写成 c + (($signed({1'b0,c}) - $signed({1'b0,p})) >>> 1)：
                    // 无符号的 c 和有符号的移位结果混在一个表达式里，结果依赖
                    // “表达式宽度会不会被左值拓宽”这条细节规则，可读性差、也容易
                    // 被综合工具解释成别的东西。改成按大小分两支，只有一种读法。
                    if (lstart)      v = c;                        // 行首没得锐化
                    else if (c >= p) v = c + ((c - p) >> 1);        // 比左邻亮：再加一点
                    else begin                                      // 比左邻暗：先算要减多少
                        t = (p - c) >> 1;                           // t 在 0~127
                        v = (c > t) ? (c - t) : 0;                  // 不够减就压到 0
                    end
                end
                default: v = c;
            endcase
            if (v < 0)        reconfig_ch = 8'd0;
            else if (v > 255) reconfig_ch = 8'd255;
            else              reconfig_ch = v[7:0];
        end
    endfunction

    wire [7:0] out_r = reconfig_ch(px1_r, px2_r, mode1_r, ls1_r);
    wire [7:0] out_g = reconfig_ch(px1_g, px2_g, mode1_r, ls1_r);
    wire [7:0] out_b = reconfig_ch(px1_b, px2_b, mode1_r, ls1_r);

    // 保持与输入完全相同的字节序：[23:16]=R, [15:8]=B, [7:0]=G
    wire [23:0] proc_px = {out_r, out_b, out_g};

    //---- 第 2 级：输出寄存 -------------------------------------------------
    reg [C_TDATA_WIDTH-1:0] m_tdata_r;
    reg m_tvalid_r, m_tuser_r, m_tlast_r;

    always @(posedge aclk) begin
        if (!aresetn) begin
            m_tdata_r  <= {C_TDATA_WIDTH{1'b0}};
            m_tvalid_r <= 1'b0;
            m_tuser_r  <= 1'b0;
            m_tlast_r  <= 1'b0;
        end else if (m_axis_video_tready) begin
            m_tdata_r  <= proc_px[C_TDATA_WIDTH-1:0];
            m_tvalid_r <= v1_r;
            m_tuser_r  <= u1_r;
            m_tlast_r  <= l1_r;
        end
    end

    assign m_axis_video_tdata  = m_tdata_r;
    assign m_axis_video_tvalid = m_tvalid_r;
    assign m_axis_video_tuser  = m_tuser_r;
    assign m_axis_video_tlast  = m_tlast_r;

endmodule
