# Build Portable apps (.qa) and plugins directly in Sol without Make.
# Drives fpr -> ccobj.sol -> 2-pass link -> mkexports/mkimports -> app-manifest -> qa-pack.
K = use "sdk/sdk".

setting name fallback = case K.need (Env.get name) of
    EnvText value -> if value == "" then fallback else value
  | EnvMissing -> fallback.

stem path = base = K.baseName path; suffix = K.suffix base; substr base 0 (Str.len base - Str.len suffix).

linesOf path = List.filter (fn l -> l != "") (List.map Str.trim (Str.lines (K.readText path))).

invoke env argv =
  status = K.need (Proc.streamNow (ProcessSpec argv "" env "" 0));
  if status == 0 then Unit else Script.abort status.

capture env argv =
  ProcessResult status out err = K.need (Proc.runNow (ProcessSpec argv "" env "" 0));
  if status == 0 then Str.trim out else error "exit {status}: {argv}\n{err}".

solCmd fprisc = case K.need (Env.get "SOL") of
    EnvText value -> if value != "" then [value] else [fprisc + "/fpr", "sol"]
  | EnvMissing -> [fprisc + "/fpr", "sol"].

resolveRoot =
  here = K.trimEnd (K.command ["pwd", "-P"]);
  envHome = setting "FPR_HOME" "";
  if envHome != "" and K.isFile "{envHome}/tools/build-checkout-app.sol" then K.realpath envHome
  else if K.isFile "{here}/tools/build-checkout-app.sol" then K.realpath here
  else error "run from QOS checkout or set FPR_HOME".

resolveFprisc root =
  configured = setting "FPRISC_ROOT"
    (if K.isFile "{root}/.installed" then "{root}/toolchain"
     else if K.isFile "{root}/fprisc.path" then Str.trim (K.readText "{root}/fprisc.path")
     else "{root}/../fprisc");
  K.realpath configured.

detectArch =
  override = setting "APP_HOST" "";
  if override != "" then override else
  m = K.trimEnd (K.command ["uname", "-m"]);
  if m == "arm64" or m == "aarch64" then "a64"
  else if m == "riscv64" then "rv64"
  else "x64".

slotBase =
  if K.trimEnd (K.command ["uname", "-s"]) == "Darwin" then "0x10000000000" else "0x400000000".

rv64Cc =
  override = setting "QOS_RV64_CC" "";
  if override != "" then override
  else if K.trimEnd (K.command ["uname", "-m"]) == "riscv64" then "gcc"
  else "riscv64-linux-gnu-gcc".

parseManifest assigns baseStem =
  lookup = fn key -> fn fallback ->
    prefix = key + "=";
    found = List.filter (fn s -> Str.startsWith prefix s) assigns;
    case found of
      [item] -> substr item (Str.len prefix) (Str.len item - Str.len prefix)
    | _ -> fallback;
  id = lookup "QA_ID" baseStem;
  name = lookup "QA_NAME" id;
  version = lookup "QA_VERSION" "1";
  {id = id, name = name, version = version}.

archSpec arch root fprisc =
  base = slotBase;
  if arch == "a64" then
    {name = "a64",
     appFlags = ["--target=qa64"],
     plugFlags = ["--target=qa64", "--plugin"],
     mkimp = "a64",
     ctx = "{fprisc}/machine/unix/ctx_a64.S",
     appLd = "{root}/qos/appside/link-qosapp-a64.ld",
     plugLd = "{root}/qos/appside/link-qosplug.ld",
     cc = ["clang", "--target=aarch64-none-elf", "-O2", "-Wall", "-Wextra",
           "-ffreestanding", "-nostdlib", "-nostartfiles", "-fno-stack-protector",
           "-fno-asynchronous-unwind-tables", "-fno-pic", "-ffixed-x18", "-ffixed-x27", "-ffixed-x28",
           "-DQOS_ARENA_BASE={base}ul"],
     appLink = ["-fuse-ld=lld", "-Wl,--emit-relocs",
                "-Wl,--defsym=_heap_start=_proc_image_end", "-Wl,--defsym=_heap_end=_proc_image_end"],
     plugLink = ["-fuse-ld=lld", "-nostdlib", "-nostartfiles", "-Wl,--emit-relocs"],
     abiCheck = "optional"}
  else if arch == "rv64" then
    {name = "rv64",
     appFlags = ["--system=qos-portable", "--target=qrv64"],
     plugFlags = ["--target=qrv64", "--plugin"],
     mkimp = "rv64",
     ctx = "{fprisc}/machine/unix/ctx_rv64.S",
     appLd = "{root}/qos/appside/link-qosapp-rv64.ld",
     plugLd = "{root}/qos/appside/link-qosplug-rv64.ld",
     cc = [rv64Cc, "-O2", "-Wall", "-Wextra", "-march=rv64gc", "-mabi=lp64d", "-mcmodel=medany",
           "-ffixed-x27", "-mno-relax", "-msmall-data-limit=0", "-ffreestanding", "-nostdlib",
           "-nostartfiles", "-static", "-no-pie", "-fno-pic", "-fno-pie", "-fno-builtin",
           "-fno-stack-protector", "-fno-asynchronous-unwind-tables"],
     appLink = ["-Wl,--no-relax", "-Wl,--emit-relocs", "-Wl,--build-id=none", "-Wl,-z,noexecstack",
                "-Wl,--defsym=_heap_start=_proc_image_end", "-Wl,--defsym=_heap_end=_proc_image_end"],
     plugLink = ["-Wl,--no-relax", "-Wl,--emit-relocs", "-Wl,--build-id=none", "-Wl,-z,noexecstack"],
     abiCheck = "required"}
  else
    {name = "x64",
     appFlags = ["--system=qos-portable"],
     plugFlags = ["--target=qx64", "--plugin"],
     mkimp = "x64",
     ctx = "{fprisc}/machine/unix/ctx_x64.S",
     appLd = "{root}/qos/appside/link-qosapp.ld",
     plugLd = "{root}/qos/appside/link-qosplug.ld",
     cc = ["gcc", "-O2", "-Wall", "-Wextra", "-ffreestanding", "-nostdlib", "-nostartfiles",
           "-static", "-fno-stack-protector", "-fno-asynchronous-unwind-tables", "-fno-pic", "-mcmodel=large"],
     appLink = ["-Wl,--emit-relocs", "-Wl,--build-id=none", "-Wl,-z,noexecstack",
                "-Wl,--defsym=_heap_start=_proc_image_end", "-Wl,--defsym=_heap_end=_proc_image_end"],
     plugLink = ["-Wl,--build-id=none", "-Wl,-z,noexecstack", "-Wl,--no-relax",
                 "-Wl,--emit-relocs", "-Wl,--no-warn-rwx-segments"],
     abiCheck = "optional"}.

rtCommon root fprisc =
  rt = "{fprisc}/runtime";
  ["{root}/qos/appside/entry.c", "{root}/qos/appside/hal.c", "{root}/qos/appside/support.c",
   "{rt}/runtime.c", "{rt}/i32.c", "{rt}/actors.c", "{rt}/bits.c", "{rt}/vec.c",
   "{rt}/mod.c", "{rt}/buddy.c", "{root}/loader/qaimg.c", "{root}/qos/portable/sha256.c"].

extraCflags =
  extra = Str.words (setting "QOSCFLAGS_EXTRA" "");
  if setting "FPR_COMPACT_CELLS" "1" == "0" then "-DFPR_LEGACY_CELLS" :: extra else extra.

buildApp source archive buildDir harts manifestArgs =
  root = resolveRoot;
  fprisc = resolveFprisc root;
  fprc = "{fprisc}/fpr";
  runner = solCmd fprisc;
  env = [("FPRISC_ROOT", fprisc), ("FPR_HOME", root), ("FPR_PATH", "{root}/programs:{fprisc}"),
         ("FPR_FOREIGN", "{root}/core/foreign.fpr"), ("FPRC", fprc), ("LC_ALL", "C.UTF-8")];
  _ = K.mkdirs buildDir;
  _ = K.mkdirs (K.parent archive);
  spec = archSpec detectArch root fprisc;
  nharts = if harts != "" then harts else setting "QOSHARTS" "8";
  slab = setting "QOSSLAB" "32768";
  stack = setting "QOSSTACK" "262144";
  objCache = setting "QOS_OBJ_CACHE" "{buildDir}/rtobj";
  asm = "{buildDir}/qosapp-{spec.name}.s";
  _ = invoke env ([fprc] + spec.appFlags + ["--prelude={fprisc}/core/prelude.fpr", source, asm]);
  units = linesOf "{asm}.units";
  ccFlags = spec.cc + [
    "-DFPR_POSIX", "-DFPR_QOSAPP", "-DFPR_NHARTS={nharts}",
    "-DFPR_SLAB_SZ={slab}", "-DFPR_STACK_SZ={stack}"
  ] + extraCflags + ["-I{fprisc}/runtime", "-I{root}/qos/appside", "-I{root}/hal"];
  sources = [asm] + units + rtCommon root fprisc + [spec.ctx];
  objsLine = capture env (runner + ["{root}/tools/ccobj.sol", "{root}/tools/ccobj-worker.sol", objCache] + ccFlags + ["--"] + sources);
  objs = Str.words objsLine;
  linkCmd = ccFlags + ["-T", spec.appLd] + spec.appLink + objs;
  preElf = "{buildDir}/qosapp-{spec.name}.pre.elf";
  expS = "{buildDir}/qosapp-{spec.name}-exports.s";
  baseElf = "{buildDir}/qosapp-{spec.name}.elf";
  movedElf = "{buildDir}/qosapp-{spec.name}.moved.elf";
  _ = invoke env (linkCmd + ["-Wl,--defsym=QOS_SLOT_BASE=0", "-Wl,--unresolved-symbols=ignore-all", "-o", preElf]);
  _ = invoke env (runner + ["{root}/tools/mkexports.sol", preElf, expS]);
  _ = invoke env (linkCmd + ["-Wl,--defsym=QOS_SLOT_BASE=0", expS, "-o", baseElf]);
  _ = invoke env (linkCmd + ["-Wl,--defsym=QOS_SLOT_BASE=0x10000000", expS, "-o", movedElf]);
  mf = parseManifest manifestArgs (stem source);
  genToml = "{buildDir}/qosapp-{spec.name}-gen.toml";
  _ = invoke env (runner + ["{root}/tools/app-manifest.sol", "{root}/qos/appside/qos_abi.h",
                            "{asm}.abirev", spec.abiCheck, genToml, mf.id, mf.name, mf.version]);
  _ = invoke env (runner + ["{root}/tools/qa-pack.sol", "process", genToml, baseElf, movedElf, "268435456", archive]);
  Unit.

buildPlugin source archive buildDir =
  root = resolveRoot;
  fprisc = resolveFprisc root;
  fprc = "{fprisc}/fpr";
  runner = solCmd fprisc;
  env = [("FPRISC_ROOT", fprisc), ("FPR_HOME", root), ("FPR_PATH", "{root}/programs:{fprisc}"),
         ("FPR_FOREIGN", "{root}/core/foreign.fpr"), ("FPRC", fprc), ("LC_ALL", "C.UTF-8")];
  _ = K.mkdirs buildDir;
  _ = K.mkdirs (K.parent archive);
  spec = archSpec detectArch root fprisc;
  pid = stem source;
  prefix = "{buildDir}/plug-{pid}-{spec.name}";
  asm = "{prefix}.s";
  _ = invoke env ([fprc] + spec.plugFlags + ["--prelude={fprisc}/core/prelude.fpr", source, asm]);
  units = linesOf "{asm}.units";
  linkBase = spec.cc + ["-T", spec.plugLd] + spec.plugLink;
  uElf = "{prefix}.u.elf";
  impS = "{prefix}.imp.s";
  baseElf = "{prefix}.elf";
  movedElf = "{prefix}.moved.elf";
  _ = invoke env (linkBase + ["-Wl,--defsym=PLUG_BASE=0", "-Wl,--unresolved-symbols=ignore-all", asm] + units + ["-o", uElf]);
  _ = invoke env (runner + ["{root}/tools/mkimports.sol", spec.mkimp, uElf, impS]);
  _ = invoke env (linkBase + ["-Wl,--defsym=PLUG_BASE=0", asm] + units + [impS, "-o", baseElf]);
  _ = invoke env (linkBase + ["-Wl,--defsym=PLUG_BASE=0x10000000", asm] + units + [impS, "-o", movedElf]);
  genToml = "{prefix}-gen.toml";
  _ = invoke env (runner + ["{root}/tools/app-manifest.sol", "plugin", "{root}/qos/appside/qos_abi.h",
                            "{asm}.abirev", genToml, pid]);
  _ = invoke env (runner + ["{root}/tools/qa-pack.sol", "plugin", genToml, baseElf, movedElf, "268435456", archive]);
  Unit.

plugins : unsafe String -> List String -> List String .
plugins directory pairs = case pairs of
    [] -> []
  | source :: archive :: rest ->
      _ = buildPlugin source archive directory;
      archive :: plugins directory rest
  | _ -> error "expected source and archive for each plugin".

> case args Unit of
    "plugins" :: directory :: diskTool :: image :: size :: pairs ->
      archives = plugins directory pairs;
      root = resolveRoot;
      fprisc = resolveFprisc root;
      invoke [("FPRISC_ROOT", fprisc), ("FPR_HOME", root), ("FPR_PATH", "{root}/programs:{fprisc}")]
             (solCmd fprisc + [diskTool, image, size] + archives)
  | ["plugin", source, archive, directory] ->
      buildPlugin source archive directory
  | "app" :: source :: archive :: directory :: harts :: manifest ->
      buildApp source archive directory harts manifest
  | _ -> error "expected app|plugin|plugins arguments".
