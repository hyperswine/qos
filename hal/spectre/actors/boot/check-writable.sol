# A file written at the prompt, and (cold) still there after a power cycle.
#
#   sol check-writable.sol warm     create a file, read it back, record it in created-file.json
#   sol check-writable.sol cold     arm, wait for the USB cable to go and come back, expect the
#                                   SD boot marker and the recorded file
unsafe program.
U = use "board-lib".
B = use "sol/lib/build".
K = use "../../../../tools/sdk/sdk".
J = use "sol/lib/json".
same line want = rows = U.command 15 line; U.ensure "{line}: expected {want}, got {rows}" (rows == want).
verify name body =
  names = U.command 15 "ls";
  _ = U.ensure "ls lacks {name} or notes/spectre.txt" (U.has name names and U.has "notes/spectre.txt" names);
  _ = same "cat {name}" [body];
  same "cat notes/spectre.txt" ["hello from Spectre"].
> here = B.query ["/bin/pwd","-P"];
  case args Unit of
    ["cold"] ->
      _ = U.ensure "connect board before arming" (K.exists U.port);
      _ = print "armed";
      boot = U.uart ["wait-gone","600","wait-present","600","expect",U.prompt,"15"];
      _ = print boot;
      _ = U.ensure "autonomous SD boot marker missing" (Str.contains "Spectre SD boot OK" boot);
      recorded = K.need (J.parse (K.readText "{here}/created-file.json"));
      (case J.items recorded of
          Ok [J.JStr name, J.JStr body] -> verify name body
        | _ -> error "created-file.json is not [name, body]")
  | ["warm"] ->
      token = Str.trim (K.command ["/usr/bin/openssl","rand","-hex","4"]);
      name = "notes/prompt-{token}.txt"; body = "written at the Spectre prompt {token}";
      _ = U.wake 15;
      _ = same "create {name} {body}" ["created {name}"];
      _ = same "create {name} overwrite" ["already exists"];
      _ = K.writeText "{here}/created-file.json" (J.render (J.JArr [J.JStr name, J.JStr body]));
      verify name body
  | _ -> error "usage: sol check-writable.sol warm|cold".
