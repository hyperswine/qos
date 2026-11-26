# Shared native RISC-V runtime, board, and HAL preparation for build-native and build-process-app.
HAL = use "virt-hal".

command env argv =
  status = unwrap (Proc.streamNow (ProcessSpec argv "" env "" 0));
  if status == 0 then Unit else error "exit {status}: {argv}".

board xlen = case Env.get "QOS_BOARD" of
    Ok (EnvText b) -> if b != "" then b else if xlen == 32 then "virt32" else "virt"
  | _ -> if xlen == 32 then "virt32" else "virt".

linesOf path = List.filter (fn l -> l != "") (List.map Str.trim (Str.lines (readPath path))).

buildClint env solCmd fpr buildDir =
  virt = "{fpr}/machine/virt"; driver = "{virt}/build-clint.sol";
  ProcessResult present _ _ = unwrap (Proc.runNow (ProcessSpec ["test", "-f", driver] "" [] "" 0));
  case present of
    0 -> command env [solCmd, driver, "{fpr}/fpr", "{virt}/clint.fpr", "{buildDir}/virt-clint.s"]
  | 1 -> command env ["make", "-s", "-f", "{virt}/virt.mk", "FPRC={fpr}/fpr", "BUILD={buildDir}", "VIRT_MACHINE={fpr}/machine", "{buildDir}/virt-clint.s"]
  | _ -> error "cannot check for {driver}".

compileHal env fpr halDir buildDir =
  _ = List.map (HAL.compile env "{fpr}/fpr" halDir buildDir) ["plic", "virtio", "blockpolicy", "netpolicy"];
  Unit.

prepare env solCmd fpr root halDir buildDir xlen =
  _ = command env ["mkdir", "-p", buildDir];
  _ = (if xlen == 64 then buildClint env solCmd fpr buildDir else Unit);
  _ = command env [solCmd, "{root}/tools/board.sol", "{root}/bsp/{board xlen}/board.json", "{buildDir}/board-{board xlen}"];
  if xlen == 64 then compileHal env fpr halDir buildDir else Unit.

boardSources buildDir xlen = linesOf "{buildDir}/board-{board xlen}/sources.txt".

virtHalSources fpr halDir buildDir xlen =
  raw = if xlen == 32 then ["{fpr}/machine/virt/rawunit.c", "{halDir}/virt/virtio32.c"]
        else ["{buildDir}/virt-clint.s", "{fpr}/machine/virt/rawunit.c",
              "{buildDir}/qos-plic.s", "{buildDir}/qos-virtio.s",
              "{buildDir}/qos-blockpolicy.s", "{buildDir}/qos-netpolicy.s"];
  List.concat [
    raw,
    ["{halDir}/virt/plic.c", "{halDir}/virt/pins.c", "{halDir}/core/lifecycle.c",
     "{buildDir}/board-{board xlen}/devtable.c"],
    boardSources buildDir xlen
  ].

rtVirtKernel fpr =
  virt = "{fpr}/machine/virt";
  ["{virt}/crt0.S", "{virt}/ctx.S", "{virt}/ctx_fab.c", "{virt}/hal.c", "{virt}/memshim.c"].

rtCoreKernel fpr actorsSrc =
  rt = "{fpr}/runtime";
  ["{rt}/runtime.c", actorsSrc, "{rt}/bits.c", "{rt}/vec.c", "{rt}/i32.c", "{rt}/mod.c", "{rt}/buddy.c"].

rtProcessApp fpr root halDir buildDir xlen =
  virt = "{fpr}/machine/virt"; rt = "{fpr}/runtime";
  raw = if xlen == 32 then ["{virt}/rawunit.c", "{halDir}/virt/virtio32.c"]
        else ["{buildDir}/virt-clint.s", "{virt}/rawunit.c",
              "{buildDir}/qos-plic.s", "{buildDir}/qos-virtio.s",
              "{buildDir}/qos-blockpolicy.s", "{buildDir}/qos-netpolicy.s"];
  List.concat [
    raw,
    ["{halDir}/virt/plic.c", "{halDir}/virt/pins.c", "{halDir}/core/lifecycle.c",
     "{buildDir}/board-{board xlen}/devtable.c",
     "{root}/qos/native/proc_entry.c", "{virt}/ctx.S", "{virt}/ctx_fab.c",
     "{rt}/runtime.c", "{rt}/i32.c", "{virt}/hal.c", "{virt}/memshim.c"],
    List.map (fn name -> "{rt}/{name}.c") ["actors", "buddy", "mod", "bits", "vec"],
    boardSources buildDir xlen
  ].
