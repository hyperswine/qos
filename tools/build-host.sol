# Build the QOS Portable host (qosp, qosp-gl, qosp-es) directly in Sol.
K = use "sdk/sdk".

setting name fallback = case K.need (Env.get name) of
    EnvText value -> if value == "" then fallback else value
  | EnvMissing -> fallback.

tryCapture argv =
  ProcessResult status out _ = K.need (Proc.runNow (ProcessSpec argv "" [] "" 0));
  if status == 0 then Str.trim out else "".

invokeDir dir env argv =
  status = K.need (Proc.streamNow (ProcessSpec argv dir env "" 0));
  if status == 0 then Unit else Script.abort status.

resolveRoot =
  here = K.trimEnd (K.command ["pwd", "-P"]);
  envHome = setting "FPR_HOME" "";
  if envHome != "" and K.isFile "{envHome}/tools/build-host.sol" then K.realpath envHome
  else if K.isFile "{here}/tools/build-host.sol" then K.realpath here
  else if K.isFile "{here}/../tools/build-host.sol" then K.realpath "{here}/.."
  else error "run from QOS checkout or set FPR_HOME".

resolveFprisc root =
  configured = setting "FPRISC_ROOT"
    (if K.isFile "{root}/.installed" then "{root}/toolchain"
     else if K.isFile "{root}/fprisc.path" then Str.trim (K.readText "{root}/fprisc.path")
     else "{root}/../fprisc");
  K.realpath configured.

codegenRevFlag fprisc =
  path = "{fprisc}/compiler/Codegen.hs";
  if not (K.isFile path) then [] else
  matches = List.filter (fn l -> Str.startsWith "codegenRev = " l) (Str.lines (K.readText path));
  case matches of
    line :: _ -> (case Str.words (substr line 13 (Str.len line - 13)) of
        rev :: _ -> ["-DQOSP_CODEGEN_REV={rev}"]
      | [] -> [])
  | [] -> [].

qospSources mode =
  base = [
    "portable/host.c", "portable/sha256.c", "portable/haltab.c", "portable/store.c",
    "portable/compile.c", "portable/park.c",
    "../hal/unix/net_raw.c", "../hal/unix/blk_raw.c", "../hal/unix/hostlog.c",
    "../hal/unix/tty_raw.c", "../hal/unix/evdev_raw.c", "../hal/unix/mice_raw.c",
    "../hal/unix/snd_raw.c", "../loader/qaimg.c"
  ];
  if mode == "gl" or mode == "es" then base + ["../hal/unix/gfx.c"] else base.

withFlags srcs = List.concat (List.map (fn s -> ["--with", s]) srcs).
cflagArgs flags = List.concat (List.map (fn f -> ["--cflag", f]) flags).
linkArgs libs = List.concat (List.map (fn l -> ["--link", l]) libs).

buildHost mode outOverride =
  root = resolveRoot;
  fprisc = resolveFprisc root;
  fprc = "{fprisc}/fpr";
  os = K.trimEnd (K.command ["uname", "-s"]);
  arch = setting "QOSP_ARCH" (K.trimEnd (K.command ["uname", "-m"]));
  archCflags = if arch == "arm64" or arch == "aarch64"
    then ["-ffixed-x27", "-ffixed-x28", "-DFPR_HART_X28"] else [];
  layoutCflags = if setting "FPR_COMPACT_CELLS" "1" == "0" then ["-DFPR_LEGACY_CELLS"] else [];
  snd = if os == "Darwin" then
    {cflags = ["-DQOSP_SND_AQ"], libs = ["-framework", "AudioToolbox", "-framework", "CoreFoundation"]}
  else
    alsa = Str.words (tryCapture ["pkg-config", "--libs", "alsa"]);
    {cflags = if alsa == [] then [] else ["-DQOSP_SND_ALSA"], libs = alsa};
  gfx = if mode == "gl" then
    glfwC = Str.words (tryCapture ["pkg-config", "--cflags", "glfw3"]);
    glfwL = Str.words (tryCapture ["pkg-config", "--libs", "glfw3"]);
    glSys = if os == "Darwin" then ["-framework", "OpenGL", "-lpthread", "-lm"] else ["-lGL", "-lpthread", "-lm"];
    {cflags = ["-DQOSP_GFX", "-DFPR_DESKTOP_GL"] + glfwC, libs = glfwL + glSys}
  else if mode == "es" then
    esLibs = Str.words (setting "ES_GL_LIBS" "-lEGL -lGLESv2 -lpthread -lm");
    {cflags = ["-DQOSP_GFX"], libs = esLibs}
  else
    {cflags = [], libs = []};
  out = if outOverride != "" then outOverride
    else if mode == "gl" then setting "QOSP_GL_OUT" "qosp-gl"
    else if mode == "es" then setting "QOSP_ES_OUT" "qosp-es"
    else setting "QOSP_OUT" "qosp";
  srcs = qospSources mode;
  cflags = ["-DQOSP_HOST"] + codegenRevFlag fprisc + archCflags + layoutCflags +
           ["-I../hal/unix", "-Iappside", "-Iportable"] + snd.cflags + gfx.cflags;
  libs = gfx.libs + snd.libs;
  extra = Str.words (setting "FPRBUILD_EXTRA" "");
  env = [("FPRISC_ROOT", fprisc), ("FPR_HOME", fprisc), ("FPR_PATH", fprisc),
         ("FPR_FOREIGN", "{root}/core/foreign.fpr")];
  cmd = [fprc, "build", "portable/qosp.fpr", "-o", out, "--harts", "1"] +
        extra + withFlags srcs + cflagArgs cflags + linkArgs libs;
  invokeDir "{root}/qos" env cmd.

> case args Unit of
    [] -> buildHost "plain" ""
  | [mode] -> buildHost mode ""
  | [mode, out] -> buildHost mode out
  | _ -> error "usage: build-host.sol [plain|gl|es] [OUT]".
