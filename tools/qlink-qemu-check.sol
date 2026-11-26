# The qlink device classes on QEMU virt (board bsp/virt-qlink), driven by
# tools/qhost over QEMU's UART0 socket.
#
#   sol tools/qlink-qemu-check.sol          (from the QOS root)
#
# Two checks, each on a fresh 8 MiB QLog disk with two harts:
#   devices   tests/qlinkdevs.fpr: the host clock, a host file read and write,
#             a refused ".." path, a tone and a key press/release
#   system    System.qa with con0 on qlink: the four permission prompts
#             answered through qhost, then the app launcher draws
# FPRISC_ROOT names the FP-RISC checkout (default ../fprisc). Prints PASS/FAIL
# per check and fails if either did.
unsafe program.
B = use "sol/lib/build".
q s = "'{s}'".
# boot a kernel with UART0 on a socket, run qhost against it, stop QEMU
session work kernel qhostArgs =
  disk = "{work}/disk.img";
  _ = B.command [B.setting "SOL" "sol","tools/mkdisk.sol",disk,"8"];
  sock = "{B.query ["mktemp","-d","/tmp/qlXXXX"]}/s";
  qemu = "qemu-system-riscv64 -accel tcg,thread=multi -machine virt -smp 2 -m 256M -nographic -bios none -kernel {q kernel} -drive file={q disk},if=none,format=raw,id=hd0 -device virtio-blk-device,drive=hd0 -serial unix:{sock},server -monitor none";
  script = "{qemu} >/dev/null 2>&1 & pid=$!; sleep 1.5; {q work}/qhost script unix:{sock} --wait 60 {qhostArgs} 2>&1; kill $pid 2>/dev/null; wait $pid 2>/dev/null; true";
  B.query ["/bin/sh","-c",script].
build root work env name system =
  kernel = "{work}/{name}.elf";
  buildEnv = [("QOS_BOARD","virt-qlink"),("SYSTEM",system),("BUILD","{work}/build-{name}")] + env;
  _ = B.runWith buildEnv [B.setting "SOL" "sol","{root}/tools/build-native.sol",kernel,"rv64"];
  kernel.
report name ok out = _ = print (if ok then "PASS {name}" else "FAIL {name}:\n{Str.slice out (Numeric.max 0 (Str.len out - 800)) (Str.len out)}"); ok.
devices root work env =
  kernel = build root work env "qlinkdevs" "{root}/tests/qlinkdevs.fpr";
  hroot = "{work}/hroot";
  _ = B.command ["mkdir","-p",hroot];
  _ = B.command ["/bin/sh","-c","printf 'hello from the host\\n' > {q hroot}/greeting.txt"];
  out = session work kernel "--root {q hroot} expect-tone 60 key 30 expect {q "qlinkdevs: key"} 30";
  wrote = if B.exists "-f" "{hroot}/from-qemu.txt" then readPath "{hroot}/from-qemu.txt" else "";
  report "devices" (Str.contains "qlinkdevs: key 30; HOLDS" out and wrote == "written by QEMU over qlink") out.
system root work env =
  kernel = build root work env "system" "{root}/programs/system.fpr";
  answers = "expect {q "keyboard (read) ?"} 60 send y expect {q "display (write) ?"} 20 send y expect {q "clock (read) ?"} 20 send y expect {q "apps (read) ?"} 20 send y expect {q "app launcher"} 30";
  out = session work kernel answers;
  report "system" (Str.contains "app launcher" out) out.
> root = B.query ["/bin/pwd","-P"];
  _ = (if B.exists "-f" "{root}/tools/qlink-qemu-check.sol" then Unit else error "run from the QOS root");
  fprisc = B.setting "FPRISC_ROOT" "{root}/../fprisc";
  env = [("FPRISC_ROOT",fprisc),("FPR_HOME",root),("FPR_PATH",fprisc)];
  work = B.query ["mktemp","-d","/tmp/qos-qlink-qemu.XXXXXX"];
  _ = B.command ["cc","-O2","-I{root}/hal/link","-o","{work}/qhost","{root}/tools/qhost/qhost.c","{root}/hal/link/qlink.c","-lm"];
  results = [devices root work env, system root work env];
  _ = B.command ["rm","-rf",work];
  failed = List.len (List.filter (fn r -> not r) results);
  if failed == 0 then print "qlink QEMU checks: 2 passed" else error "qlink QEMU checks: {failed} of 2 failed".
