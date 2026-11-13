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
versions fpr =
  argv = ["riscv64-unknown-elf-gcc","-march=rv64imafdc_zicsr","-ffixed-x27","-mabi=lp64",cellLayoutFlag,
    "-DFPR_NHARTS=1","-ffreestanding","-dM","-E","-x","c","-include","{fpr}/runtime/fpr.h","-"];
  ProcessResult status out err = unwrap (Proc.runNow (ProcessSpec argv "" [] "" 30000));
  definitions = (if status == 0 then Str.lines out else error "ABI preprocessor exited {status}: {err}");
  List.map (value definitions) ["FPR_NATIVE_ABI","FPR_PLANE_ACTORS_ABI","FPR_PLANE_MEMORY_ABI"].
