# Check the linked path and every raw sample before summarizing costs.
#
#   sol analyse.sol       in a directory holding leaf.elf, leaf.sxa and board.log
unsafe program.
L = use "leaf-lib".
K = use "../../../../../tools/sdk/sdk".
J = use "sol/lib/json".
B = use "sol/lib/build".
disassemble here extra = K.commandIn here (List.concat [["riscv64-unknown-elf-objdump","-d","-M","no-aliases"],extra,["leaf.elf"]]).
names rows = List.map (fn r -> (_, _, name, _) = r; name) rows.
operands rows = List.map (fn r -> (_, _, _, rest) = r; Str.join "" (Str.split 32 rest)) rows.
window rows = case rows of
    [] -> error "the measured window is not in the image"
  | (_, _, name, rest) :: more -> (if name == "csrrs" and Str.contains "s4,mcycle,zero" (Str.join "" (Str.split 32 rest)) then List.take 5 rows else window more).
pairs rows = case rows of a :: b :: rest -> (a, b) :: pairs rest | _ -> [].
summary label picked length =
  _ = K.check "{label}: a sample retired a different number of instructions" (List.all (fn row -> case row of [_, n] -> n == 2 + length | _ -> False) picked);
  (label, J.JObj [("paired_trials", J.JNum (List.len picked)), ("minstret_delta", J.JNum (2 + length)),
    ("raw_mcycle_histogram", L.histogramJson (List.map (fn row -> case row of c :: _ -> c | [] -> 0) picked))]).
> here = B.query ["/bin/pwd","-P"];
  body = L.ops (disassemble here ["--disassemble=fpr_fn_chooseRight"]);
  _ = K.check "chooseRight is not the expected ten instructions" (names body == ["addi","sw","sw","addi","addi","addi","lw","lw","addi","jalr"]);
  _ = K.check "chooseRight does not end in a plain return" (case List.rev (operands body) of last :: _ -> last == "zero,0(ra)" | [] -> False);
  measured = window (L.ops (disassemble here []));
  _ = K.check "the measured window's operations differ" (names measured == ["csrrs","csrrs","jalr","csrrs","csrrs"]);
  _ = K.check "the measured window's operands differ" (operands measured == ["s4,mcycle,zero","s5,minstret,zero","ra,0(s2)","t0,minstret,zero","t1,mcycle,zero"]);
  log = K.readText "{here}/board.log";
  rows = L.samples 2 log;
  _ = K.check "expected 32 samples and exit 42" (List.len rows == 32 and Str.contains "exit 42" log);
  both = pairs rows;
  offset = case body of (at, _, _, _) :: _ -> at | [] -> "";
  print (J.pretty (J.JObj [("elf_sha256", J.JStr (K.sha256 "{here}/leaf.elf")), ("package_sha256", J.JStr (K.sha256 "{here}/leaf.sxa")),
    ("leaf_link_offset", J.JStr offset),
    ("samples", J.JObj [summary "ret_only" (List.map (fn p -> (a, _) = p; a) both) 1, summary "chooseRight" (List.map (fn p -> (_, b) = p; b) both) (List.len body)])])).
