# Restrict InitializeAllTargets and its companion registries to SDK targets.
K = use "sdk/sdk".
targets = ["AArch64","RISCV","X86"].
keepTargetLine line = case Str.split 40 line of
    macro :: args :: [] ->
      registry = Str.startsWith "LLVM_" macro and List.all (fn c -> c == 95 or (c >= 65 and c <= 90)) (Str.codes macro);
      if registry then List.any (fn target -> args == "{target})") targets else True
  | _ -> True.
header source dest name =
  text = K.readText "{source}/{name}.def";
  K.writeText "{dest}/{name}.def" (Str.join "\n" (List.filter keepTargetLine (Str.split 10 text)) + "\n").
# CMake normally discovers its install prefix by walking up from the package.
# The copy lives outside that prefix, so retain the original library location.
rewrite llvm cfg line =
  targetList = Str.join ";" targets;
  case line of
    "set(LLVM_LINK_LLVM_DYLIB ON)" -> ["set(LLVM_LINK_LLVM_DYLIB OFF)"]
  | _ -> if Str.startsWith "set(LLVM_TARGETS_TO_BUILD " line then ["set(LLVM_TARGETS_TO_BUILD {targetList})"]
    else if Str.startsWith "set(LLVM_CMAKE_DIR " line then ["set(LLVM_CMAKE_DIR \"{cfg}\")"]
    else if (Str.startsWith "get_filename_component(LLVM_INSTALL_PREFIX " line and Str.contains "CMAKE_CURRENT_LIST_FILE" line) then ["set(LLVM_INSTALL_PREFIX \"{llvm}\")"]
    else if (Str.startsWith "get_filename_component(_IMPORT_PREFIX " line and Str.contains "CMAKE_CURRENT_LIST_FILE" line) then ["set(_IMPORT_PREFIX \"{llvm}\")"]
    else if (Str.startsWith "get_filename_component(LLVM_INSTALL_PREFIX " line and Str.contains "LLVM_INSTALL_PREFIX}" line) or (Str.startsWith "get_filename_component(_IMPORT_PREFIX " line and Str.contains "_IMPORT_PREFIX}" line) then []
    else [Str.replace "zstd::libzstd_shared" "zstd::libzstd_static" (Str.replace "/opt/homebrew/lib/libz3.dylib;" "" line)].
packageFile llvm cfg name =
  path = "{cfg}/{name}.cmake";
  lines = Str.split 10 (K.readText path);
  K.writeText path (Str.join "\n" (List.concat (List.map (rewrite llvm cfg) lines)) + "\n").
configure llvm cfg build = dest = "{build}/include/llvm/Config"; _ = K.mkdirs dest;
      _ = List.map (packageFile llvm cfg) ["LLVMConfig","LLVMExports"];
      _ = List.map (header "{llvm}/include/llvm/Config" dest) ["Targets","AsmPrinters","AsmParsers","Disassemblers","TargetMCAs","TargetExegesis"]; Unit.
