//=============================================================================
// axis_video_proc —— 阶段 2：加 AXI-Lite 寄存器骨架
//
// 与阶段 1 的区别只有两点：
//   1. 多了一个 AXI4-Lite 从接口 S_AXI；
//   2. 多了几个寄存器（VERSION / MODE_SEL / STATUS / FRAME_CNT / VBLANK_CNT）。
// 视频数据通路仍然是纯直通（阶段 3 才动像素）。
//
// 重要的两个设计决定：
//   * S_AXI **不单独占一个时钟**，它和视频共用 aclk。
//     BD 里 aclk 接 FCLK_CLK0(100MHz)，AXI 互联也是这个时钟，
//     所以整个 IP 只有一个时钟域，不需要任何 CDC，最不容易出错。
//   * MODE_SEL 在 **tuser（帧边界）** 才被搬进 mode_active。
//     这样 CPU 随便什么时候写 MODE_SEL，硬件都等到下一帧开始才生效，
//     天然避免半帧换模式造成的撕裂（对应方案书阶段 8 的“VBlank 切换”）。
//
// 寄存器映射见 docs/01_register_map.md。
// 阶段 2 里 0x10/0x14/0x18/0x24/0x28 这几个特征寄存器读回 0，
// 阶段 3 会把它们接上真正的累加器。
//=============================================================================
`timescale 1ns / 1ps

module axis_video_proc #(
    parameter integer C_TDATA_WIDTH = 24,
    // 0x0001_00SS：家族号 0x000100 + 阶段号 0x02
    parameter [31:0]  C_VERSION     = 32'h0001_0002
) (
    // ---- 时钟 / 复位（视频与 AXI-Lite 共用，BD 里都是 FCLK_CLK0=100MHz）----
    input  wire                        aclk,
    input  wire                        aresetn,

    // ---- AXI4-Lite 从接口 -------------------------------------------------
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

    // ---- 视频输入：v_demosaic_0/m_axis_video -------------------------------
    input  wire [C_TDATA_WIDTH-1:0]    s_axis_video_tdata,
    input  wire                        s_axis_video_tvalid,
    output wire                        s_axis_video_tready,
    input  wire                        s_axis_video_tuser,
    input  wire                        s_axis_video_tlast,

    // ---- 视频输出：axi_vdma_0/S_AXIS_S2MM ---------------------------------
    output wire [C_TDATA_WIDTH-1:0]    m_axis_video_tdata,
    output wire                        m_axis_video_tvalid,
    input  wire                        m_axis_video_tready,
    output wire                        m_axis_video_tuser,
    output wire                        m_axis_video_tlast
);

    //=========================================================================
    // 1. 视频数据通路（阶段 2 仍然是直通）
    //=========================================================================
    assign m_axis_video_tdata  = s_axis_video_tdata;
    assign m_axis_video_tvalid = s_axis_video_tvalid;
    assign m_axis_video_tuser  = s_axis_video_tuser;
    assign m_axis_video_tlast  = s_axis_video_tlast;
    assign s_axis_video_tready = m_axis_video_tready;

    //=========================================================================
    // 2. 帧边界检测：tuser 的上升沿
    //    这条流水线没有独立 vsync，tuser 就是唯一的帧起始标志。
    //=========================================================================
    reg tuser_d;
    wire sof = s_axis_video_tvalid & s_axis_video_tuser & ~tuser_d;

    always @(posedge aclk) begin
        if (!aresetn)
            tuser_d <= 1'b0;
        else if (s_axis_video_tvalid)
            tuser_d <= s_axis_video_tuser;
    end

    //=========================================================================
    // 3. 寄存器（阶段 2 实现的部分）
    //    0x10/0x14/0x18/0x24/0x28 先固定读 0，阶段 3 接真实累加器。
    //=========================================================================
    reg  [31:0] reg_mode_sel;
    reg  [31:0] reg_frame_cnt;
    reg  [31:0] reg_vblank_cnt;
    reg         vblank_flag;
    reg  [1:0]  mode_active;

    wire [31:0] reg_mlp_output = 32'd0;   // 阶段 6 由 MLP 驱动
    wire [31:0] reg_luma_sum   = 32'd0;   // 阶段 3
    wire [31:0] reg_luma_sq_lo = 32'd0;   // 阶段 3
    wire [31:0] reg_luma_sq_hi = 32'd0;   // 阶段 3
    wire [31:0] reg_grad_sum   = 32'd0;   // 阶段 3
    wire [31:0] reg_pixel_cnt  = 32'd0;   // 阶段 3
    wire        reg_stats_ok   = 1'b0;    // 阶段 3
    wire        reg_mlp_done   = 1'b0;    // 阶段 6

    wire [31:0] reg_status = {29'd0, reg_stats_ok, vblank_flag, reg_mlp_done};

    // 帧计数 / 帧边界重采样 MODE_SEL
    always @(posedge aclk) begin
        if (!aresetn) begin
            reg_frame_cnt  <= 32'd0;
            reg_vblank_cnt <= 32'd0;
            vblank_flag    <= 1'b0;
            mode_active    <= 2'd0;
        end else if (sof) begin
            reg_frame_cnt  <= reg_frame_cnt  + 32'd1;
            reg_vblank_cnt <= reg_vblank_cnt + 32'd1;
            vblank_flag    <= 1'b1;
            mode_active    <= reg_mode_sel[1:0];   // 帧边界才生效 -> 不撕裂
        end else if (status_clear) begin
            vblank_flag    <= 1'b0;
        end
    end

    // 读寄存器译码
    function [31:0] reg_read;
        input [5:0] addr;
        begin
            case (addr)
                6'h00:   reg_read = reg_mlp_output;
                6'h04:   reg_read = reg_mode_sel;
                6'h08:   reg_read = reg_status;
                6'h0C:   reg_read = C_VERSION;
                6'h10:   reg_read = reg_luma_sum;
                6'h14:   reg_read = reg_luma_sq_lo;
                6'h18:   reg_read = reg_grad_sum;
                6'h1C:   reg_read = reg_frame_cnt;
                6'h20:   reg_read = reg_vblank_cnt;
                6'h24:   reg_read = {16'd0, reg_luma_sq_hi[15:0]};
                6'h28:   reg_read = reg_pixel_cnt;
                default: reg_read = 32'd0;         // 未映射地址读 0
            endcase
        end
    endfunction

    //=========================================================================
    // 4. AXI4-Lite 写通道
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

    assign s_axi_awready = !aw_have  && !bvalid_r;
    assign s_axi_wready  = !w_have   && !bvalid_r;
    assign s_axi_bvalid  = bvalid_r;
    assign s_axi_bresp   = 2'b00;   // OKAY

    // 寄存器写入（目前只有 MODE_SEL 可写；按 WSTRB 支持字节写）
    integer bi;
    always @(posedge aclk) begin
        if (!aresetn) begin
            reg_mode_sel <= 32'd0;
        end else if (write_fire && (aw_addr[5:2] == 4'h1)) begin   // 0x04
            for (bi = 0; bi < 4; bi = bi + 1) begin
                if (w_strb[bi])
                    reg_mode_sel[bi*8 +: 8] <= w_data[bi*8 +: 8];
            end
        end
    end

    //=========================================================================
    // 5. AXI4-Lite 读通道
    //    读 STATUS 时顺手清掉 vblank_flag（粘滞标志、读清），
    //    这样软件即使错过 1 拍脉冲也能知道“刚发生过帧边界”。
    //=========================================================================
    reg [31:0] rdata_r;
    reg        rvalid_r;
    reg        status_clear;

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
    assign s_axi_rresp   = 2'b00;   // OKAY

    // mode_active 留给阶段 7 的可重构阵列使用；
    // 这里显式引用一下，避免综合工具把这一级优化掉（阶段 2 暂时没接负载）。
    wire _mode_in_use = ^mode_active;

endmodule
