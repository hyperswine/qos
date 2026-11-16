# Exercise two named, independently compiled apps on the Spectre UART.
#
#   sol check-two.sol [--mailbox]      in the directory holding the built .sxa packages
#
# On a freshly booted board with the earlier hello app and notes/spectre.txt present.
unsafe program.
U = use "../board-lib".
B = use "sol/lib/build".
image here app = Str.trim (readPath "{here}/{app}.sxa").
yields slot = U.yieldsIn (U.loose 15 "status {slot}").
note = U.expectRow 15 "cat notes/spectre.txt" "hello from Spectre".
round u =
  _ = U.expectRow 15 "run apps/pong.sxa" "started job 1";
  _ = U.ensure "pong yielded before a message arrived" (yields 1 == 0);
  _ = U.expectRow 15 "cat notes/spectre.txt" "hello from Spectre";
  _ = U.expectRow 15 "run apps/ping.sxa" "started job 2";
  _ = U.expectRow 15 "status 1" "exit 37";
  _ = U.expectRow 15 "status 2" "exit 37";
  U.expectRow 15 "cat notes/spectre.txt" "hello from Spectre".
mailbox here =
  _ = List.map (fn app -> U.install 60 "apps/{app}.sxa" (image here app)) ["pong","ping"];
  _ = round Unit;
  round Unit.
two here =
  _ = List.map (fn app -> U.install 60 (if app == "hello" then "apps/hello2.sxa" else "apps/{app}.sxa") (image here app)) ["spin","pendulum","hello"];
  _ = U.expectRow 15 "run apps/spin.sxa" "started job 1";
  _ = U.expectRow 15 "run apps/pendulum.sxa" "started job 2";
  first = yields 1; second = yields 2;
  _ = U.expectRow 15 "run apps/hello2.sxa" "run: busy";
  _ = U.expectRow 15 "cat notes/spectre.txt" "hello from Spectre";
  _ = U.ensure "the two loops did not both progress" (yields 1 > first and yields 2 > second);
  _ = U.expectRow 15 "stop 1" "stopped";
  _ = U.expectRow 15 "status 1" "stopped";
  later = yields 2;
  _ = U.expectRow 15 "run apps/hello2.sxa" "started job 1";
  _ = U.sleepMs 200;
  _ = U.expectRow 15 "status 1" "exit 42";
  _ = U.ensure "the second loop stopped progressing" (yields 2 > later);
  _ = U.expectRow 15 "stop 2" "stopped";
  _ = U.expectRow 15 "status 2" "stopped";
  U.expectRow 15 "cat notes/spectre.txt" "hello from Spectre".
> here = B.query ["/bin/pwd","-P"];
  _ = U.frame 15 "";
  _ = (case args Unit of ["--mailbox"] -> mailbox here | [] -> two here | _ -> error "expected optional --mailbox");
  print "PASS".
