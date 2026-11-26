# Build the QOS Native RISC-V kernel (qos-native.elf) directly in Sol.
K = use "sdk/sdk".
RT = use "native-rt".
ABI = use "native-abi".

setting name fallback = case K.need (Env.get name) of
    EnvText value -> if value == "" then fallback else value
  | EnvMissing -> fallback.

resolveRoot =
  here = K.trimEnd (K.command ["pwd", "-P"]);
  envHome = setting "FPR_HOME" "";
  if envHome != "" and K.isFile "{envHome}/tools/build-native.sol" then K.realpath envHome
  else if K.isFile "{here}/tools/build-native.sol" then K.realpath here
  else if K.isFile "{here}/../tools/build-native.sol" then K.realpath "{here}/.."
  else error "run from QOS checkout or set FPR_HOME".

resolveFprisc root =
  configured = setting "FPRISC_ROOT"
    (if K.isFile "{root}/.installed" then "{root}/toolchain"
     else if K.isFile "{root}/fprisc.path" then Str.trim (K.readText "{root}/fprisc.path")
     else "{root}/../fprisc");
  K.realpath configured.

solCmd fprisc = case K.need (Env.get "SOL") of
    EnvText value -> if value != "" then value else "{fprisc}/fpr sol"
  | EnvMissing -> "{fprisc}/fpr".

runSol fprisc env argv =
  case K.need (Env.get "SOL") of
    EnvText value -> if value != "" then RT.command env ([value] + argv)
                     else RT.command env (["{fprisc}/fpr", "sol"] + argv)
  | EnvMissing -> RT.command env (["{fprisc}/fpr", "sol"] + argv).

buildNative kernelOverride xlen =
  root = resolveRoot;
  fpr = resolveFprisc root;
  buildDir = setting "BUILD" "{root}/qos/build";
  systemSrc = setting "SYSTEM" "{root}/programs/system.fpr";
  kernel = if kernelOverride != "" then kernelOverride else setting "KERNEL" "{root}/qos/qos-native.elf";
  harts = setting "HARTS" "2";
  actorsSrc = setting "ACTORS_SRC" "{fpr}/runtime/actors.c";
  extraFlags = Str.words (setting "NATIVE_CFLAGS_EXTRA" "");
  testSrc = Str.words (setting "NATIVE_TEST_SRC" "");
  env = [("FPRISC_ROOT", fpr), ("FPR_HOME", root), ("FPR_PATH", fpr),
         ("FPR_FOREIGN", "{root}/core/foreign.fpr"), ("LC_ALL", "C.UTF-8")];
  solBin = case K.need (Env.get "SOL") of EnvText s -> if s != "" then s else "{fpr}/fpr" | EnvMissing -> "{fpr}/fpr";
  _ = RT.prepare env solBin fpr root "{root}/hal" buildDir xlen;
  qa0Dir = "{buildDir}/qa0";
  _ = RT.command env ["mkdir", "-p", qa0Dir];
  qapps = ["TUIAppLauncher", "TUINotes", "TUIClock", "HelloProc"];
  qas = List.map (fn name -> "{qa0Dir}/{name}.qa") qapps;
  _ = List.map (fn name -> runSol fpr env ["{root}/tools/qa-placeholder.sol", "{root}/apps/{name}.toml", "{qa0Dir}/{name}.qa"]) qapps;
  appsData = "{buildDir}/apps_data.c";
  _ = runSol fpr env (["{root}/tools/qa-registry.sol", appsData] + qas);
  sysAsm = "{buildDir}/system.s";
  targetFlags = if xlen == 32 then ["--target=rv32"] else [];
  _ = RT.command env (["{fpr}/fpr", "--system=qos-native"] + targetFlags + ["--prelude={fpr}/core/prelude.fpr", systemSrc, sysAsm]);
  units = RT.linesOf "{sysAsm}.units";
  cflags = [ABI.cellLayoutFlag] + ABI.archFlags xlen +
    ["-mcmodel=medany", "-ffixed-x27", "-DFPR_NHARTS={harts}",
     "-ffreestanding", "-nostdlib", "-nostartfiles", "-O2", "-Wall", "-Wextra",
     "-fno-builtin", "-fno-stack-protector", "-ffunction-sections", "-fdata-sections"] + extraFlags;
  linkInputs = List.concat [
    RT.rtVirtKernel fpr,
    RT.virtHalSources fpr "{root}/hal" buildDir xlen,
    [sysAsm], units,
    RT.rtCoreKernel fpr actorsSrc,
    ["{root}/loader/apps.c", appsData, "{root}/loader/qaimg.c", "{root}/loader/process.c", "{root}/qos/portable/sha256.c"],
    testSrc
  ];
  RT.command env (["riscv64-unknown-elf-gcc"] + cflags +
    ["-Wl,--gc-sections", "-T", "{fpr}/machine/virt/link.ld", "-I{fpr}/runtime", "-I{fpr}/machine/virt"] +
    linkInputs + ["-lgcc", "-o", kernel]).

> case args Unit of
    [] -> buildNative "" (parseInt (setting "XLEN" "64"))
  | [kernel] -> buildNative kernel (parseInt (setting "XLEN" "64"))
  | [kernel, "rv32"] -> buildNative kernel 32
  | [kernel, "rv64"] -> buildNative kernel 64
  | _ -> error "usage: build-native.sol [KERNEL] [rv64|rv32]".
