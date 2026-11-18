# Build the same process at two bases; mkqa validates every relocation.
# rv64 (QEMU virt) by default; rv32 builds for virt32 (raw FP-RISC units
# lower to rv64 only, so rv32 links their C stand-ins).
HAL = use "virt-hal".
ABI = use "native-abi".
command env argv = status = unwrap (Proc.streamNow (ProcessSpec argv "" env "" 0));
  if status == 0 then Unit else error "exit {status}: {argv}".
output argv = ProcessResult status out err = unwrap (Proc.runNow (ProcessSpec argv "" [] "" 0));
  if status == 0 then Str.trim out else error "{argv}: {err}".
runtime fpr xlen = virt = "{fpr}/machine/virt"; rt = "{fpr}/runtime";
  raw = (if xlen == 32 then ["{virt}/rawunit.c","hal/virt/virtio32.c"]
         else ["build/virt-clint.s","{virt}/rawunit.c","build/qos-plic.s","build/qos-virtio.s","build/qos-blockpolicy.s","build/qos-netpolicy.s"]);
  List.append (List.append raw ["hal/virt/plic.c","hal/virt/pins.c","hal/core/lifecycle.c","build/board-{board xlen}/devtable.c",
    "qos/native/proc_entry.c","{virt}/ctx.S","{virt}/ctx_fab.c","{rt}/runtime.c","{rt}/i32.c","{virt}/hal.c","{virt}/memshim.c"])
    (List.map (fn name -> "{rt}/{name}.c") ["actors","buddy","mod","bits","vec","sstr"]).
board xlen = if xlen == 32 then "virt32" else "virt".
link extra env fpr layout assembly units base elf xlen =
  flags = List.concat [["riscv64-unknown-elf-gcc",layout], ABI.archFlags xlen, ["-mcmodel=medany","-ffixed-x27","-DFPR_NHARTS=1",
    "-ffreestanding","-nostdlib","-nostartfiles","-O2","-Wl,--defsym=PROC_IMAGE_BASE={base}","-Wl,--emit-relocs","-Wl,--no-relax",
    "-Wl,--no-warn-rwx-segments","-Wl,--defsym=_heap_start=_proc_image_end","-Wl,--defsym=_heap_end=_proc_image_end",
    "-Wl,--defsym=_proc_arena_end=_proc_image_end","-T","{fpr}/machine/virt/link-app.ld","-I{fpr}/runtime","-I{fpr}/machine/virt"]];
  boardSources = List.filter (fn l -> l != "") (Str.lines (readPath "build/board-{board xlen}/sources.txt"));
  command env (List.concat [flags,extra,runtime fpr xlen,boardSources,[assembly],units,["-lgcc","-o",elf]]).
solCommand = (case unwrap (Env.get "SOL") of EnvText path -> path | EnvMissing -> "sol").
buildClint env fpr =
  virt = "{fpr}/machine/virt"; driver = "{virt}/build-clint.sol";
  ProcessResult present _ _ = unwrap (Proc.runNow (ProcessSpec ["test","-f",driver] "" [] "" 0));
  case present of
    0 -> command env [solCommand,driver,"{fpr}/fpr","{virt}/clint.fpr","build/virt-clint.s"]
  | 1 -> command env ["make","-s","-f","{virt}/virt.mk","FPRC={fpr}/fpr","BUILD=build","VIRT_MACHINE={fpr}/machine","build/virt-clint.s"]
  | _ -> error "cannot check for {driver}".
compileHal env fpr = _ = List.map (HAL.compile env "{fpr}/fpr" "hal" "build") ["plic","virtio","blockpolicy","netpolicy"]; Unit.
build app manifest archive extra xlen =
  fpr = (case unwrap (Env.get "FPRISC_ROOT") of EnvText path -> path | EnvMissing -> error "set FPRISC_ROOT to the FP-RISC checkout");
  root = output ["pwd","-P"];
  env = [("FPR_HOME",root),("FPR_PATH",fpr),("FPR_FOREIGN","{root}/core/foreign.fpr")];
  layout = ABI.cellLayoutFlag;
  name = output ["basename",app,".fpr"]; prefix = "build/{name}"; assembly = "{prefix}.s";
  _ = command env ["mkdir","-p","build"];
  _ = command (("LC_ALL","C.UTF-8") :: env) ["{fpr}/fpr","--target=rv{xlen}","--prelude={fpr}/core/prelude.fpr",app,assembly];
  _ = (if xlen == 64 then buildClint env fpr else Unit);
  # the board's device table and the class and driver sources (tools/board.sol)
  _ = command env [solCommand,"tools/board.sol","bsp/{board xlen}/board.json","build/board-{board xlen}"];
  _ = (if xlen == 64 then compileHal env fpr else Unit);
  units = Str.lines (readPath "{assembly}.units");
  _ = link extra env fpr layout assembly units "0" "{prefix}.elf" xlen;
  _ = link extra env fpr layout assembly units "0x10000000" "{prefix}.moved.elf" xlen;
  case ABI.versionsFor fpr xlen of
    [native,actors,memory] -> command env [solCommand,"tools/qa-pack.sol","native",manifest,"{prefix}.elf","{prefix}.moved.elf","268435456",archive,native,actors,memory]
  | _ -> error "expected native, actors and memory ABI versions".
> case args Unit of [app,manifest,out] -> build app manifest out [] 64
  | [app,manifest,out,"rv64"] -> build app manifest out [] 64
  | [app,manifest,out,"rv32"] -> build app manifest out [] 32
  | app :: manifest :: out :: "rv32" :: "--" :: extra -> build app manifest out extra 32
  | app :: manifest :: out :: "--" :: extra -> build app manifest out extra 64
  | [_,_,_,_] -> error "native process images are rv64 or rv32"
  | _ -> error "usage: build-process-app APP MANIFEST OUT [rv64 | rv32] [-- LINK_INPUT...]".
