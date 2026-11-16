# One separately compiled app from the prompt, before and after a CPU reset.
#
#   sol check-app.sol      in the directory holding hello.sxa
unsafe program.
U = use "../board-lib".
B = use "sol/lib/build".
ran = ["hello from a separately compiled FP-RISC app","exit 42"].
same line want = rows = U.command 18 line; U.ensure "{line}: expected {want}, got {rows}" (rows == want).
> here = B.query ["/bin/pwd","-P"];
  name = "apps/hello.sxa";
  image = Str.trim (readPath "{here}/hello.sxa");
  _ = U.wake 18;
  created = U.command 60 "create {name} {image}";
  _ = U.ensure "create: {created}" (created == ["created {name}"] or created == ["already exists"]);
  _ = same "cat {name}" [image];
  _ = U.ensure "ls lacks {name}" (U.has name (U.command 18 "ls"));
  _ = same "run {name}" ran;
  _ = same "run {name}" ran;
  _ = same "run notes/spectre.txt" ["run: invalid app or exit status"];
  _ = same "cat notes/spectre.txt" ["hello from Spectre"];
  _ = print (U.reset 18);
  _ = same "run {name}" ran;
  _ = same "cat notes/spectre.txt" ["hello from Spectre"];
  print "PASS".
