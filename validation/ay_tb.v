// A headless testbench around lvd's Verilog model of the AY-3-8910 from its die
// (reference/src/ay-3-8910_reverse_engineered/rtl/ay_model.v, GPL-3.0, pinned at
// cf8d14d), built by validation/build_referees.sh and run as a referee. Nothing of
// the model is copied into ay8910-python: this file only drives its pins.
//
//   vvp ay_ref +events=events.hex +count=EVENTS +out=out.bin +reads=reads.bin +clocks=N
//
// events.hex: one 64-bit hex word per line, sorted by clock:
//   {clock[39:0], kind[7:0], a[7:0], b[7:0]}
// kind 0: select register `a` (the address byte, DA7-DA0), then write `b` to it
//      1: select register `a`, then read it (the byte goes to reads.bin)
//      2: the outside world drives port A's pins with `a` (while the port is an input)
//      3: the same for port B
//      4: /RESET pulsed over one extra clock that is not counted or sampled
//      5: latch the address byte `a` alone
//      6: write `b` alone, to whatever is selected
//      7: read alone
// An event is applied before the rising edge of the clock it names; clock 0 is the
// first clock after the one the power-on /RESET is released in.
//
// out.bin: per clock, sampled after the falling edge, one little-endian 32-bit word
//   {4'b0, iob[7:0], ioa[7:0], ch_c[3:0], ch_b[3:0], ch_a[3:0]}
// reads.bin: one 32-bit word per read, {24'b0, da[7:0]}.
`timescale 100ns/1ns

module ay_tb;
    reg clk = 0;
    reg rst_n = 0;
    reg bdir = 0, bc1 = 0;
    reg [7:0] da_drive = 8'h00;
    reg da_oe = 0;
    reg [7:0] ext_a = 8'hFF, ext_b = 8'hFF;

    wire [7:0] da;
    wire [7:0] ioa, iob;
    wire [3:0] ch_a, ch_b, ch_c;
    wire test1;

    assign da = da_oe ? da_drive : 8'bz;
    assign (weak1, weak0) da = 8'h00;  // the bus at rest: low, as the chip's pull-downs leave it
    // The outside world drives a port's pins only while the port is an input
    // (register 7 bits 6 and 7 low): against the chip's own drivers the model
    // has no answer but X.
    assign ioa = chip.r7_b[6] ? 8'bz : ext_a;
    assign iob = chip.r7_b[7] ? 8'bz : ext_b;

    ay_model chip (
        .clk(clk), ._rst(rst_n),
        .da(da), .bdir(bdir), .bc2(1'b1), .bc1(bc1),
        .a8(1'b1), ._a9(1'b0),
        .ioa(ioa), .iob(iob),
        .test1(test1), .test2(1'b0),
        .ch_a(ch_a), .ch_b(ch_b), .ch_c(ch_c)
    );

    reg [63:0] events [0:4194303];
    reg [1023:0] events_path, out_path, reads_path;
    integer out_fd, reads_fd;
    integer count, next;
    reg [63:0] clocks, n;
    reg [63:0] ev;

    task latch_address(input [7:0] value);
        begin
            da_drive = value; da_oe = 1; #0.5;
            bdir = 1; bc1 = 1; #1;
            bdir = 0; bc1 = 0; #0.5;
            da_oe = 0; #0.5;
        end
    endtask

    task write_data(input [7:0] value);
        begin
            da_drive = value; da_oe = 1; #0.5;
            bdir = 1; bc1 = 0; #1;
            bdir = 0; #0.5;
            da_oe = 0; #0.5;
        end
    endtask

    task read_data;
        begin
            da_oe = 0; #0.5;
            bdir = 0; bc1 = 1; #1;
            $fwrite(reads_fd, "%u", {24'b0, da});
            bc1 = 0; #1;
        end
    endtask

    // /RESET is released with the clock high. Released with it low, the model's
    // divider flip-flops leave reset with both halves equal and never settle (two
    // cross-coupled gates of equal delay); a real chip would fall one way or the other.
    task tick;
        begin
            #2; clk = 1; #2; rst_n = 1; #3; clk = 0; #5;
        end
    endtask

    initial begin
        if (!$value$plusargs("events=%s", events_path)) $finish;
        if (!$value$plusargs("out=%s", out_path)) $finish;
        if (!$value$plusargs("reads=%s", reads_path)) $finish;
        if (!$value$plusargs("clocks=%d", clocks)) $finish;
        if (!$value$plusargs("count=%d", count)) $finish;
        if (count > 0) $readmemh(events_path, events, 0, count - 1);
        out_fd = $fopen(out_path, "wb");
        reads_fd = $fopen(reads_path, "wb");

        // Power-on: /RESET held over 32 clocks.
        for (n = 0; n < 32; n = n + 1) begin rst_n = 0; tick; end

        next = 0;
        for (n = 0; n < clocks; n = n + 1) begin
            while (next < count && events[next][63:24] <= n) begin
                ev = events[next];
                case (ev[23:16])
                    0: begin latch_address(ev[15:8]); write_data(ev[7:0]); end
                    1: begin latch_address(ev[15:8]); read_data; end
                    2: begin ext_a = ev[15:8]; #0.5; end
                    3: begin ext_b = ev[15:8]; #0.5; end
                    4: begin rst_n = 0; tick; end
                    5: latch_address(ev[15:8]);
                    6: write_data(ev[7:0]);
                    7: read_data;
                endcase
                next = next + 1;
            end
            tick;
            $fwrite(out_fd, "%u", {4'b0, iob, ioa, ch_c, ch_b, ch_a});
        end
        $fclose(out_fd);
        $fclose(reads_fd);
        $finish;
    end
endmodule

// What validation/icarus_port.py puts on each of the model's `trireg` nets: a weak
// driver of the last value the net was driven to, bit by bit.
module ay_tb_keeper #(parameter W = 1) (inout wire [W-1:0] net);
    reg [W-1:0] held;
    integer i;
    assign (weak1, weak0) net = held;
    always @(net)
        for (i = 0; i < W; i = i + 1)
            if (net[i] === 1'b0 || net[i] === 1'b1) held[i] <= net[i];
endmodule
