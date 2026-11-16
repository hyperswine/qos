# Inventory one qualified Spectre app before assigning hardware cycle costs.
#
#   sol hal/spectre/actors/boot/timing-inputs.sol BUILD APP      (from the QOS root)
#
# BUILD is a build-integrated.sol output; APP is hello, spin, pendulum, ping or pong.
unsafe program.
K = use "../../../../tools/sdk/sdk".
J = use "sol/lib/json".
words text = List.filter (fn w -> w != "") (Str.split 32 (Str.trim text)).
isHex text = text != "" and List.all (fn c -> (c >= 48 and c <= 57) or (c >= 97 and c <= 102)) (Str.codes text).
# "  1f4:  00a00513  li a0,10": an address, an encoding, an instruction
instruction line = case words (Str.join " " (Str.split 9 line)) of
    at :: code :: _ :: _ -> Str.len at > 1 and Str.slice at (Str.len at - 1) (Str.len at) == ":" and isHex (Str.slice at 0 (Str.len at - 1)) and isHex code
  | _ -> False.
> case args Unit of
    [root, name] ->
      _ = K.check "expected hello, spin, pendulum, ping or pong" (List.has name ["hello","spin","pendulum","ping","pong"]);
      app = "{root}/boot/apps/{name}";
      rows = List.map words (K.lines (K.readText "{root}/SHA256SUMS"));
      manifest = List.map (fn row -> case row of
          expected :: file :: _ -> _ = K.check "build artifact hash mismatch: {file}" (K.sha256 "{root}/{file}" == expected); (file, expected)
        | _ -> error "malformed SHA256SUMS") rows;
      sumOf file = case List.filter (fn p -> (n, _) = p; n == file) manifest of (_, sha) :: _ -> sha | [] -> error "SHA256SUMS lacks {file}";
      # objdump reads the ELF; confirm its flat executable is the payload on the card
      tmp = Str.trim (K.command ["/usr/bin/mktemp","-d"]);
      _ = K.command ["riscv64-unknown-elf-objcopy","-O","binary","{app}.elf","{tmp}/app.bin"];
      payload = Str.join "" (K.lines (K.command ["/usr/bin/xxd","-p","{tmp}/app.bin"]));
      _ = K.command ["/bin/rm","-rf",tmp];
      package = Str.trim (K.readText "{app}.sxa");
      _ = K.check "ELF and packaged payload differ" (Str.slice package 24 (Str.len package) == payload);
      symbol = "fpr_fn_main";
      listing = K.command ["riscv64-unknown-elf-objdump","-d","--disassemble={symbol}","{app}.elf"];
      sites = List.len (List.filter instruction (Str.split 10 listing));
      mark = "# native-insns-v1: main ";
      report = case List.filter (fn line -> Str.startsWith mark line) (Str.split 10 (K.readText "{app}.s")) of
          line :: _ -> Str.slice line (Str.len mark) (Str.len line)
        | [] -> error "missing compiler report";
      _ = K.check "missing linked main" (sites > 0);
      inputs = Str.split 10 (K.readText "{root}/build-inputs.txt");
      at i = case List.drop i inputs of line :: _ -> line | [] -> error "build-inputs.txt is short";
      second line = case words line of _ :: w :: _ -> w | _ -> error "malformed build-inputs.txt";
      first line = case words line of w :: _ -> w | _ -> error "malformed build-inputs.txt";
      print (J.pretty (J.JObj [
        ("fprisc", J.JObj [("checkout", J.JStr (at 3)), ("compiler_sha256", J.JStr (first (at 4))), ("runtime", J.JStr (second (at 0)))]),
        ("qos_native", J.JObj [("checkout_at_build", J.JStr (at 2)), ("kernel_sha256", J.JStr (sumOf "boot/fs.bin"))]),
        ("spectre", J.JObj [("board_sources", J.JStr (second (at 1))), ("fpga_sha256", J.JStr (sumOf "boot/patched-pre.fs"))]),
        ("app", J.JStr name), ("sxa_sha256", J.JStr (K.sha256 "{app}.sxa")),
        ("symbol", J.JStr symbol), ("compiler_native_insns_v1", J.JStr report),
        ("linked_main_static_instruction_sites", J.JNum sites),
        ("wcet_cycles", J.JNull)]))
  | _ -> error "usage: sol hal/spectre/actors/boot/timing-inputs.sol BUILD hello|spin|pendulum|ping|pong".
