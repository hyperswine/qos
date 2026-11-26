# Build the same process at two bases; mkqa validates every relocation.
# rv64 (QEMU virt) by default; rv32 builds for virt32 (raw FP-RISC units
# lower to rv64 only, so rv32 links their C stand-ins).
RT = use "native-rt".
ABI = use "native-abi".
output argv = ProcessResult status out err = unwrap (Proc.runNow (ProcessSpec argv "" [] "" 0));
  if status == 0 then Str.trim out else error "{argv}: {err}".
link extra env fpr root layout assembly units base elf xlen =
  flags = List.concat [["riscv64-unknown-elf-gcc",layout], ABI.archFlags xlen, ["-mcmodel=medany","-ffixed-x27","-DFPR_NHARTS=1",
    "-ffreestanding","-nostdlib","-nostartfiles","-O2","-Wl,--defsym=PROC_IMAGE_BASE={base}","-Wl,--emit-relocs","-Wl,--no-relax",
    "-Wl,--no-warn-rwx-segments","-Wl,--defsym=_heap_start=_proc_image_end","-Wl,--defsym=_heap_end=_proc_image_end",
    "-Wl,--defsym=_proc_arena_end=_proc_image_end","-T","{fpr}/machine/virt/link-app.ld","-I{fpr}/runtime","-I{fpr}/machine/virt"]];
  RT.command env (List.concat [flags,extra,RT.rtProcessApp fpr root "hal" "build" xlen,[assembly],units,["-lgcc","-o",elf]]).
solCommand = (case unwrap (Env.get "SOL") of EnvText path -> path | EnvMissing -> "sol").
build app manifest archive extra xlen =
  fpr = (case unwrap (Env.get "FPRISC_ROOT") of EnvText path -> path | EnvMissing -> error "set FPRISC_ROOT to the FP-RISC checkout");
  root = output ["pwd","-P"];
  env = [("FPR_HOME",root),("FPR_PATH",fpr),("FPR_FOREIGN","{root}/core/foreign.fpr")];
  layout = ABI.cellLayoutFlag;
  name = output ["basename",app,".fpr"]; prefix = "build/{name}"; assembly = "{prefix}.s";
  _ = RT.prepare env solCommand fpr root "hal" "build" xlen;
  _ = RT.command (("LC_ALL","C.UTF-8") :: env) ["{fpr}/fpr","--target=rv{xlen}","--prelude={fpr}/core/prelude.fpr",app,assembly];
  units = Str.lines (readPath "{assembly}.units");
  _ = link extra env fpr root layout assembly units "0" "{prefix}.elf" xlen;
  _ = link extra env fpr root layout assembly units "0x10000000" "{prefix}.moved.elf" xlen;
  case ABI.versionsFor fpr xlen of
    [native,actors,memory] -> RT.command env [solCommand,"tools/qa-pack.sol","native",manifest,"{prefix}.elf","{prefix}.moved.elf","268435456",archive,native,actors,memory]
  | _ -> error "expected native, actors and memory ABI versions".
> case args Unit of [app,manifest,out] -> build app manifest out [] 64
  | [app,manifest,out,"rv64"] -> build app manifest out [] 64
  | [app,manifest,out,"rv32"] -> build app manifest out [] 32
  | app :: manifest :: out :: "rv32" :: "--" :: extra -> build app manifest out extra 32
  | app :: manifest :: out :: "--" :: extra -> build app manifest out extra 64
  | [_,_,_,_] -> error "native process images are rv64 or rv32"
  | _ -> error "usage: build-process-app APP MANIFEST OUT [rv64 | rv32] [-- LINK_INPUT...]".
