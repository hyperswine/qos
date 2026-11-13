baseTests = ["strprims", "bitrange", "longpanic", "killblocked", "deadmail", "autodrop2", "fixedheap", "sleepwake", "sleepwait", "taskstress", "mvufailure", "mvuscoped", "deadlines", "taskfailure", "mvudeadlines", "arenamigrate", "vecwide", "veccaps", "typedvector", "vecsimd_int", "bigheap", "overflow", "files"].
extraTests = ["fvec2", "fmath", "actors"].
benchmarks = ["fib", "sha", "pingpong", "xpingpong", "nbody", "vecread"].
applications = ["blockportable", "blocknamespace", "blocklifecyclep", "blockmemory", "filessvc", "filesshutdown", "qlogmemory", "gfxshare", "gfxmemory", "gfxsmoke", "gfxheadless", "guishell", "panemvu", "appsession", "appjobs", "appsessionmemory", "shelllayout", "portableshutdown", "qsys", "netactor", "netactorstart", "nettransport"].
plugins = ["plugmini", "plughello"].
command cwd argv =
  status = unwrap (Proc.streamNow (ProcessSpec argv cwd [] "" 0));
  if status == 0 then Unit else error "{argv} exited {status}".
program fpr out cc suite name =
  stem = (if suite == "bench/" then "bench-{name}" else name);
  extra = (if suite == "base/" and name == "taskfailure" then ["--with","tests/base/actorfail_probe.c"] else []);
  _ = command fpr (["./fpr","build","tests/{suite}{name}.fpr","-o","{out}/{stem}","--harts","4","--cc",cc] + extra);
  _ = (if suite == "bench/" then command fpr ["cp","tests/{suite}{name}.expected","{out}/{stem}.expected"] else Unit);
  print "built {suite}{name}".
archiveSource qos out target key source name =
  _ = command qos ["make","-s",target,"PROG={source}","{key}={out}/{name}.qa","BUILD={out}/build-{name}"];
  print "built qos/{name}".
archive qos out target key name = archiveSource qos out target key "tests/{name}.fpr" name.
runner cwd qos out cc = command cwd [cc,"-O2","-Wall","-Wextra","{qos}/tools/pi4/runner.c","-o","{out}/runner"].
eglHost cwd dir out cc =
  flags = "--cc {cc} --cflag -g --cflag -DQOS_BLK_TEST --cflag -DQOS_STORE_TEST";
  command cwd ["make","-s","-C",dir,"portable-es","QOSP_ES_OUT={out}/qosp-es","FPRBUILD_EXTRA={flags}","SND_FLAGS=-DQOSP_SND_ALSA","SND_LIBS=-lasound"].
compileBundle qos fpr out cc =
      _ = runner "" qos out cc;
      _ = eglHost "" "{qos}/qos" out cc;
      _ = print "built diagnostic EGL host";
      _ = List.map (program fpr out cc "base/") baseTests;
      _ = List.map (program fpr out cc "") extraTests;
      _ = List.map (program fpr out cc "bench/") benchmarks;
      _ = command fpr ["cp","tests/base/strprims.expected","{out}/strprims.expected"];
      _ = List.map (archive qos out "qos-app-a64" "QA_OUT") applications;
      _ = List.map (archive qos out "plugin-qa-a64" "PLUG_OUT") plugins;
      sol = (case unwrap (Env.get "SOL") of EnvText path -> path | EnvMissing -> "sol");
      command qos [sol,"tools/mkdisk.sol","{out}/qsys.disk","8","{out}/plugmini.qa","{out}/plughello.qa"].
