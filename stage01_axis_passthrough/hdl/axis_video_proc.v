//=============================================================================
// axis_video_proc —— OV5640 视频流自定义处理 IP（阶段 1：纯直通）
//
// 位置：插在 v_demosaic_0/m_axis_video 与 axi_vdma_0/S_AXIS_S2MM 之间。
// 接口：AXI4-Stream Video，24bit RGB，tuser=帧起始(SOF)，tlast=行结束(EOL)。
//
// 阶段 1 只做直通，目的有两个：
//   1. 先把“自定义 IP 插进视频流”这件事验证通，画面必须和插之前一模一样。
//   2. 把端口名字固定下来（s_axis_video_* / m_axis_video_*），
//      后面阶段 2/3/6/7 只是往内部加逻辑，BD 的连线方式不再变。
//
// 设计取舍：
//   * 阶段 1 用组合直通（不插寄存器），保证行为与原来完全等价、延迟最小。
//   * aclk/aresetn 现在就保留，阶段 2 加 AXI-Lite 时直接用，
//     避免那时再改一次端口导致 BD 要重连。
//=============================================================================
`timescale 1ns / 1ps

module axis_video_proc #(
    parameter integer C_TDATA_WIDTH = 24
) (
    // 视频时钟域（与 v_demosaic / axi_vdma_0 同域：FCLK_CLK0 = 100MHz）
    input  wire                        aclk,
    input  wire                        aresetn,

    // ---------------- 视频输入：来自 v_demosaic_0/m_axis_video ----------------
    input  wire [C_TDATA_WIDTH-1:0]    s_axis_video_tdata,
    input  wire                        s_axis_video_tvalid,
    output wire                        s_axis_video_tready,
    input  wire                        s_axis_video_tuser,
    input  wire                        s_axis_video_tlast,

    // ---------------- 视频输出：去 axi_vdma_0/S_AXIS_S2MM --------------------
    output wire [C_TDATA_WIDTH-1:0]    m_axis_video_tdata,
    output wire                        m_axis_video_tvalid,
    input  wire                        m_axis_video_tready,
    output wire                        m_axis_video_tuser,
    output wire                        m_axis_video_tlast
);

    // 纯直通：数据、valid、帧起始、行结束原样传递；
    // 反压方向从输出端回传到输入端。
    assign m_axis_video_tdata  = s_axis_video_tdata;
    assign m_axis_video_tvalid = s_axis_video_tvalid;
    assign m_axis_video_tuser  = s_axis_video_tuser;
    assign m_axis_video_tlast  = s_axis_video_tlast;
    assign s_axis_video_tready = m_axis_video_tready;

    // 阶段 1 用不到复位，但保留端口（阶段 2 起会用到），
    // 这里给一个显式引用避免综合工具报 “unused” 影响阅读。
    wire _unused_ok = aresetn;

endmodule
