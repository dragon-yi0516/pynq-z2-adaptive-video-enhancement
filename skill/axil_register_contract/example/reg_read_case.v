// Minimal example used by check_hdl.py
module reg_read_case (
    input  wire [5:0] addr,
    output reg  [31:0] r
);
always @(*) begin
    case (addr)
        6'h00: r = 32'd1;
        6'h04: r = 32'd2;
        6'h08: r = 32'd3;
        6'h0C: r = 32'h0001_020D;
        6'h34: r = 32'd192;
        6'h38: r = 32'd0;
        6'h3C: r = 32'd0;
        default: r = 32'd0;
    endcase
end
endmodule
