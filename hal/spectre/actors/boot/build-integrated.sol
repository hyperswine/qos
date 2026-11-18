# Build the integrated Spectre kernel, SD installer, FPGA image and app fixtures.
#
#   sol hal/spectre/actors/boot/build-integrated.sol NEW-OUTPUT-DIRECTORY     (from the QOS root)
#   SPECTRE_BOARD=spectre-84 sol hal/spectre/actors/boot/build-integrated.sol DIR   (the fprisc-84 image)
# SPECTRE_RUNTIME_REV overrides the runtime revision taken from fprisc.lock.json.
# SPECTRE_IMAGE=system makes System.qa (programs/system.fpr, HARTS=1, console
# con0 on qlink; needs SPECTRE_CONSOLE=qlink) the image the SD slot boots
# instead of the boot shell (boot/app.fpr, the default `boot`).
#
# FPRISC and SIMPLE_RISC name the two other checkouts (default: beside QOS).
# The output holds the artifacts, SHA256SUMS and build-inputs.txt. The byte
# steps (LZ4, boot media, app packages, the ROM patched into the bitstream)
# are hal/spectre/tools/spectre-image.c, built here.
unsafe program.
S = use "../spectre-build".
B = use "sol/lib/build".
K = use "../../../../tools/sdk/sdk".
J = use "sol/lib/json".
boardPin = "8f83a6d165dae080110312cdbde40d32799a461a".
# SPECTRE_BOARD picks the qualified bitstream the ROM is patched into, its CPU
# clock and the SD boot slot: spectre-54 (btbdef-54, the original demonstrator)
# or spectre-84 (fprisc-84, RV32IM at 84 MHz). The two slots are adjacent 2 MiB
# windows, so a card can hold both kernels.
spectreBoard = B.setting "SPECTRE_BOARD" "spectre-54".
boardConf name = case name of
    "spectre-54" -> ("output/tangnano20k/btbdef-54","f01fdf0bb48c3f5842cf8f8ad0d7d24bc1a746c9959993089e26a4661e207038","54","135168")
  | "spectre-84" -> ("output/tangnano20k/fprisc-84","64664f41c869e9110857ddf5b5df9797c0c4c3a38f750765646ec7fcd71fc261","84","139264")
  | _ -> error "SPECTRE_BOARD must be spectre-54 or spectre-84".
preset = (p,_,_,_) = boardConf spectreBoard; p.
bitstreamSha = (_,h,_,_) = boardConf spectreBoard; h.
slot = (_,_,_,l) = boardConf spectreBoard; l.
bare = ["-march=rv32im_zicsr_zifencei","-mabi=ilp32","-mno-relax","-msmall-data-limit=0","-Os","-ffreestanding","-nostdlib"].
inDir dir argv = B.inDirectory dir [] argv.
copyInto dir paths = List.map (fn p -> B.command ["/bin/cp", p, dir]) paths.
# `git archive REV PATHS | tar -x -C DEST`
export repo rev paths dest = B.command (List.append ["/bin/sh","-c","rev=$1; dest=$2; repo=$0; shift 2; git -C \"$repo\" archive \"$rev\" \"$@\" | tar -x -C \"$dest\"",repo,rev,dest] paths).

# ---- the boot media: ROM, packed kernel, SD slot, patched bitstream, installer ----
media out board tool =
  boot = "{out}/boot"; b = "{board}/boards/tangnano20k";
  _ = inDir boot (List.concat [[S.cc],bare,["-DROM_SDRAM","-DSLOT_LBA={slot}u","-T","{b}/bootrom/link.ld","{b}/bootrom/crt0.S","rom.c","-o","rom.elf"]]);
  _ = inDir boot [S.objcopy,"-O","binary","rom.elf","rom.bin"];
  _ = inDir boot [tool,"lz4","fs.bin","packed.lz4"];
  _ = inDir boot (List.concat [[S.cc],bare,["-Ttext=0x80000000","unpack.S","-o","packed.elf"]]);
  _ = inDir boot [S.objcopy,"-j",".text","-O","binary","packed.elf","packed.bin"];
  _ = inDir boot [tool,"media","packed.bin","media.bin"];
  fs = "{board}/{preset}/impl/pnr/sdram_test.fs";
  _ = K.check "the bitstream is not the one this patch was qualified against" (K.sha256 fs == bitstreamSha);
  _ = inDir boot [tool,"patchrom",fs,"{board}/{preset}/bootrom-sdram.hex","rom.bin","patched-pre.fs"];
  _ = inDir out (List.concat [[S.cc],bare,["-DSLOT_LBA={slot}u","-T","src/machine/tangnano20k/link.ld","src/machine/tangnano20k/crt0.S","-I{b}/c","{b}/c/sd.c","boot/install.c","boot/media.S","-o","boot/install.elf"]]);
  inDir out [S.objcopy,"-O","binary","boot/install.elf","boot/install.bin"].

# ---- one returning app: PC-relative text and read-only literals ----
allowed = ["R_RISCV_PCREL_HI20","R_RISCV_PCREL_LO12_I","R_RISCV_CALL","R_RISCV_CALL_PLT","R_RISCV_BRANCH","R_RISCV_JAL","R_RISCV_NONE"].
isDigit c = c >= 48 and c <= 57.
leading cs n = case cs of c :: rest -> (if isDigit c then leading rest (n + 1) else n) | [] -> n.
# ".Ltir_<name>_b<digits>:" -- a typed RV32 block label, the tail-recursive loop targets among them
blockLabel line =
  n = Str.len line;
  if not (Str.startsWith ".Ltir_" line) or n < 10 or Str.slice line (n - 1) n != ":" then False
  else
    digits = List.rev (Str.codes (Str.slice line 0 (n - 1)));
    tail = leading digits 0;
    tail > 0 and Str.slice line (n - 1 - tail - 2) (n - 1 - tail) == "_b".
poll = ["    addi sp,sp,-16","    sw ra,12(sp)","    call spectre_poll","    lw ra,12(sp)","    addi sp,sp,16"].
globlName line = Str.trim (Str.slice line 11 (Str.len line)).
# each function in a section of its own, static closures read-only, and a
# poll at every block label; answers the lines and how many labels there were
sections lines count acc = case lines of
    [] -> (List.rev acc, count)
  | line :: rest ->
      if Str.startsWith "# fn " line then (case rest of
          next :: _ -> (if Str.startsWith "    .globl fpr_fn_" next then sections rest count (".section .text.{globlName next},\"ax\"" :: line :: acc)
                        else sections rest count (line :: acc))
        | [] -> sections rest count (line :: acc))
      else if Str.startsWith "# static-pap:" line then sections rest count (line :: ".section .rodata.paps,\"a\"" :: acc)
      else if blockLabel line then sections rest (count + 1) (List.append (List.rev poll) (line :: acc))
      else sections rest count (line :: acc).
app apps fpr env tool mailbox name =
  _ = B.inDirectory apps env [fpr,"compile","--profile=builtin","--target=rv32","--prelude=empty.fpr","{name}.fpr","{name}.s"];
  (lines, count) = sections (Str.split 10 (readPath "{apps}/{name}.s")) 0 [];
  _ = K.check "{name}: no instrumentable typed blocks" (count > 0);
  _ = K.writeText "{apps}/{name}.sections.s" (Str.join "\n" lines);
  _ = inDir apps (List.concat [[S.cc,"-march=rv32im","-mabi=ilp32","-mno-relax","-nostdlib","-Wl,--gc-sections,--emit-relocs","-T","link.ld"],
        (if mailbox then ["-DSPECTRE_MAILBOX"] else []),["entry.S","{name}.sections.s","-o","{name}.elf"]]);
  relocs = K.commandIn apps ["riscv64-unknown-elf-readelf","-rW","{name}.elf"];
  kinds = List.filter (fn w -> Str.startsWith "R_RISCV_" w) (List.concat (List.map S.words (Str.lines relocs)));
  _ = List.map (fn kind -> K.check "{name}: relocation {kind} is not position independent" (List.has kind allowed)) kinds;
  _ = inDir apps [S.objcopy,"-O","binary","{name}.elf","{name}.bin"];
  inDir apps (List.append [tool,"sxa","{name}.bin","{name}.sxa"] (if mailbox then ["--mailbox"] else [])).

# System.qa as the SD image: compiled for qos-native RV32, linked by
# spectre-build's `system` target, and copied over boot/fs.bin for `media`
systemImage qos fprisc out board env =
  _ = K.mkdirs "{out}/system";
  _ = B.command ["/bin/cp","{qos}/hal/spectre/actors/system/hal.c","{out}/system/"];
  _ = B.inDirectory "{out}/system" env ["{fprisc}/fpr","compile","--system=qos-native","--target=rv32","--prelude={out}/fprisc/core/prelude.fpr","{out}/qos/programs/system.fpr","app.s"];
  _ = B.command ["make","-s","-C","{qos}/qos","BUILD={out}/sysbuild","{out}/sysbuild/apps_data.c"];
  _ = S.target out board "system";
  B.command ["/bin/cp","{out}/system/fs.bin","{out}/boot/fs.bin"].
sums out names = Str.join "" (List.map (fn name -> path = "{out}/{name}"; sha = K.sha256 path; "{sha}  {name}\n") names).
> case args Unit of
    [target] ->
      qos = B.query ["/bin/pwd","-P"];
      boot = "{qos}/hal/spectre/actors/boot";
      _ = K.check "run from the QOS root" (K.isFile "{boot}/app.fpr");
      fprisc = K.realpath (B.setting "FPRISC" "{qos}/../fprisc");
      checkout = K.realpath (B.setting "SIMPLE_RISC" "{qos}/../simple-risc");
      _ = B.command ["/bin/mkdir", target];
      out = K.realpath target;
      (_,_,clock,_) = boardConf spectreBoard;
      _ = unwrap (Env.set "SPECTRE_MHZ" clock);
      _ = unwrap (Env.set "QOS" qos);
      _ = List.map (fn d -> K.mkdirs "{out}/{d}") ["src","boot/apps","board/{preset}/impl/pnr","fprisc","qos"];
      # the runtime is fprisc.lock.json's revision unless SPECTRE_RUNTIME_REV names
      # another (the lock predates the RV32 raw-mask fix fprisc 886696e8)
      locked = K.need (J.text (K.field "revision" (K.need (J.parse (readPath "{qos}/fprisc.lock.json")))));
      pin = B.setting "SPECTRE_RUNTIME_REV" locked;
      _ = export fprisc pin ["runtime","machine/virt","machine/tangnano20k"] "{out}/src";
      _ = export checkout boardPin ["boards/tangnano20k/c","boards/tangnano20k/bootrom"] "{out}/board";
      _ = B.command ["/bin/cp","{checkout}/{preset}/impl/pnr/sdram_test.fs","{out}/board/{preset}/impl/pnr/"];
      _ = B.command ["/bin/cp","{checkout}/{preset}/bootrom-sdram.hex","{out}/board/{preset}/"];
      board = "{out}/board";
      _ = B.command ["/bin/cp","{boot}/../atomic.c",out];
      _ = copyInto "{out}/boot" (List.map (fn n -> "{boot}/{n}") ["app.fpr","hal.c","rom.c","install.c","media.S"]);
      _ = B.command ["/bin/cp","{boot}/../vfs/unpack.S","{out}/boot/"];
      _ = B.command ["/bin/sh","-c","cp \"$0\"/apps/*.fpr \"$0\"/apps/entry.S \"$0\"/apps/link.ld \"$1\"/boot/apps/",boot,out];
      # FP-RISC orders module-table entries by resolved source path. Give both
      # source roots stable relative names, independent of checkout locations.
      _ = B.command ["/bin/cp","-R","{fprisc}/core","{fprisc}/std","{out}/fprisc/"];
      _ = B.command ["/bin/cp","-R","{qos}/core","{qos}/std","{qos}/programs","{qos}/.fpr","{out}/qos/"];
      env = [("LC_ALL","C"),("FPR_HOME","{out}/qos"),("FPR_PATH","{out}/fprisc"),("FPR_FOREIGN","{out}/qos/core/foreign.fpr"),("EXTRA","")];
      tool = "{out}/spectre-image";
      _ = B.command ["/bin/sh","-c","cc -O2 $(pkg-config --cflags liblz4) \"$0\" $(pkg-config --libs liblz4) -o \"$1\"","{qos}/hal/spectre/tools/spectre-image.c",tool];
      _ = B.inDirectory "{out}/boot" env ["{fprisc}/fpr","compile","--target=rv32","--prelude={out}/fprisc/core/prelude.fpr","app.fpr","app.s"];
      bsp = if spectreBoard == "spectre-84" then "spectre84" else "spectre54";
      _ = B.inDirectory qos [] [B.setting "SOL" "sol","tools/board.sol","bsp/{bsp}/board.json","{out}/board-devices"];
      _ = S.target out board "boot";
      _ = (if B.setting "SPECTRE_IMAGE" "boot" == "system" then systemImage qos fprisc out board env else Unit);
      _ = media out board tool;
      _ = List.map (app "{out}/boot/apps" "{fprisc}/fpr" env tool False) ["spin","pendulum","hello"];
      _ = List.map (app "{out}/boot/apps" "{fprisc}/fpr" env tool True) ["ping","pong"];
      listed = List.append ["boot/fs.bin","boot/media.bin","boot/install.bin","boot/patched-pre.fs"]
        (List.map (fn n -> "boot/apps/{n}.sxa") ["hello","pendulum","ping","pong","spin"]);
      manifest = sums out listed;
      _ = K.writeText "{out}/SHA256SUMS" manifest;
      compilerSha = K.sha256 "{fprisc}/fpr"; preludeSha = K.sha256 "{fprisc}/core/prelude.fpr";
      consoleMode = B.setting "SPECTRE_CONSOLE" "raw";
      inputs = Str.join "\n" ["board image {spectreBoard} ({preset}, slot {slot}), console {consoleMode}","runtime {pin}","board {boardPin}",Str.trim (K.command ["git","-C",qos,"rev-parse","HEAD"]),Str.trim (K.command ["git","-C",fprisc,"rev-parse","HEAD"]),
        "{compilerSha}  {fprisc}/fpr","{preludeSha}  {fprisc}/core/prelude.fpr",Str.trim (K.command [S.cc,"--version"])];
      _ = K.writeText "{out}/build-inputs.txt" "{inputs}\n";
      print manifest
  | _ -> error "usage: sol hal/spectre/actors/boot/build-integrated.sol NEW-OUTPUT-DIRECTORY".
