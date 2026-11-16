# Run the leaf timing probe on the board and check every sample's instruction count.
#
#   sol board.sol > board.log      in the directory holding leaf.sxa
unsafe program.
U = use "../board-lib".
L = use "leaf-lib".
B = use "sol/lib/build".
K = use "../../../../../tools/sdk/sdk".
counts rows i = case rows of [] -> True | [_, n] :: rest -> n == (if i % 2 == 1 then 12 else 3) and counts rest (i + 1) | _ -> False.
> here = B.query ["/bin/pwd","-P"];
  image = Str.trim (readPath "{here}/leaf.sxa");
  name = "apps/wcet-{Str.slice (K.sha256Text image) 0 8}.sxa";
  _ = U.reset 20;
  _ = U.install 60 name image;
  # one open port for both commands: the samples arrive after the first prompt
  text = U.uart ["send-line","run {name}","expect",U.prompt,"15","delay","500","send-line","status 1","expect",U.prompt,"15"];
  _ = print text;
  _ = U.ensure "the probe did not exit 42" (Str.contains "exit 42" text);
  rows = L.samples 2 text;
  _ = U.ensure "expected 32 samples, got {List.len rows}" (List.len rows == 32);
  U.ensure "a sample retired an unexpected number of instructions" (counts rows 0).
