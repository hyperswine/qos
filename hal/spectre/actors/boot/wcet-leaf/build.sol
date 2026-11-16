# Build the bounded measurement app from FP-RISC compiler output.
#
#   sol build.sol FPR APPS        in a directory holding leaf.fpr and entry.S
#
# FPR is the compiler, APPS the Spectre apps directory (empty.fpr, link.ld).
# The complete compiler-emitted chooseRight is isolated without its unused
# runtime; SPECTRE_IMAGE names the built hal/spectre/tools/spectre-image.
unsafe program.
K = use "../../../../../tools/sdk/sdk".
B = use "sol/lib/build".
start = "    .globl fpr_fn_chooseRight".
finish = "# native-insns-v1: chooseRight ".
body lines inside acc = case lines of
    [] -> error "missing compiler function"
  | line :: rest ->
      if not inside then (if line == start then body rest True (line :: acc) else body rest False acc)
      else if Str.startsWith finish line then List.rev (line :: acc)
      else body rest True (line :: acc).
> case args Unit of
    [fpr, given] ->
      apps = K.realpath given;
      here = B.query ["/bin/pwd","-P"];
      tool = B.setting "SPECTRE_IMAGE" "spectre-image";
      _ = B.inDirectory here [] [fpr,"compile","--profile=builtin","--target=rv32","--prelude={apps}/empty.fpr","leaf.fpr","leaf.s"];
      text = Str.join "\n" (body (Str.split 10 (readPath "{here}/leaf.s")) False []);
      _ = K.writeText "{here}/body.s" ".text\n{text}\n";
      _ = B.inDirectory here [] ["riscv64-unknown-elf-gcc","-march=rv32im_zicsr","-mabi=ilp32","-mno-relax","-nostdlib","-T","{apps}/link.ld","entry.S","body.s","-o","leaf.elf"];
      _ = B.inDirectory here [] ["riscv64-unknown-elf-objcopy","-O","binary","leaf.elf","leaf.bin"];
      B.inDirectory here [] [tool,"sxa","leaf.bin","leaf.sxa"]
  | _ -> error "usage: sol build.sol FPR APPS".
