`timescale 1ns/1ps
module tb;
 localparam BASE=32'h800d1980;
 reg clk=0,reset=1;
 always #5 clk=~clk;
 wire [21:0] addr; wire wr,held;wire [31:0] wd,rd;wire [3:0] mask;
 sdram_pipeline_risc cpu(.clk(clk),.reset(reset),.enable(1'b1),.uart_rx(1'b1),.sd_miso(1'b1),
    .memory_data(rd),.memory_hold(held),.memory_address(addr),.memory_write(wr),
    .memory_wdata(wd),.memory_mask(mask));
 wire req,mw;wire [20:0] ma;wire [31:0] md;wire [3:0] mm;
 wire done,valid,ready;wire [1:0] idx;
 sdram_pipeline_cache #(.LINE_BITS(11),.WAYS(2),.ROM_FILE("rom.hex"))
  c(clk,reset,addr,wr,wd,mask,held,rd,req,mw,ma,md,mm,ready,done,data,valid,idx);
 wire [31:0] unused_dq;
 sdram_burst_memory #(.FREQ(54000000)) mem(.clk(clk),.clk_sdram(clk),.reset(reset),
    .req(req),.write(mw),.address(ma),.wdata(md),.mask(mm),.ready(ready),
    .done(done),.rdata(),.word_valid(valid),.word_index(idx),.IO_sdram_dq(unused_dq));
 reg [31:0] ram[0:2097151]; reg [20:0] saved;
 wire [31:0] data=ram[saved+idx];
 initial begin $readmemh("image.hex",ram,(BASE-32'h80000000)/4,(BASE-32'h80000000)/4+116);repeat(5) @(negedge clk);reset=0;end
 wire [31:0] pc=cpu.cpuPc_15;
 wire [22:0] phase=cpu.cpuPhase_16;
 wire [31:0] retired=cpu.cpuInstret_12[64:33];
 wire sample=!held && phase==2048 && !cpu.heldState[74];
 integer stack,cap,mid_retire,pattern,carry_retries; reg clear_tags;
 integer start_cycle,first_retire,carried,writes,limit,seed,inj=-1; reg poisoned;
 integer advances=0,cycles=0,windows=0,start_adv,last_retire,max_gap,previous,tx=0;
 reg active=0;
 initial begin
   if(!$value$plusargs("limit=%d",limit))limit=64;
   if(!$value$plusargs("cap=%d",cap))cap=32;
   if(!$value$plusargs("pattern=%d",pattern))pattern=0;
   clear_tags=$test$plusargs("cold");
   if(!$value$plusargs("stack=%h",stack))stack=32'h80380000;
   #1;
   c.rom[0]=((stack+2048)&32'hfffff000)|32'h137;
   c.rom[1]=((stack&4095)<<20)|32'h10113;
   poisoned=$value$plusargs("seed=%d",seed);
 end
 integer slot;reg [31:0] tagpc,target;reg [31:0] code;
 // Deposit only at the serialized opening CSR, after older work hands over.
 always @(negedge clk) if((poisoned || clear_tags) && !held && phase==2048 && pc==BASE+'hb0 && inj!=windows)begin
   inj=windows;
   if(clear_tags)begin
     for(integer setno=0;setno<2048;setno=setno+1)begin
       c.tags[setno]=0;
       c.tags_way1[setno]=0;
     end
     // Keep in-flight requests, data and write queue. Suppress stale tag hits.
     c.tag_conflict=1; c.keep2=0; c.fill_forward=0;
     if(c.v2 && !c.a2[21] && !c.w2)c.hit2=0;
   end
   if(poisoned)begin
   code=seed+windows;
   cpu.c$running_app_arg[0+:46]=0; // no pending predictor update
   for(slot=0;slot<8;slot=slot+1)begin
     case((code/256+slot)%3)
       0:tagpc=((BASE+'h1ac)&~31)+slot*4;
       1:tagpc=((BASE+'h1cc)&~31)+slot*4;
       2:tagpc=((BASE+'hb0)&~31)+slot*4;
     endcase
     case(pattern)
       0:target=32'h80400000+slot*32'h8010+((code>>4)&3)*4;
       1:target=tagpc+((code>>4)&1)*2; // predicted self or upper halfword
       2:target=32'h80400000+(tagpc & 32'h1fff)+4+((code>>4)&1)*2; // alias chain
       default:$fatal(1,"unknown target pattern");
     endcase
     cpu.c$running_app_arg[46+42*(7-slot)+:42]=
       {code[slot],code[(slot+3)%8],tagpc[12:5],target};
   end
   cpu.heldState[107+:32]=32'hffffffff-(code%160);
   cpu.machine_0[1024+:32]=32'hffffffff-(code%17);
   end
 end
 always @(posedge clk) begin
   cycles=cycles+1;
   if(req && ready)begin
     if(mw)begin
       for(integer k=0;k<4;k=k+1)if(mm[k])ram[ma][k*8+:8]<=md[k*8+:8];
     end else saved<=ma;
   end
   if(!held)advances=advances+1;
   if(sample && pc==BASE+'hb0)begin
     active=1;start_adv=advances;last_retire=advances;previous=retired;first_retire=retired;max_gap=0;tx=0;start_cycle=cycles;writes=0;carry_retries=0;carried=(c.state!=0);
   end
   if(active)begin
     if(!held && phase==2048 && !cpu.machine_0[991] && pc==BASE+'hb4)mid_retire=retired;
     if(!held && phase==2048 && !cpu.machine_0[991] && pc==BASE+'hbc && retired-mid_retire!=12)$fatal(1,"unexpected instret inside wrapper");
     if(!held && phase==2048 && ((cpu.cpuInstruction_18[31:20]==12'hb00 && cpu.heldState[74]) ||
          (cpu.cpuInstruction_18[31:20]==12'hb02 && cpu.machine_0[991])))carry_retries=carry_retries+1;
     if(c.push)writes=writes+1;
     if(previous!=retired || (sample && pc==BASE+'hc0))begin
       if(advances-last_retire>max_gap)max_gap=advances-last_retire;
       previous=retired;last_retire=advances;
     end
     if(c.read_miss && c.state==3 && ready)begin $display("M %0d %h",windows,ma);tx=tx+1;end
     if(!held && c.v2 && !c.a2[21])$display("P %0d %h %d",windows,c.a2,c.w2);
     if(sample && pc==BASE+'hc0)begin
       if(retired-first_retire!=14 || max_gap>cap)$fatal(1,"window %0d gap %0d retire %0d",windows,max_gap,retired-first_retire);
       $display("W %0d %0d %0d %0d %0d %0d %0d %0d",windows,advances-start_adv,max_gap,tx,cycles-start_cycle,writes,carried,carry_retries);
       active=0;windows=windows+1;
       if(windows==limit)$finish;
     end
   end
   if(cycles>40000000)$fatal(1,"timeout pc=%h phase=%h retire=%d",pc,phase,retired);
 end
endmodule
