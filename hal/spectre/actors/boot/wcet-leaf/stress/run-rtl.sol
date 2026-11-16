# Run the controller test bench against the archived SDRAM sources.
#
#   SIMPLE_RISC=... sol run-rtl.sol       in a directory holding controller_tb.v
unsafe program.
B = use "sol/lib/build".
> board = B.setting "SIMPLE_RISC" "";
  _ = (if board == "" then error "set SIMPLE_RISC to the Simple-Risc checkout" else Unit);
  here = B.query ["/bin/pwd","-P"];
  evidence = "{board}/docs/evidence/2026-10-30-structural";
  _ = B.inDirectory here [] ["/usr/bin/tar","-xzf","{evidence}/baseline-sources.tar.gz","sdram/pipeline_cache.v","sdram/burst_memory.v","sdram/sdram.v"];
  _ = B.inDirectory here [] ["/bin/sh","-c","gzip -dc \"$0\" > rom.hex","{evidence}/builds/existing-54/bootrom-sdram.hex.gz"];
  _ = B.inDirectory here [] ["/bin/sh","-c","iverilog -g2012 -s tb -o sim controller_tb.v sdram/*.v"];
  B.inDirectory here [] ["vvp","sim"].
