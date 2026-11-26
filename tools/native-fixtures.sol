# Run QOS Native test kernels on QEMU virt (rv64) and check their expected line.
#
#   sol tools/native-fixtures.sol NAME...        from the QOS root, e.g. blockrange disknative
#
# Each tests/NAME.fpr stands in for system.fpr (`make -C qos native SYSTEM=...`),
# boots with a freshly seeded 8 MiB QLog disk on virtio-blk, and passes when its
# output holds the text of its `#: expect ...` header line and no PANIC or FAILED;
# `#: cflags ...` passes test-only switches (NATIVE_CFLAGS_EXTRA). FPRISC_ROOT names the
# FP-RISC checkout (default ../fprisc). Kernels and disks go to a scratch
# directory, each with its own build directory. Prints PASS/FAIL per fixture and
# fails if any did.
unsafe program.
B = use "sol/lib/build".
header key text = pre = "#: {key} ";
  case List.filter (fn l -> Str.startsWith pre l) (Str.lines text) of
    l :: _ -> Str.trim (Str.slice l (Str.len pre) (Str.len l))
  | [] -> "".
runOne root work env name =
  src = "{root}/tests/{name}.fpr";
  text = readPath src;
  want = header "expect" text;
  cflags = header "cflags" text;
  kernel = "{work}/{name}.elf"; disk = "{work}/{name}.img";
  buildEnv = [("SYSTEM",src),("BUILD","{work}/build-{name}"),("NATIVE_CFLAGS_EXTRA",cflags)] + env;
  build = Proc.runNow (ProcessSpec [B.setting "SOL" "sol","{root}/tools/build-native.sol",kernel,"rv64"] "" buildEnv "" 0);
  case build of
    Ok (ProcessResult 0 _ _) ->
      _ = B.runWith env [B.setting "SOL" "sol","{root}/tools/mkdisk.sol",disk,"8"];
      qemu = ["qemu-system-riscv64","-accel","tcg,thread=multi","-machine","virt","-smp","2","-m","256M","-nographic","-bios","none",
              "-kernel",kernel,"-drive","file={disk},if=none,format=raw,id=hd0","-device","virtio-blk-device,drive=hd0"];
      stage = ProcessSpec qemu "" [] "" 0;
      spec = PipelineSpec [stage] (PipeBytes (Bytes.empty Unit)) (PipeCapture 4194304) (PipeCapture 1048576) 90000 PipeFail;
      out = case Proc.pipeline spec of
          Ok (PipelineResult _ _ o _) -> (case Utf8.decode o of Ok s -> s | Err _ -> "")
        | Err why -> "{why}";
      ok = want != "" and Str.contains want out and not (Str.contains "PANIC" out) and not (Str.contains "FAILED" out);
      _ = print (if ok then "PASS {name}" else "FAIL {name}: expected \"{want}\"\n{Str.slice out (Numeric.max 0 (Str.len out - 600)) (Str.len out)}");
      ok
  | Ok (ProcessResult code o e) -> _ = print "FAIL {name}: kernel build exit {code}\n{Str.slice (o + e) (Numeric.max 0 (Str.len (o + e) - 800)) (Str.len (o + e))}"; False
  | Err why -> _ = print "FAIL {name}: {why}"; False.
> root = B.query ["/bin/pwd","-P"];
  _ = (if B.exists "-f" "{root}/tools/native-fixtures.sol" then Unit else error "run from the QOS root");
  names = args Unit;
  _ = (if names == [] then error "usage: sol tools/native-fixtures.sol NAME..." else Unit);
  fprisc = B.setting "FPRISC_ROOT" "{root}/../fprisc";
  env = [("FPRISC_ROOT",fprisc),("FPR_HOME",root),("FPR_PATH",fprisc)];
  work = B.query ["mktemp","-d","/tmp/qos-native-fixtures.XXXXXX"];
  results = List.map (runOne root work env) names;
  failed = List.len (List.filter (fn r -> not r) results);
  _ = B.command ["rm","-rf",work];
  if failed == 0 then print "native fixtures: {List.len names} passed" else error "native fixtures: {failed} of {List.len names} failed".
