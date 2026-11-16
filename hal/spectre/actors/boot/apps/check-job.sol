# A looping app as a background job: progress, busy, stop, slot reuse.
#
#   sol check-job.sol      in the directory holding spin.sxa (apps/hello.sxa installed)
unsafe program.
U = use "../board-lib".
B = use "sol/lib/build".
check line row = U.expectRow 12 line row.
yields u = U.yieldsIn (U.loose 12 "status").
> here = B.query ["/bin/pwd","-P"];
  name = "apps/spin.sxa";
  _ = U.wake 12;
  _ = U.install 60 name (Str.trim (readPath "{here}/spin.sxa"));
  _ = check "run {name}" "started";
  a = yields Unit;
  _ = check "cat notes/spectre.txt" "hello from Spectre";
  _ = check "run apps/hello.sxa" "run: busy";
  b = yields Unit;
  _ = U.ensure "the job did not progress: {a} then {b}" (b > a);
  _ = check "stop" "stopped";
  _ = check "status" "stopped";
  _ = check "stop" "no running app";
  _ = check "run apps/hello.sxa" "started";
  _ = U.sleepMs 100;
  _ = check "status" "exit 42";
  _ = check "cat notes/spectre.txt" "hello from Spectre";
  _ = check "run {name}" "started";
  _ = U.ensure "the restarted job did not progress" (yields Unit > 0);
  _ = check "stop" "stopped";
  print "PASS {a} {b}".
