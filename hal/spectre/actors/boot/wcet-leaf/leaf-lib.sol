# Shared by the leaf timing experiment's Sol scripts.
unsafe program.
K = use "../../../../../tools/sdk/sdk".
J = use "sol/lib/json".
words text = List.filter (fn w -> w != "") (Str.split 32 (Str.join " " (Str.split 9 (Str.trim text)))).
digit c = if c >= 48 and c <= 57 then c - 48 else if c >= 97 and c <= 102 then c - 87 else 0 - 1.
isHex text = text != "" and List.all (fn c -> digit c >= 0) (Str.codes text).
hex text = List.fold (fn acc c -> acc * 16 + digit c) 0 (Str.codes text).
hex8 w = Str.len w == 8 and isHex w.
# every "W xxxxxxxx ..." sample of `width` 8-digit hex words, in order, as numbers
takeHex n ws acc = if n == 0 then Ok (List.rev acc, ws) else case ws of
    w :: rest -> (if hex8 w then takeHex (n - 1) rest (hex w :: acc) else Err Unit)
  | [] -> Err Unit.
samplesIn width ws acc = case ws of
    [] -> List.rev acc
  | w :: rest -> (if Str.len w > 0 and Str.slice w (Str.len w - 1) (Str.len w) == "W" then (case takeHex width rest [] of
        Ok (row, more) -> samplesIn width more (row :: acc)
      | Err _ -> samplesIn width rest acc) else samplesIn width rest acc).
samples width text = samplesIn width (List.concat (List.map words (Str.split 10 text))) [].
# (value, count) pairs, values ascending
bump v pairs = case pairs of
    [] -> [(v, 1)]
  | (x, n) :: rest -> (if x == v then (x, n + 1) :: rest else if v < x then (v, 1) :: pairs else (x, n) :: bump v rest).
histogram values = List.fold (fn acc v -> bump v acc) [] values.
histogramJson values = J.JObj (List.map (fn p -> (v, n) = p; ("{v}", J.JNum n)) (histogram values)).
# objdump lines "  138:  ff010113  addi sp,sp,-16" as (address, encoding, operation, operands)
op line = case words line of
    at :: code :: name :: rest -> (if Str.len at > 1 and Str.slice at (Str.len at - 1) (Str.len at) == ":" and isHex (Str.slice at 0 (Str.len at - 1)) and hex8 code
        then [(Str.slice at 0 (Str.len at - 1), code, name, Str.join " " rest)] else [])
  | _ -> [].
ops text = List.concat (List.map op (Str.split 10 text)).
