// Phase sweep of a miss behind four same-line stores on the historical cache.
module tb;
  reg clk=0, reset=1, wr=0;
  always #5 clk=~clk;
  reg [21:0] addr=22'h200000;
  wire hold,req,mw,ready,done,valid;
  wire [20:0] ma;
  wire [31:0] md,rd,dq;
  wire [3:0] mask;
  wire [1:0] idx;
  sdram_pipeline_cache #(.LINE_BITS(11),.WAYS(2),.ROM_FILE("rom.hex"))
    c(clk,reset,addr,wr,32'h42,4'hf,hold,,req,mw,ma,md,mask,ready,done,rd,valid,idx);
  sdram_burst_memory #(.FREQ(54000000)) mem(.clk(clk),.clk_sdram(clk),.reset(reset),
    .req(req),.write(mw),.address(ma),.wdata(md),.mask(mask),.ready(ready),
    .done(done),.rdata(rd),.word_valid(valid),.word_index(idx),.IO_sdram_dq(dq));
  integer phase,i,span,peak=0,refresh_hits=0,full_hits=0,ref_seen;
  task tick; begin @(negedge clk); end endtask
  initial begin
    repeat(5) tick; reset=0;
    wait(!mem.ram.busy && !c.clearing);
    for(phase=0;phase<540;phase=phase+1)begin
      while(mem.refresh_count!=phase)tick;
      for(i=0;i<4;i=i+1)begin addr=phase*4+i;wr=1;tick;end
      addr=phase*4;wr=0;tick;addr=22'h200000;
      while(!c.read_miss)tick;
      if(c.write_count==4)full_hits=full_hits+1;
      span=0;ref_seen=0;
      while(hold)begin
        if(mem.refresh)ref_seen=1;
        span=span+1; if(span>64)$fatal(1,"hold ceiling exceeded");
        tick;
      end
      if(ref_seen)refresh_hits=refresh_hits+1;
      if(span>peak)peak=span;
      repeat(8)tick;
    end
    if(full_hits!=540 || !refresh_hits)$fatal(1,"coverage missing");
    $display("phase_cases=540 four_pending=%0d refresh_during_hold=%0d max_hold=%0d",full_hits,refresh_hits,peak);
    $finish;
  end
  initial begin #20000000;$fatal(1,"timeout");end
endmodule
