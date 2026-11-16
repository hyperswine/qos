# Check the measured intervals against the conditional progress model.
#
#   sol summary.sol       in a directory holding linked.txt and board.log
unsafe program.
L = use "../leaf-lib".
K = use "../../../../../../tools/sdk/sdk".
J = use "sol/lib/json".
B = use "sol/lib/build".
expected = ["ff010113","00112623","00812423","01010413","00058513","00040e13","ffc42083","ff842403","000e0113","00008067"].
after mark lines = case lines of [] -> error "linked.txt has no chooseRight" | line :: rest -> (if Str.contains mark line then rest else after mark rest).
# One blocking read per advance, one carried read, and up to eleven writes
# or other carry-in transactions, each charged independently.
ceiling steps = advancing = steps * 32; advancing + 20 * (advancing + 1 + 11).
every k i rows = case rows of [] -> [] | row :: rest -> (if i % 4 == k then row :: every k (i + 1) rest else every k (i + 1) rest).
distinct values = List.len (L.histogram values).
mode rows k key =
  picked = every k 0 rows;
  cycles = List.map (fn row -> case row of c :: _ -> c | [] -> 0) picked;
  _ = K.check "{key}: a sample exceeds the conditional window" (List.all (fn c -> c <= ceiling 14) cycles);
  (key, J.JObj [("trials", J.JNum (List.len picked)), ("histogram", L.histogramJson cycles),
    ("distinct_start_low32_mod_540", J.JNum (distinct (List.map (fn row -> case row of [_, _, s] -> s % 540 | _ -> 0) picked)))]).
> here = B.query ["/bin/pwd","-P"];
  body = after "<fpr_fn_chooseRight>:" (Str.split 10 (K.readText "{here}/linked.txt"));
  codes = List.map (fn r -> (_, code, _, _) = r; code) (L.ops (Str.join "\n" body));
  _ = K.check "the linked chooseRight differs from the measured one" (codes == expected);
  log = K.readText "{here}/board.log";
  rows = L.samples 3 log;
  _ = K.check "expected 2160 samples of 12 instructions and exit 42" (List.len rows == 2160 and Str.contains "exit 42" log and List.all (fn row -> case row of [_, n, _] -> n == 12 | _ -> False) rows);
  print (J.pretty (J.JObj [("conditional_leaf_cycles", J.JNum (ceiling 10)), ("conditional_window_cycles", J.JNum (ceiling 14)),
    ("modes", J.JObj [mode rows 0 "baseline", mode rows 1 "conflict", mode rows 2 "stores", mode rows 3 "both"])])).
