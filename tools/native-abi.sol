# Read macros after preprocessing with the process image's target ABI.
value definitions name =
  prefix = "#define {name} ";
  case List.filter (Str.startsWith prefix) definitions of
    [line] -> raw = substr line (Str.len prefix) (Str.len line);
              digits = (if Str.endsWith "u" raw then substr raw 0 (Str.len raw - 1) else raw);
              if and (digits != "") (List.all (fn c -> and (c >= 48) (c <= 57)) (Str.codes digits)) then digits
              else error "target does not define a numeric {name}"
  | _ -> error "missing or duplicate target definition: {name}".
cellLayoutFlag = case unwrap (Env.get "FPR_COMPACT_CELLS") of
    EnvText "0" -> "-DFPR_LEGACY_CELLS" | _ -> "-DFPR_COMPACT_CELLS".
# the target's compiler flags: rv64 (QEMU virt) or rv32 (virt32, Spectre)
archFlags xlen = if xlen == 32 then ["-march=rv32imac_zicsr_zifencei","-mabi=ilp32"] else ["-march=rv64imafdc_zicsr","-mabi=lp64"].
versions fpr = versionsFor fpr 64.
# The native ABI (struct layouts, the boot block) differs by word size: an
# rv32 image declares it plus 500000000 (loader/process.c QOS_NATIVE_ABI_ID),
# so a kernel refuses an image of the other width before reading its layout.
widthed xlen versions = case versions of
    native :: rest -> (if xlen == 32 then "{parseInt native + 500000000}" else native) :: rest
  | [] -> [].
versionsFor fpr xlen =
  argv = List.concat [["riscv64-unknown-elf-gcc"], archFlags xlen, ["-ffixed-x27",cellLayoutFlag,
    "-DFPR_NHARTS=1","-ffreestanding","-dM","-E","-x","c","-include","{fpr}/runtime/fpr.h","-"]];
  ProcessResult status out err = unwrap (Proc.runNow (ProcessSpec argv "" [] "" 30000));
  definitions = (if status == 0 then Str.lines out else error "ABI preprocessor exited {status}: {err}");
  widthed xlen (List.map (value definitions) ["FPR_NATIVE_ABI","FPR_PLANE_ACTORS_ABI","FPR_PLANE_MEMORY_ABI"]).
