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
flags march = List.append extra ["-march={march}","-mabi=ilp32","-mno-relax","-msmall-data-limit=0","-ffixed-x27","-DFPR_NHARTS=1",
  "-ffreestanding","-fno-builtin","-Os","-ffunction-sections","-fdata-sections","-Isrc/runtime","-Isrc/machine/virt"].
hal = ["-Dhal_mtime=spectre_raw_ticks","-Dhal_timer_arm=spectre_raw_arm","-Dhal_putc=unused_uart","-Dhal_poweroff=unused_poweroff"].
kernel runtime = List.append ["-nostdlib","-Wl,--gc-sections","-T","src/machine/tangnano20k/link.ld","src/machine/tangnano20k/crt0.S",
  "src/machine/virt/ctx.S","src/machine/virt/ctx_fab.c","src/machine/virt/memshim.c"]
  (List.append (List.map (fn name -> "src/runtime/{name}.c") runtime) ["hal.o"]).
base = ["runtime","actors","buddy","i32","sstr","vec"].
withMod = List.append base ["mod"].
sd board = ["-I{board}/boards/tangnano20k/c","{board}/boards/tangnano20k/c/sd.c"].
# the compilation units an FP-RISC compile listed beside its app.s, as paths from the root
units root dir = List.map (fn line -> if Str.startsWith "./" line then "{dir}/{Str.slice line 2 (Str.len line)}" else line)
  (List.filter (fn line -> line != "") (List.map Str.trim (Str.lines (readPath "{root}/{dir}/app.s.units")))).
link root march runtime rest stem =
  f = flags march;
  _ = B.inDirectory root [] (List.concat [[cc],f,hal,["-c","src/machine/virt/hal.c","-o","hal.o"]]);
  _ = B.inDirectory root [] (List.concat [[cc],f,kernel runtime,rest,["atomic.c","-lgcc","-o","{stem}.elf"]]);
  B.inDirectory root [] [objcopy,"-O","binary","{stem}.elf","{stem}.bin"].
# one target, in `root`; `board` is the Simple-Risc checkout (sd, vfs and boot need its SD driver)
target root board name =
  if name == "probe" then link root "rv32im_zicsr" base ["probe.c"] "probe"
  else if name == "idle" then link root "rv32im_zicsr" base ["-Wl,--wrap=hal_wfi","idle/idle.c"] "idle/idle"
  else if name == "uart" then link root "rv32im_zicsr" base ["-Wl,--wrap=hal_wfi","uart/uart.c"] "uart/uart"
  else if name == "sd" then link root "rv32im_zicsr" base (List.append (sd board) ["sd/storage.c"]) "sd/storage"
  else if name == "vfs" then link root "rv32im_zicsr" withMod (List.concat [sd board,["vfs/hal.c","vfs/app.s"],units root "vfs"]) "vfs/fs"
  else if name == "boot" then link root "rv32im_zicsr_zifencei" withMod (List.concat [sd board,["boot/hal.c","boot/app.s"],units root "boot"]) "boot/fs"
  else error "expected probe, idle, uart, sd, vfs or boot".
