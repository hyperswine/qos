# Run the stress variant of the leaf probe: 2160 samples of 12 instructions each.
#
#   sol board.sol > board.log      in the directory holding leaf.sxa
unsafe program.
U = use "../../board-lib".
L = use "../leaf-lib".
B = use "sol/lib/build".
K = use "../../../../../../tools/sdk/sdk".
counts rows i = List.all (fn row -> case row of [_, n, _] -> n == 12 | _ -> False) rows.
> here = B.query ["/bin/pwd","-P"];
  image = Str.trim (readPath "{here}/leaf.sxa");
  name = "apps/wcet-{Str.slice (K.sha256Text image) 0 8}.sxa";
  _ = U.reset 20;
  _ = U.install 60 name image;
  # one open port for both commands: the samples arrive after the first prompt
  text = U.uart ["send-line","run {name}","expect",U.prompt,"15","expect-count","W ","2160","90","send-line","status 1","expect",U.prompt,"15"];
  _ = print text;
  _ = U.ensure "the probe did not exit 42" (Str.contains "exit 42" text);
  rows = L.samples 3 text;
  _ = U.ensure "expected 2160 samples, got {List.len rows}" (List.len rows == 2160);
  U.ensure "a sample retired an unexpected number of instructions" (counts rows 0).
