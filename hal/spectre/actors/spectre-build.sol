# The Spectre Native build steps, shared by build.sol (one actor probe) and
# boot/build-integrated.sol (the whole image). Every step runs in a scratch
# root that holds `src` (the pinned FP-RISC runtime and machine sources) and
# `atomic.c`, as the shell scripts these replace did.
unsafe program.
B = use "sol/lib/build".
cc = "riscv64-unknown-elf-gcc".
objcopy = "riscv64-unknown-elf-objcopy".
words text = List.filter (fn w -> w != "") (Str.split 32 (Str.trim text)).
extra = words (B.setting "EXTRA" "").
# the CPU clock the board C converts its timebase with (Spectre-54 or Spectre-84)
mhz = B.setting "SPECTRE_MHZ" "54".
flags march = List.append extra ["-march={march}","-DCORE_MHZ={mhz}","-mabi=ilp32","-mno-relax","-msmall-data-limit=0","-ffixed-x27","-DFPR_NHARTS=1",
  "-ffreestanding","-fno-builtin","-Os","-ffunction-sections","-fdata-sections","-Isrc/runtime","-Isrc/machine/virt"].
hal = ["-Dhal_mtime=spectre_raw_ticks","-Dhal_timer_arm=spectre_raw_arm","-Dhal_putc=unused_uart","-Dhal_poweroff=unused_poweroff"].
kernel runtime = List.append ["-nostdlib","-Wl,--gc-sections","-T","src/machine/tangnano20k/link.ld","src/machine/tangnano20k/crt0.S",
  "src/machine/virt/ctx.S","src/machine/virt/ctx_fab.c","src/machine/virt/memshim.c"]
  (List.append (List.map (fn name -> "src/runtime/{name}.c") runtime) ["hal.o"]).
base = ["runtime","actors","buddy","i32","sstr","vec"].
withMod = List.append base ["mod"].
sd board = ["-I{board}/boards/tangnano20k/c","{board}/boards/tangnano20k/c/sd.c"].
# the BLOCK class and its SD driver, from the QOS checkout QOS names
# (hal/classes/block.c, hal/drivers/sd_spi.c): vfs and boot name their volume
# in the device table and leave the primitives to the class
blockClass u = q = B.setting "QOS" "";
  if q == "" then error "set QOS to the QOS checkout (the vfs and boot images link hal/classes and hal/drivers)"
  else ["-I{q}/hal/classes","-I{q}/hal/drivers","{q}/hal/classes/block.c","{q}/hal/drivers/sd_spi.c"].
# SPECTRE_CONSOLE=qlink: the boot image's console runs over qlink (hal/link),
# for tools/qhost; raw (the default) keeps the plain UART prompt
consoleSources u = q = B.setting "QOS" "";
  if B.setting "SPECTRE_CONSOLE" "raw" == "qlink" then ["-DSPECTRE_QLINK","-I{q}/hal/link","{q}/hal/link/qlink_sruart.c"] else [].
# the boot image's device table and its class and driver sources, generated
# into ROOT/board-devices by tools/board.sol from the board manifest
boardDevices root = List.append ["{root}/board-devices/devtable.c"]
  (List.filter (fn l -> l != "") (Str.lines (readPath "{root}/board-devices/sources.txt"))).
# System.qa's own C: the loader and process images, the placeholder app
# registry (generated into ROOT/sysbuild by qos/Makefile), the lifecycle, and
# the RV32 PLIC and pin drivers shared with QEMU virt32
qosKernel root = q = B.setting "QOS" "";
  ["{q}/loader/apps.c","{root}/sysbuild/apps_data.c","{q}/loader/qaimg.c","{q}/loader/process.c",
   "{q}/qos/portable/sha256.c","{q}/hal/core/lifecycle.c","{q}/hal/virt/plic.c","{q}/hal/virt/pins.c"].
# the compilation units an FP-RISC compile listed beside its app.s, as paths from the root
units root dir = List.map (fn line -> if Str.startsWith "./" line then "{dir}/{Str.slice line 2 (Str.len line)}" else line)
  (List.filter (fn line -> line != "") (List.map Str.trim (Str.lines (readPath "{root}/{dir}/app.s.units")))).
# System.qa on an 8 MiB board: the runtime's memory sizes for big machines
# (64 KiB buddy blocks, 128 KiB first stacks, slabs to 256 KiB) leave about
# 96 blocks of a 6 MiB heap and run out at boot. Small blocks, first stacks
# that grow on demand, and slab sizes that leave room for the buddy header
# (a 64 KiB slab plus its header took a 128 KiB block):
smallMemory = ["-DFPR_BUDDY_MIN=4096","-DFPR_STACK_SZ=16376","-DFPR_SLAB_SZ=32760","-DFPR_SLAB_MIN=4088","-DFPR_MSG_SLAB_SZ=16376"].
link root march runtime rest stem = linkWith [] root march runtime rest stem.
linkWith more root march runtime rest stem =
  f = List.append (flags march) more;
  _ = B.inDirectory root [] (List.concat [[cc],f,hal,["-c","src/machine/virt/hal.c","-o","hal.o"]]);
  _ = B.inDirectory root [] (List.concat [[cc],f,kernel runtime,rest,["atomic.c","-lgcc","-o","{stem}.elf"]]);
  B.inDirectory root [] [objcopy,"-O","binary","{stem}.elf","{stem}.bin"].
# one target, in `root`; `board` is the Simple-Risc checkout (sd, vfs and boot need its SD driver)
target root board name =
  if name == "probe" then link root "rv32im_zicsr" base ["probe.c"] "probe"
  else if name == "idle" then link root "rv32im_zicsr" base ["-Wl,--wrap=hal_wfi","idle/idle.c"] "idle/idle"
  else if name == "uart" then link root "rv32im_zicsr" base ["-Wl,--wrap=hal_wfi","uart/uart.c"] "uart/uart"
  else if name == "sd" then link root "rv32im_zicsr" base (List.append (sd board) ["sd/storage.c"]) "sd/storage"
  else if name == "vfs" then link root "rv32im_zicsr" withMod (List.concat [sd board,blockClass Unit,["vfs/hal.c","vfs/app.s"],units root "vfs"]) "vfs/fs"
  else if name == "boot" then link root "rv32im_zicsr_zifencei" withMod (List.concat [sd board,boardDevices root,consoleSources Unit,["boot/hal.c","boot/app.s"],units root "boot"]) "boot/fs"
  else if name == "system" then (if B.setting "SPECTRE_CONSOLE" "raw" != "qlink" then error "the System.qa image needs SPECTRE_CONSOLE=qlink (its console is con0 on qlink)" else
    linkWith smallMemory root "rv32im_zicsr_zifencei" (List.append withMod ["bits"]) (List.concat [sd board,boardDevices root,consoleSources Unit,qosKernel root,["system/hal.c","system/app.s"],units root "system"]) "system/fs")
  else error "expected probe, idle, uart, sd, vfs, boot or system".
