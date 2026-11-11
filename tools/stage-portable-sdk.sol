# stage-portable-sdk.sol -- contributor packaging step: stage a native binary
# QOS Portable SDK (no rebuilding of the compiler, hosts or Main).
#
#   sol tools/stage-portable-sdk.sol --fprisc ../fprisc-pin --compiler FPR \
#     --profile PROFILE --lld LD.LLD --output PREFIX
#
# Run from inside the QOS checkout. The installed `qos` command is FP-RISC
# (tools/qos/), compiled here by the SDK's own compiler and runtime, so the
# SDK ships no Python. It needs Clang on PATH, and lld unless --lld gives the
# static ld.lld the SDK ships (tools/build-sdk-lld.sh). --profile supplies the
# matching prebuilt Main and apps; the hosts come from this tree's qos/qosp
# and qos/qosp-gl, built beforehand.
K = use "sdk/sdk".
J = use "sol/lib/json".
CLI = use "sol/lib/cli".

api = "qos.desktop/2".
session = "qos.app-session/6".

options = [CLI.Option "fprisc" "" CLI.One, CLI.Option "compiler" "" CLI.One, CLI.Option "output" "" CLI.One,
           CLI.Option "profile" "" CLI.One, CLI.Option "lld" "" CLI.One].

machine u = case K.trimEnd (K.command ["/usr/bin/uname", "-m"]) of
    "arm64" -> "aarch64"
  | "aarch64" -> "aarch64"
  | "x86_64" -> "x86_64"
  | m -> error "this SDK does not support {m}".
system u = case K.trimEnd (K.command ["/usr/bin/uname", "-s"]) of
    "Darwin" -> "darwin"
  | "FreeBSD" -> "freebsd"
  | _ -> "linux".

# Library sources and committed blobs: .fpr, .txt and versions.db files.
# No .git, .hs, makefiles or runtime C build is installed.
modules : unsafe String -> String -> Unit .
modules from to = if K.exists from then
    List.fold (fn u name -> K.copy "{from}/{name}" "{to}/{name}") Unit
      (List.filter (fn name -> K.suffix name == ".fpr" or K.suffix name == ".txt" or K.baseName name == "versions.db") (K.files from))
  else Unit.

# kind = "app" build inputs (docs/2026-11-01-SDK-PROCESS-APPS.md): private,
# hashed, never a public interface. Installed path -> source path. The runtime
# C and context switch come from the same FP-RISC tree as the compiler, so an
# image never mixes two releases.
platformSources root fprisc =
  List.map (fn n -> ("appside/{n}", "{root}/qos/appside/{n}")) ["entry.c", "hal.c", "support.c", "qos_abi.h", "link-qosapp-a64.ld"]
  + [("store_abi.h", "{root}/qos/store_abi.h"),
     ("portable/sha256.c", "{root}/qos/portable/sha256.c"),
     ("loader/qaimg.c", "{root}/loader/qaimg.c"),
     ("hal/net_actor_bridge.c", "{root}/hal/net_actor_bridge.c"),
     ("machine/unix/ctx_a64.S", "{fprisc}/machine/unix/ctx_a64.S")]
  + List.map (fn n -> ("runtime/{n}", "{fprisc}/runtime/{n}"))
      ["runtime.c", "i32.c", "actors.c", "bits.c", "vec.c", "sstr.c", "mod.c", "buddy.c", "fpr.h", "i32.h", "vec_layout.h"].

# tools/qos/qos.fpr + host.c -> the SDK's `qos` binary, built by the SDK's
# own compiler with the FP-RISC tree it comes from
buildCommand root compiler fprisc destination extra =
  _ = K.mkdirs (K.parent destination);
  K.commandIn "{root}/tools/qos" (["/usr/bin/env", "-u", "GHCRTS", "-u", "FPR_PATH", "-u", "FPR_FOREIGN", "-u", "FPRISC_ROOT",
    "FPR_HOME={fprisc}", "FPR_NO_RUN_CACHE=1",
    compiler, "build", "{root}/tools/qos/qos.fpr", "--with", "{root}/tools/qos/host.c", "-o", destination] + extra).

# a linker that loads anything outside the system is refused
systemOnly path = List.all (fn l -> Str.startsWith "/usr/lib/" (Str.trim l) or Str.startsWith "/System/" (Str.trim l))
  (List.drop 1 (K.lines (K.command ["/usr/bin/otool", "-L", path]))).

# the profile archives, each checked by the staged `qos inspect` as the
# packager and installer read them; -> (apps, files)
profile : unsafe String -> String -> (List String, List (String, String, String)) .
profile sdk abi = case List.filter (fn n -> K.suffix n == ".qa") (K.files "{sdk}/profile") of
  names ->
    checked = List.map (fn name ->
        main = if name == "main.qa" then ["--main"] else [];
        (sid, sha) = case Str.words (K.trimEnd (K.command (["{sdk}/tools/qos", "inspect", "{sdk}/profile/{name}", "--abi", abi] + main))) of
            [a, b] -> (a, b)
          | _ -> error "qos inspect: unexpected output for {name}";
        (name, sid, sha)) names;
    (List.filter (fn n -> n != "main.qa") names, checked).

opt parsed key = CLI.valueOr "" key parsed.

shipLinker root sdk lld =
  lldReal = K.realpath lld;
  _ = K.check "{lldReal} links libraries outside the system; build it with tools/build-sdk-lld.sh" (systemOnly lldReal);
  _ = K.copy lldReal "{sdk}/toolchain/ld.lld";
  _ = K.copy "{root}/packaging/llvm/LICENSE.TXT" "{sdk}/toolchain/LICENSE-LLVM.txt";
  [("ld.lld", J.JStr (K.sha256 "{sdk}/toolchain/ld.lld"))].

host root sdk abi name =
  info = K.need (J.parse (K.command ["{root}/qos/{name}", "--sdk-info"]));
  _ = K.check "{name} lacks matching ABI, disk lock or archive digest contract; rebuild the host"
        (K.textOr "" "abi" info == abi and K.field "diskLockContract" info == J.JNum 1 and K.field "archiveDigestContract" info == J.JNum 1);
  _ = K.copy "{root}/qos/{name}" "{sdk}/runtime/{name}";
  (name, J.JStr (K.sha256 "{sdk}/runtime/{name}")).

withProfile : unsafe String -> String -> String -> String -> String -> String -> J.Json -> J.Json .
withProfile root compiler fprisc sdk profileDir abi meta0 =
  _ = List.fold (fn u name -> K.copy "{profileDir}/{name}" "{sdk}/profile/{name}") Unit
        (List.filter (fn n -> K.suffix n == ".qa" and Str.contains "/" n == False) (K.files profileDir));
  (apps, files) = profile sdk abi;
  digest = case List.filter (fn row -> (n, _, _) = row; n == "main.qa") files of
      [(_, _, h)] -> h
    | _ -> error "missing inspected Main digest";
  plugins = List.fold (fn acc row -> (n, sid, h) = row;
      if n == "main.qa" then acc else "{acc}{sid}:{h}|") "|" files;
  _ = buildCommand root compiler fprisc "{sdk}/tools/qos" ["--cflag", "-DQOS_VERIFIED_MAIN=\"{digest}:{abi}\"", "--cflag", "-DQOS_VERIFIED_PLUGINS=\"{plugins}\""];
  hosts = List.map (fn name -> host root sdk abi name) ["qosp", "qosp-gl"];
  case meta0 of
    J.JObj kvs -> J.JObj (kvs + [("profileFiles", J.JObj (List.map (fn p -> (n, _, h) = p; (n, J.JStr h)) files)),
                                 ("profileApps", J.JArr (List.map J.JStr apps)),
                                 ("runtimeFiles", J.JObj hosts), ("diskLockContract", J.JNum 1), ("archiveDigestContract", J.JNum 1)])
  | other -> other.

main : unsafe Unit .
main = parsed = K.need (CLI.parse options (args Unit));
  _ = K.check "--fprisc and --output are required" (opt parsed "fprisc" != "" and opt parsed "output" != "");
  root = K.trimEnd (K.command ["/usr/bin/git", "rev-parse", "--show-toplevel"]);
  _ = K.check "run from inside the QOS checkout" (K.isFile "{root}/tools/stage-portable-sdk.sol");
  prefix = opt parsed "output";
  _ = K.check "output already exists; use a fresh prefix" (K.exists prefix == False);
  fprisc = K.realpath (opt parsed "fprisc");
  compiler = K.realpath (if opt parsed "compiler" == "" then "{fprisc}/fpr" else opt parsed "compiler");
  _ = K.check "build the compiler before staging" (K.isFile compiler);
  arch = machine Unit;
  profileDir = opt parsed "profile";
  _ = K.check "profile must contain a prebuilt main.qa" (profileDir == "" or K.isFile "{profileDir}/main.qa");
  _ = K.mkdirs "{prefix}/libexec/qos-portable";
  prefixReal = K.realpath prefix;
  sdk = "{prefixReal}/libexec/qos-portable";
  _ = K.copy compiler "{sdk}/compiler/fpr";
  _ = K.copy "{fprisc}/LICENSE" "{sdk}/compiler/LICENSE";
  _ = List.fold (fn u folder -> modules "{fprisc}/{folder}" "{sdk}/compiler/{folder}") Unit ["core", "std", ".fpr"];
  _ = List.fold (fn u folder -> modules "{root}/{folder}" "{sdk}/modules/{folder}") Unit ["core", "std", "programs/mods", ".fpr"];
  _ = modules "{root}/sdk" "{sdk}/modules";
  _ = List.fold (fn u name -> K.copy "{root}/tools/{name}" "{sdk}/tools/{name}") Unit ["desktop-adapter.fpr.in", "desktop-counter.fpr"];
  _ = buildCommand root compiler fprisc "{sdk}/tools/qos" [];
  lld = opt parsed "lld";
  toolchain = if lld == "" then [] else shipLinker root sdk lld;
  _ = K.copy "{root}/qos/appside/link-qosplug.ld" "{sdk}/support/link-qosplug.ld";
  platform = List.map (fn p -> (name, source) = p;
      _ = K.check "platform input missing: {source}" (K.isFile source);
      _ = K.copy source "{sdk}/platform/{name}";
      (name, K.sha256 "{sdk}/platform/{name}")) (K.sortBy (fn p -> (name, _) = p; name) (platformSources root fprisc));
  abi = K.defineOf "QOS_ABI_VERSION" (K.readText "{root}/qos/appside/qos_abi.h");
  codegen = K.bindingOf "codegenRev" (K.readText "{fprisc}/compiler/Codegen.hs");
  dependencies = if toolchain == [] then ["Clang (ELF assembler)", "lld (ELF linker)"] else ["Clang (ELF assembler)"];
  meta0 = J.JObj ([("format", J.JNum 1), ("abi", J.JStr "{abi}.{codegen}"), ("desktopApi", J.JStr api),
      ("desktopSession", J.JStr session), ("architecture", J.JStr arch), ("os", J.JStr (system Unit)),
      ("portableAbi", J.JStr abi), ("compilerSha256", J.JStr (K.sha256 compiler)),
      ("qosRevision", J.JStr (K.revision root)), ("fpriscRevision", J.JStr (K.revision fprisc)),
      ("qosDirty", J.JBool (K.dirty root)), ("fpriscDirty", J.JBool (K.dirty fprisc)),
      ("dependencies", J.JArr (List.map J.JStr dependencies)),
      ("platformFiles", J.JObj (List.map (fn p -> (n, h) = p; (n, J.JStr h)) platform)),
      ("platformSha256", J.JStr (K.platformDigest platform))]
    + (if toolchain == [] then [] else [("toolchainFiles", J.JObj toolchain),
        ("toolchainLld", J.JStr (K.trimEnd (K.command ["{sdk}/toolchain/ld.lld", "--version"])))]));
  meta = if profileDir == "" then meta0 else withProfile root compiler fprisc sdk profileDir "{abi}.{codegen}" meta0;
  _ = K.writeJson "{sdk}/sdk.json" meta;
  # Since 0.2.0 the package exports only `qos`; since 0.3.0 it is the native
  # command beside the private, hash-matched compiler.
  _ = K.mkdirs "{prefixReal}/bin";
  _ = K.symlink "../libexec/qos-portable/tools/qos" "{prefixReal}/bin/qos";
  # a hash inventory lets release packaging verify the exact staged inputs
  _ = K.writeJson "{sdk}/files.sha256.json" (K.inventory sdk);
  print "Staged {prefixReal}; SDK requires {if toolchain == [] then "Clang and lld" else "Clang"} on PATH".
