module tb;
    reg clk=0, reset=1, write_pulse=0;
    reg [31:0] value=0;
    wire signal;
    always #5 clk=~clk;
    motor_gpio dut(clk,reset,write_pulse,value,signal);
    task write_value(input [31:0] data);
        begin
            @(negedge clk); value=data; write_pulse=1;
            @(negedge clk); write_pulse=0;
        end
    endtask
    initial begin
        @(negedge clk);
        if (signal !== 0) $fatal(1,"reset");
        reset=0;
        write_value(1);
        repeat (100) begin
            @(negedge clk);
            if (signal !== 1) $fatal(1,"hold high");
        end
        write_value(0);
        if (signal !== 0) $fatal(1,"write low");
        write_value(1);
        write_value(1500);
        if (signal !== 0) $fatal(1,"unexpected command drives motor");
        write_value(1);
        reset=1;
        @(negedge clk); reset=0;
        if (signal !== 0) $fatal(1,"reset after high");
        $display("PASS motor GPIO");
        $finish;
    end
endmodule
