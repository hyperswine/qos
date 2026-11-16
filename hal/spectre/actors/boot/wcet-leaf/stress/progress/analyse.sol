# Account for A2 port traffic, including speculative fetch and earlier writes.
#
#   sol analyse.sol       in a directory holding runs/*.log (100 of them)
unsafe program.
L = use "../../leaf-lib".
K = use "../../../../../../../tools/sdk/sdk".
J = use "sol/lib/json".
B = use "sol/lib/build".
number text = case Try.parseInt text of Ok n -> n | Err _ -> error "not a number: {text}".
has x xs = List.any (fn y -> y == x) xs.
add x xs = if has x xs then xs else x :: xs.
lookup index known = case known of [] -> 0 - 1 | (i, line) :: rest -> (if i == index then line else lookup index rest).
without index known = List.filter (fn p -> (i, _) = p; i != index) known.
larger a b = if a > b then a else b.
# Unknown initial tags. For each set remember only one guaranteed line.
# Discard it even on a store hit. A different read in the same set can
# replace it; consecutive reads of the same line need only one fill.
# state: (known, lines, reads, fills, maxima, windows, retries); maxima in `keys` order
keys = ["advance","gap","read_lines","all_lines","charged_fills","refills","pushes","transfer_cap","window","physical_sim"].
step path state row = case state of (known, lines, reads, fills, maxima, total, retries) ->
  (case L.words row of
      "P" :: _ :: word :: store :: _ ->
        line = L.hex word / 4; index = line % 2048;
        if number store != 0 then (without index known, add line lines, reads, fills, maxima, total, retries)
        else ((index, line) :: without index known, add line lines, add line reads, (if lookup index known != line then fills + 1 else fills), maxima, total, retries)
    | ["W", n, advancing, gap, refills, clocks, pushes, _, retry] ->
        # One extra carry-in transaction in addition to the four
        # queued writes; covers a refill already active on entry.
        cap = fills + number pushes + 5;
        envelope = number advancing + 20 * cap;
        _ = K.check "{path}: window {n} is outside its envelope" (number refills <= fills + 1 and number clocks <= envelope);
        now = [number advancing, number gap, List.len reads, List.len lines, fills, number refills, number pushes, cap, envelope, number clocks];
        ([], [], [], 0, List.map (fn p -> (a, b) = p; larger a b) (List.zip maxima now), total + 1, retries + number retry)
    | _ -> state).
file state path = case state of (_, _, _, _, maxima, total, retries) ->
  List.fold (step path) ([], [], [], 0, maxima, total, retries) (Str.split 10 (readPath path)).
summarise files = case List.fold file ([], [], [], 0, List.map (fn k -> 0) keys, 0, 0) files of (_, _, _, _, maxima, total, retries) ->
  J.JObj (List.append (List.map (fn p -> (k, v) = p; (k, J.JNum v)) (List.zip keys maxima)) [("windows", J.JNum total), ("counter_retry_clocks", J.JNum retries)]).
> here = B.query ["/bin/pwd","-P"];
  files = List.map (fn name -> "{here}/runs/{name}") (List.filter (fn name -> Str.endsWith ".log" name) (K.files "{here}/runs"));
  _ = K.check "expected 100 run logs" (List.len files == 100);
  natural = List.filter (fn p -> Str.endsWith "-0-0-None.log" p) files;
  all = summarise files;
  _ = K.check "expected 25600 windows" (case J.get "windows" all of Ok (J.JNum n) -> n == 25600 | _ -> False);
  print (J.pretty (J.JObj [("natural", summarise natural), ("all", all)])).
