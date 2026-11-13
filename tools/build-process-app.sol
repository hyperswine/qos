# Build the same process at two bases; mkqa validates every relocation.
HAL = use "virt-hal".
ABI = use "native-abi".
command env argv = status = unwrap (Proc.streamNow (ProcessSpec argv "" env "" 0));
  if status == 0 then Unit else error "exit {status}: {argv}".
output argv = ProcessResult status out err = unwrap (Proc.runNow (ProcessSpec argv "" [] "" 0));
  if status == 0 then Str.trim out else error "{argv}: {err}".
runtime fpr = virt = "{fpr}/machine/virt"; rt = "{fpr}/runtime";
  List.append ["build/virt-clint.s","{virt}/rawunit.c","build/qos-plic.s","build/qos-virtio.s","build/qos-blockpolicy.s","build/qos-netpolicy.s",
    "hal/virt/plic.c","hal/virt/net.c","hal/net_actor_bridge.c","hal/virt/blk.c","hal/virt/pins.c","hal/virt/devices.c","hal/core/lifecycle.c",
    "qos/native/proc_entry.c","{virt}/ctx.S","{virt}/ctx_fab.c","{rt}/runtime.c","{rt}/i32.c","{virt}/hal.c","{virt}/memshim.c"]
    (List.map (fn name -> "{rt}/{name}.c") ["actors","buddy","mod","bits","vec","sstr"]).
link extra env fpr layout assembly units base elf =
  flags = ["riscv64-unknown-elf-gcc",layout,"-march=rv64imafdc_zicsr","-mabi=lp64","-mcmodel=medany","-ffixed-x27","-DFPR_NHARTS=1",
    "-ffreestanding","-nostdlib","-nostartfiles","-O2","-Wl,--defsym=PROC_IMAGE_BASE={base}","-Wl,--emit-relocs","-Wl,--no-relax",
    "-Wl,--no-warn-rwx-segments","-Wl,--defsym=_heap_start=_proc_image_end","-Wl,--defsym=_heap_end=_proc_image_end",
    "-Wl,--defsym=_proc_arena_end=_proc_image_end","-T","{fpr}/machine/virt/link-app.ld","-I{fpr}/runtime","-I{fpr}/machine/virt"];
  command env (List.concat [flags,extra,runtime fpr,[assembly],units,["-o",elf]]).
solCommand = (case unwrap (Env.get "SOL") of EnvText path -> path | EnvMissing -> "sol").
buildClint env fpr =
  virt = "{fpr}/machine/virt"; driver = "{virt}/build-clint.sol";
  ProcessResult present _ _ = unwrap (Proc.runNow (ProcessSpec ["test","-f",driver] "" [] "" 0));
  case present of
    0 -> command env [solCommand,driver,"{fpr}/fpr","{virt}/clint.fpr","build/virt-clint.s"]
  | 1 -> command env ["make","-s","-f","{virt}/virt.mk","FPRC={fpr}/fpr","BUILD=build","VIRT_MACHINE={fpr}/machine","build/virt-clint.s"]
  | _ -> error "cannot check for {driver}".
build app manifest archive extra =
  fpr = (case unwrap (Env.get "FPRISC_ROOT") of EnvText path -> path | EnvMissing -> error "set FPRISC_ROOT to the FP-RISC checkout");
  root = output ["pwd","-P"];
  env = [("FPR_HOME",root),("FPR_PATH",fpr),("FPR_FOREIGN","{root}/core/foreign.fpr")];
  layout = ABI.cellLayoutFlag;
  name = output ["basename",app,".fpr"]; prefix = "build/{name}"; assembly = "{prefix}.s";
  _ = command env ["mkdir","-p","build"];
  _ = command (("LC_ALL","C.UTF-8") :: env) ["{fpr}/fpr","--target=rv64","--prelude={fpr}/core/prelude.fpr",app,assembly];
  _ = buildClint env fpr;
  _ = List.map (HAL.compile env "{fpr}/fpr" "hal" "build") ["plic","virtio","blockpolicy","netpolicy"];
  units = Str.lines (readPath "{assembly}.units");
  _ = link extra env fpr layout assembly units "0" "{prefix}.elf";
  _ = link extra env fpr layout assembly units "0x10000000" "{prefix}.moved.elf";
  case ABI.versions fpr of
    [native,actors,memory] -> command env [solCommand,"tools/qa-pack.sol","native",manifest,"{prefix}.elf","{prefix}.moved.elf","268435456",archive,native,actors,memory]
  | _ -> error "expected native, actors and memory ABI versions".
> case args Unit of [app,manifest,out] -> build app manifest out []
  | [app,manifest,out,"rv64"] -> build app manifest out []
  | app :: manifest :: out :: "--" :: extra -> build app manifest out extra
  | [_,_,_,_] -> error "native process images are rv64"
  | _ -> error "usage: build-process-app APP MANIFEST OUT [rv64 | -- LINK_INPUT...]".
