# merge sort by a String key (byte order, as Python sorts ASCII)
sortBy : unsafe (a -> String) -> List a -> List a .
sortBy key xs = case xs of
    [] -> []
  | [x] -> [x]
  | _ ->
      half = List.len xs / 2;
      merge key (sortBy key (List.take half xs)) (sortBy key (List.drop half xs)).
merge : unsafe (a -> String) -> List a -> List a -> List a .
merge key a b = case (a, b) of
    ([], _) -> b
  | (_, []) -> a
  | (x :: xs, y :: ys) -> (case strCmp (key x) (key y) <= 0 of
      True -> x :: merge key xs b
    | False -> y :: merge key a ys).
sortText : unsafe List String -> List String .
sortText xs = sortBy (fn x -> x) xs.
