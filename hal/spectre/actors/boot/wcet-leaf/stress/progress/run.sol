# Rebuild the leaf, replay normal startup and three stale BTB tag assignments at
# five stack placements in the archived RTL, and analyse the port traffic.
#
#   QOS=... SIMPLE_RISC=... FPRISC=... SPECTRE_IMAGE=... sol "$QOS"/hal/spectre/actors/boot/wcet-leaf/stress/progress/run.sol NEW_OUTPUT
#
# SPECTRE_IMAGE names the built hal/spectre/tools/spectre-image.
unsafe program.
K = use "../../../../../../../tools/sdk/sdk".
B = use "sol/lib/build".
# The monitor uses private counter/predictor signals in this archived top.
pinned = [("observed.v","33376ec743baa45d8e117371439636917dc4f9f4201e3ed6e44859b03bbd0e38"),
  ("leaf.bin","72dfeb832d1d87c043bef1511202beaf0eb7a90157034159a4a61c43b3393dba"),
  ("cache.sv","4bf19aec80fcb87c7b603ffe427af8386472e64425106ef7f1a38ffe478eaf0e"),
  ("sdram/burst_memory.v","b96af62e6b1ec957c112d6607d6bfd901560776dedbac9078588cb8910ddb35a"),
  ("sdram/sdram.v","fac724ff34098570c5ad55b18fa2fd43770496c11005e8b6992ad27f7830693e")].
# a flat binary as one little-endian 32-bit word per line
word bytes = if Str.len bytes != 8 then error "the image is not a whole number of words"
  else "{Str.slice bytes 6 8}{Str.slice bytes 4 6}{Str.slice bytes 2 4}{Str.slice bytes 0 2}\n".
hexWords out source target = K.writeText "{out}/{target}" (Str.join "" (List.map word (K.lines (K.commandIn out ["/usr/bin/xxd","-p","-c","4",source])))).
stacks = ["80380000","80381a80","80381b80","80381bc0","80380050"].
modes = ("None", "0") :: List.concat (List.map (fn seed -> List.map (fn pattern -> (seed, pattern)) ["0","1","2"]) ["0","256","512"]).
simulate out stack mode cold = case mode of (seed, pattern) ->
  log = "runs/{stack}-{cold}-{pattern}-{seed}.log";
  argv = List.concat [["obj_dir/Vtb","+limit=256","+stack={stack}","+pattern={pattern}"],(if cold == "1" then ["+cold"] else []),(if seed == "None" then [] else ["+seed={seed}"])];
  _ = B.inDirectory out [] (List.append ["/bin/sh","-c","log=$0; shift 0; \"$@\" > \"$log\" 2>&1",log] argv);
  windows = List.len (List.filter (fn row -> Str.startsWith "W " row) (Str.split 10 (readPath "{out}/{log}")));
  K.check "incomplete {log}" (windows == 256).
> case args Unit of
    [target] ->
      here = "{K.realpath (B.setting "QOS" "")}/hal/spectre/actors/boot/wcet-leaf/stress/progress";
      leaf = K.realpath "{here}/../..";
      board = K.realpath (B.setting "SIMPLE_RISC" "");
      compiler = "{K.realpath (B.setting "FPRISC" "")}/fpr";
      _ = B.command ["/bin/mkdir",target];
      out = K.realpath target;
      _ = B.command ["/bin/cp","{leaf}/leaf.fpr","{here}/../entry.S",out];
      _ = B.inDirectory out [] ["sol","{leaf}/build.sol",compiler,"{leaf}/../apps"];
      archive = "{board}/docs/evidence/2026-10-30-structural";
      _ = B.inDirectory out [] ["/bin/sh","-c","gzip -dc \"$0\" > observed.v","{archive}/generated/observed-cpu.v.gz"];
      _ = B.inDirectory out [] ["/usr/bin/tar","-xzf","{archive}/baseline-sources.tar.gz","sdram/pipeline_cache.v","sdram/burst_memory.v","sdram/sdram.v"];
      _ = B.inDirectory out [] ["/bin/cp","sdram/pipeline_cache.v","cache.sv"];
      _ = B.inDirectory out [] ["riscv64-unknown-elf-gcc","-march=rv32im","-mabi=ilp32","-nostdlib","-mno-relax","-Ttext=0","{here}/rom.S","-o","rom.elf"];
      _ = B.inDirectory out [] ["riscv64-unknown-elf-objcopy","-j",".text","-O","binary","rom.elf","rom.bin"];
      _ = List.map (fn p -> (name, expected) = p; K.check "{name} is not the pinned source" (K.sha256 "{out}/{name}" == expected)) pinned;
      _ = hexWords out "rom.bin" "rom.hex";
      _ = hexWords out "leaf.bin" "image.hex";
      _ = B.inDirectory out [] ["verilator","--binary","--timing","-j","4","-Wno-fatal","--top","tb","+1364-2005ext+v","observed.v","cache.sv","sdram/sdram.v","sdram/burst_memory.v","{here}/trace.sv"];
      _ = K.mkdirs "{out}/runs";
      _ = List.map (fn stack -> List.map (fn mode -> List.map (simulate out stack mode) ["0","1"]) modes) stacks;
      result = K.commandIn out ["sol","{here}/analyse.sol"];
      _ = K.writeText "{out}/result.json" result;
      print result
  | _ -> error "usage: sol run.sol NEW_OUTPUT".
