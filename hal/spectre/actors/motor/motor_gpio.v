// The CPU owns the timing. This register drives the motor switch directly.
module motor_gpio(
    input wire clk,
    input wire reset,
    input wire write_pulse,
    input wire [31:0] pulse_us,
    output wire signal
);
    reg enabled;
    assign signal = !reset && enabled;

    always @(posedge clk) begin
        if (reset)
            enabled <= 1'b0;
        else if (write_pulse)
            enabled <= pulse_us == 32'd1;
    end
endmodule
