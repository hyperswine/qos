# Native process images on QEMU virt, for either word size.
#
#   sol tools/native-image-check.sol [rv64|rv32]      (from the QOS root; rv64 default)
#
# Three test kernels, each on a fresh 8 MiB QLog disk seeded with the process
# images it loads (built by tools/build-process-app.sol for the same width):
#   image    tests/nativeimage.fpr: two processes at once, an image held while
#            a child runs and freed after, no images left, memory returned
#            (apps: tests/slowproc.fpr, tests/lingerproc.fpr)
#   refusal  tests/nativerefusal.fpr: a process's storage calls against a
#            full, dead and killed-mid-request storage actor, then a real
#            request, and a failing device primitive (apps: storeprobe, failproc)
#   width    tests/nativewidth.fpr: an image built for the OTHER width refused
# A kernel's `#: cflags ...` header line is passed as NATIVE_CFLAGS_EXTRA.
# rv32 builds the kernel with XLEN=32 for bsp/virt32 and runs it on
# qemu-system-riscv32. FPRISC_ROOT names the FP-RISC checkout (default
# ../fprisc). Prints PASS/FAIL per check and fails if any did.
unsafe program.
B = use "sol/lib/build".
image root work env xlen src id =
  out = "{work}/{id}.qa"; # mkdisk names the app after the file
  _ = B.runWith env [B.setting "SOL" "sol","{root}/tools/build-process-app.sol",src,"tests/{id}.toml",out,"rv{xlen}"];
  out.
header key text = pre = "#: {key} ";
  case List.filter (fn l -> Str.startsWith pre l) (Str.lines text) of
    l :: _ -> Str.trim (Str.slice l (Str.len pre) (Str.len l))
  | [] -> "".
kernel root work env xlen name =
  elf = "{work}/{name}-rv{xlen}.elf";
  cflags = header "cflags" (readPath "{root}/tests/{name}.fpr");
  board = if xlen == 32 then [("XLEN","32"),("QOS_BOARD","virt32")] else [];
  buildEnv = board + [("SYSTEM","{root}/tests/{name}.fpr"),("BUILD","{work}/build-{name}-rv{xlen}"),("NATIVE_CFLAGS_EXTRA",cflags)] + env;
  _ = B.runWith buildEnv [B.setting "SOL" "sol","{root}/tools/build-native.sol",elf,"rv{xlen}"];
  elf.
boot root work xlen name elf apps =
  disk = "{work}/{name}-rv{xlen}.img";
  _ = B.command (List.concat [[B.setting "SOL" "sol","{root}/tools/mkdisk.sol",disk,"8"], apps]);
  qemu = if xlen == 32 then "qemu-system-riscv32" else "qemu-system-riscv64";
  stage = ProcessSpec [qemu,"-accel","tcg,thread=multi","-machine","virt","-smp","2","-m","256M","-nographic","-bios","none",
    "-kernel",elf,"-drive","file={disk},if=none,format=raw,id=hd0","-device","virtio-blk-device,drive=hd0"] "" [] "" 0;
  spec = PipelineSpec [stage] (PipeBytes (Bytes.empty Unit)) (PipeCapture 4194304) (PipeCapture 1048576) 240000 PipeFail;
  case Proc.pipeline spec of
    Ok (PipelineResult _ _ o _) -> (case Utf8.decode o of Ok s -> s | Err _ -> "")
  | Err why -> "{why}".
report name out = ok = Str.contains "HOLDS" out and not (Str.contains "PANIC" out);
  _ = print (if ok then "PASS {name}" else "FAIL {name}:\n{Str.slice out (Numeric.max 0 (Str.len out - 600)) (Str.len out)}"); ok.
> root = B.query ["/bin/pwd","-P"];
  _ = (if B.exists "-f" "{root}/tools/native-image-check.sol" then Unit else error "run from the QOS root");
  xlen = case args Unit of [] -> 64 | ["rv64"] -> 64 | ["rv32"] -> 32 | _ -> error "usage: sol tools/native-image-check.sol [rv64|rv32]";
  other = if xlen == 32 then 64 else 32;
  fprisc = B.setting "FPRISC_ROOT" "{root}/../fprisc";
  env = [("FPRISC_ROOT",fprisc),("FPR_HOME",root),("FPR_PATH",fprisc)];
  work = B.query ["mktemp","-d","/tmp/qos-native-image.XXXXXX"];
  slow = image root work env xlen "tests/slowproc.fpr" "CkSlow";
  linger = image root work env xlen "tests/lingerproc.fpr" "CkLinger";
  probeDir = "{work}/probe"; failDir = "{work}/fail"; wideDir = "{work}/wide";
  _ = B.command ["mkdir","-p",probeDir,failDir,wideDir];
  probe = image root probeDir env xlen "tests/storeprobe.fpr" "CkSlow";
  failing = image root failDir env xlen "tests/failproc.fpr" "CkFail";
  wide = image root wideDir env other "tests/slowproc.fpr" "CkWide";
  results = [report "image" (boot root work xlen "nativeimage" (kernel root work env xlen "nativeimage") [slow,linger]),
             report "refusal" (boot root work xlen "nativerefusal" (kernel root work env xlen "nativerefusal") [probe,failing]),
             report "width" (boot root work xlen "nativewidth" (kernel root work env xlen "nativewidth") [wide])];
  _ = B.command ["rm","-rf",work];
  failed = List.len (List.filter (fn r -> not r) results);
  if failed == 0 then print "native image checks (rv{xlen}): 3 passed" else error "native image checks (rv{xlen}): {failed} of 3 failed".
