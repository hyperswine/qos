# sweep.sol -- run the legs in checks/legs, several at a time, and say what
# changed against what each leg is expected to do.
#
#   ./sweep [--jobs N] [--output DIR] [--since REF | --changed PATH ...]
#           [--only TEXT ...] [--times FILE] [--list] [--no-retry] [--strict]
#           [--in-place] [--manifest FILE] [--timeout SECONDS]
#
# Run through ./sweep, which starts this with a released Sol: the runner must
# not be built by the compiler it is reporting on.
#
# Every worker has a private copy of the tree, so two legs never share
# build/, app.qa or a disk.  A group (a leg and the `@ with previous` legs
# under it) runs in one tree, in order.  `@ serial` groups run on worker 0
# in file order.  The service checks run once beside the workers and their
# legs read the verdicts.  A leg that fails where it is expected to pass is
# run again alone, because a deadline can be missed only for want of cores.
#
# Nothing here is transactional: every read and write is immediate, and
# every process is owned by this script (Proc.start), so a timeout or an
# interrupt takes the leg's whole process group with it.

Leg = Type (Leg String Bool Bool String (List String)).
legName (Leg n s f w b) = n.
legSerial (Leg n s f w b) = s.
legFollows (Leg n s f w b) = f.
legWhy (Leg n s f w b) = w.
legBody (Leg n s f w b) = Str.join "\n" (List.rev b).
legService l = Str.contains "service_leg " (legBody l).

must r = case r of Ok value -> value | Err e -> error (str e).

# ---- options ---------------------------------------------------------------

defaults = {jobs = 5, out = "", since = "", changed = [], only = [], times = "", list = False,
            retry = True, strict = False, inPlace = False, manifest = "checks/legs", timeout = 2400}.

setOpt key value o | key == "--jobs" = {o | jobs = parseInt value}.
setOpt key value o | key == "--output" = {o | out = value}.
setOpt key value o | key == "--since" = {o | since = value}.
setOpt key value o | key == "--changed" = {o | changed = value :: o.changed}.
setOpt key value o | key == "--only" = {o | only = value :: o.only}.
setOpt key value o | key == "--times" = {o | times = value}.
setOpt key value o | key == "--manifest" = {o | manifest = value}.
setOpt key value o | key == "--timeout" = {o | timeout = parseInt value}.
setOpt key value o = error "sweep: unknown option {key}".

optStep (o, key) a | key != "" = (setOpt key a o, "").
optStep (o, key) a | a == "--list" = ({o | list = True}, "").
optStep (o, key) a | a == "--no-retry" = ({o | retry = False}, "").
optStep (o, key) a | a == "--strict" = ({o | strict = True}, "").
optStep (o, key) a | a == "--in-place" = ({o | inPlace = True, jobs = 1}, "").
optStep (o, key) a = (o, a).

options argv = case foldl optStep (defaults, "") argv of
  (o, "") -> o
| (o, key) -> error "sweep: {key} needs a value".

# ---- the manifest ----------------------------------------------------------

legLine (done, cur) line | Str.startsWith "== " line = (List.append cur done, [Leg (Str.sub line 3 (strlen line - 3)) False False "" []]).
legLine (done, Nil) line = (done, []).
legLine (done, Leg n s f w b :: rest) line | line == "@ serial" = (done, [Leg n True f w b]).
legLine (done, Leg n s f w b :: rest) line | line == "@ with previous" = (done, [Leg n s True w b]).
legLine (done, Leg n s f w b :: rest) line | Str.startsWith "@ expect fail -- " line = (done, [Leg n s f (Str.sub line 17 (strlen line - 17)) b]).
legLine (done, Leg n s f w b :: rest) line | Str.startsWith "@ " line = error "checks/legs: unknown directive in '{n}': {line}".
legLine (done, Leg n s f w b :: rest) line = (done, [Leg n s f w (line :: b)]).

legsOf text = case foldl legLine ([], []) (Str.lines text) of (done, cur) -> List.rev (List.append cur done).

# groups, in file order: a leg, then the legs that follow it
groupStep (groups, i) leg = case legFollows leg of
  True -> (case groups of Nil -> ([[i]], i + 1) | g :: rest -> ((i :: g) :: rest, i + 1))
| False -> ([i] :: groups, i + 1).
groupsOf legs = case foldl groupStep ([], 0) legs of (groups, n) -> List.rev (map List.rev groups).

# ---- small tools -----------------------------------------------------------

shell cmd = Proc.runNow (ProcessSpec ["/bin/sh", "-c", cmd] "" [] "" 0).
shellOut cmd = case shell cmd of
  Ok (ProcessResult 0 out err) -> out
| Ok (ProcessResult code out err) -> error "sweep: `{cmd}` exited {code}: {err}"
| Err e -> error "sweep: `{cmd}`: {e}".
shellOk cmd = case shell cmd of Ok (ProcessResult 0 out err) -> True | other -> False.
nonEmpty xs = filter (fn x -> x != "") xs.
linesOf text = nonEmpty (Str.lines text).
quote s = "'{s}'".
pad n s = case strlen s >= n of True -> s | False -> "{Str.repeat (n - strlen s) " "}{s}".
padR n s = case strlen s >= n of True -> s | False -> "{s}{Str.repeat (n - strlen s) " "}".
anyOf p xs = case filter p xs of Nil -> False | some -> True.
uniqStep acc x = case List.has x acc of True -> acc | False -> x :: acc.
uniq xs = List.rev (foldl uniqStep [] xs).
fst (a, b) = a.
snd (a, b) = b.

# ---- what a change can reach ------------------------------------------------
#
# docs/ and *.md reach nothing.  A path outside tests/, tools/ and docs/ (a
# program, the runtime, a makefile, a lock, the manifest) reaches every leg,
# and so does a tool a makefile names.  Any other test or tool reaches the
# legs that name it, directly or through a file that names it; one that no
# leg names reaches every leg, since nothing here can say what it feeds.
#
# A file directly in tests/ or tools/ is named by its stem appearing as a
# word (a path, an import, a name in a table of checks); a nested one, whose
# stem is often an ordinary word, by its last two path components.  That
# over-reaches, which only runs more legs.

wordChar c | c >= 48 and c <= 57 = True.
wordChar c | c >= 65 and c <= 90 = True.
wordChar c | c >= 97 and c <= 122 = True.
wordChar c | c == 95 = True.
wordChar c | c == 45 = True.
wordChar c = False.

edge t i | i < 0 = True.
edge t i | i >= strlen t = True.
edge t i = not (wordChar (charAt t i)).

# no measure: it walks the occurrences of w in t
hasWordFrom : unsafe String -> String -> Int -> Bool .
hasWordFrom w t i = wordAt w t (strIndexFrom w t i).
wordAt : unsafe String -> String -> Int -> Bool .
wordAt w t at | at < 0 = False.
wordAt w t at | edge t (at - 1) and edge t (at + strlen w) = True.
wordAt w t at = hasWordFrom w t (at + 1).

stemOf path =
  base = List.last (Str.split 47 path);
  dot = Str.find 46 base;
  case dot <= 0 of True -> base | False -> Str.sub base 0 dot.
tail2 path =
  parts = Str.split 47 path;
  Str.join "/" (List.drop (List.len parts - 2) parts).
# (path, key, byWord)
# These are `unsafe` only because they reach the word scan above.
leafOf path = case List.len (Str.split 47 path) == 2 of
  True -> (path, stemOf path, True)
| False -> (path, tail2 path, False).
leafPath (path, key, byWord) = path.
names : unsafe _ -> _ -> _ .
names text (path, key, byWord) = case byWord of True -> hasWordFrom key text 0 | False -> Str.contains key text.
namedIn : unsafe _ -> _ -> _ .
namedIn leaves text = map leafPath (filter (names text) leaves).

textFile path = anyOf (fn ext -> Str.endsWith ext path)
  [".fpr", ".py", ".sh", ".sol", ".toml", ".json", ".txt", ".in", ".c", ".h", ".mk", ".legs"].
readText root path = case textFile path of True -> readNow "{root}/{path}" | False -> "".

edgesOf table path = case filter (fn row -> fst row == path) table of
  Nil -> []
| row :: more -> snd row.

# no measure: it ends when a round adds nothing
grow : unsafe _ -> List String -> List String -> List String .
grow table seen frontier | frontier == [] = seen.
grow table seen frontier =
  found = uniq (List.concat (map (edgesOf table) frontier));
  fresh = filter (fn p -> not (List.has p seen)) found;
  grow table (List.append seen fresh) fresh.

serviceName body = Str.trim (Str.replace "service_leg " "" (Str.replace ")" "" (Str.replace "(" "" body))).
legText leg = case legService leg of
  True -> "{legBody leg} check-services service_checks service_worker {serviceName (legBody leg)}-check"
| False -> legBody leg.

everyLeg legs = List.range 0 (List.len legs - 1).

reaches : unsafe _ -> _ -> _ -> _ -> _ -> _ .
reaches table leaves legs path i =
  start = namedIn leaves (legText (legs ! i));
  List.has path (grow table start start).

reachOf : unsafe _ -> _ -> _ -> _ -> _ -> _ .
reachOf table leaves legs built path | Str.startsWith "docs/" path = ([], "").
reachOf table leaves legs built path | Str.endsWith ".md" path = ([], "").
reachOf table leaves legs built path | not (or (Str.startsWith "tests/" path) (Str.startsWith "tools/" path)) = (everyLeg legs, "{path}: reaches every leg").
reachOf table leaves legs built path | Str.startsWith "tools/" path and hasWordFrom (stemOf path) built 0 = (everyLeg legs, "{path}: a makefile names it, so every leg runs").
reachOf table leaves legs built path = case filter (reaches table leaves legs path) (everyLeg legs) of
  Nil -> (everyLeg legs, "{path}: no leg names it, so every leg runs")
| hit -> (hit, "{path}: {List.len hit} leg(s)").

affected : unsafe _ -> _ -> _ -> _ .
# In a copy of the tree with no .git (a worker's), the leaves are the files there.
affected root legs changed =
  leaves = map leafOf (linesOf (shellOut "cd {quote root} && (git ls-files -c -o --exclude-standard tests tools 2>/dev/null || find tests tools -type f -not -path '*/__pycache__/*')"));
  table = map (fn leaf -> (leafPath leaf, namedIn leaves (readText root (leafPath leaf)))) leaves;
  built = shellOut "cd {quote root} && cat Makefile qos/Makefile *.mk hal/*/*.mk 2>/dev/null";
  reached = map (reachOf table leaves legs built) changed;
  (uniq (List.concat (map fst reached)), nonEmpty (map snd reached)).

changedSince root ref = uniq (List.append
  (linesOf (shellOut "cd {quote root} && git diff --name-only {quote ref}"))
  (linesOf (shellOut "cd {quote root} && git ls-files -o --exclude-standard"))).

# ---- running one leg --------------------------------------------------------

mark c i = "{c.out}/legs/{Str.replace " " "0" (pad 3 (str i))}".
legLog c i = "{mark c i}.log".

# exit 77: the body recorded a skip and otherwise succeeded
scriptFor c i tree work = Str.join "\n" [
  "export SWEEP_TREE={quote tree} SWEEP_WORK={quote work} SWEEP_OUT={quote c.out}",
  "export SWEEP_COMPILER={quote c.compiler} SWEEP_MARK={quote (mark c i)}",
  "rm -f \"$SWEEP_MARK.skipped\"",
  ". {quote c.root}/checks/prelude.sh",
  "(",
  legBody (c.legs ! i),
  ")",
  "status=$?",
  "if [ $status -eq 0 ] && [ -e \"$SWEEP_MARK.skipped\" ]; then exit 77; fi",
  "exit $status",
  ""].

jobSpec cmd seconds = PipelineSpec [ProcessSpec ["/bin/bash", "-c", cmd] "" [] "" 0]
  (PipeBytes (Bytes.empty Unit)) PipeDiscard PipeDiscard (seconds * 1000) PipeFail.

startLeg c i tree work =
  u = writeNow "{mark c i}.sh" (scriptFor c i tree work);
  must (Proc.start (jobSpec "exec /bin/bash {quote "{mark c i}.sh"} > {quote (legLog c i)} 2>&1" c.opts.timeout)).

statusOf result = case result of
  Ok (PipelineResult 0 codes out errs) -> "passed"
| Ok (PipelineResult 77 codes out errs) -> "skipped"
| Ok (PipelineResult code codes out errs) -> "failed"
| Err (ProcessError "timeout" stage channel limit) -> "timeout"
| Err e -> "failed".

# a result: (leg, status, seconds, lane, first verdict or "")
report c (i, status, seconds, lane, first) =
  print "{padR 8 status} {pad 5 (str seconds)} s  {legName (c.legs ! i)}{case lane == "alone" of True -> "  (alone)" | False -> ""}".

# ---- the workers ------------------------------------------------------------
#
# A worker is (id, tree, work, rest, slot): `rest` is what is left of its
# group, and the slot is free or holds the running (leg, started, job).  A job
# is owned exactly once, so the slot is linear.

Slot 1 = Type (Free | Busy Int Int ProcessJob).
Services 1 = Type (NoServices | Services ProcessJob).

laneOf c id i = case legSerial (c.legs ! i) of True -> "serial" | False -> "worker-{id}".

finishLeg c id i t0 job = (i, statusOf (Proc.wait job), timeNow Unit - t0, laneOf c id i, "").

pollBusy c id tree work rest i t0 (state, job) = case state of
  Ok False -> ((id, tree, work, rest, Busy i t0 job), [])
| other -> ((id, tree, work, rest, Free), [finishLeg c id i t0 job]).
pollWorker c (id, tree, work, rest, slot) = case slot of
  Free -> ((id, tree, work, rest, Free), [])
| Busy i t0 job -> pollBusy c id tree work rest i t0 (Proc.poll job).
gather (workers, finished) (worker, f) = (worker :: workers, List.append finished f).

begin c id tree work group = case group of
  Nil -> (id, tree, work, [], Free)
| i :: rest -> (id, tree, work, rest, Busy i (timeNow Unit) (startLeg c i tree work)).

# hand a free worker the rest of its group, else the next group: worker 0
# takes the serial groups first, in file order.  `busy` counts the workers
# that have something to do after this round.
assignFree c serial free done busy id tree work = case free of
  g :: gs -> (serial, gs, begin c id tree work g :: done, busy + 1)
| Nil -> (serial, free, (id, tree, work, [], Free) :: done, busy).
assignNext c serial free done busy id tree work = case id == 0 of
  True -> (case serial of
      g :: gs -> (gs, free, begin c id tree work g :: done, busy + 1)
    | Nil -> assignFree c serial free done busy id tree work)
| False -> assignFree c serial free done busy id tree work.
assign c (serial, free, done, busy) (id, tree, work, rest, slot) = case slot of
  Busy i t0 job -> (serial, free, (id, tree, work, rest, Busy i t0 job) :: done, busy + 1)
| Free -> (case rest of
    i :: more -> (serial, free, begin c id tree work rest :: done, busy + 1)
  | Nil -> assignNext c serial free done busy id tree work).

endServices job =
  u = Proc.wait job;
  (NoServices, True).
pollRunning (state, job) = case state of
  Ok False -> (Services job, False)
| other -> endServices job.
pollServices services = case services of
  NoServices -> (NoServices, True)
| Services job -> pollRunning (Proc.poll job).

# when the loop ends every slot is free; this is what says so to the checker
letGo results (id, tree, work, rest, slot) = case slot of
  Free -> results
| Busy i t0 job -> letGoJob results (Proc.cancel job).
letGoJob results cancelled = results.
letGoServices results services = case services of
  NoServices -> results
| Services job -> letGoJob results (Proc.cancel job).

# no measure: it ends when the queues are empty and every worker is free
loop : unsafe _ -> _ -> _ -> _ -> _ -> _ -> _ -> _ .
loop c workers serial free waiting services results =
  polled = foldl gather ([], []) (map (pollWorker c) workers);
  u = map (report c) (snd polled);
  settle c polled serial free waiting (pollServices services) results.

settle : unsafe _ -> _ -> _ -> _ -> _ -> _ -> _ -> _ .
settle c (workersRev, finished) serial free waiting (services, servicesDone) results =
  ready = case servicesDone of True -> List.append free waiting | False -> free;
  held = case servicesDone of True -> [] | False -> waiting;
  next c (foldl (assign c) (serial, ready, [], 0) workersRev) held services servicesDone (List.append results finished).

next : unsafe _ -> _ -> _ -> _ -> _ -> _ -> _ .
next c (serial, free, workers, busy) waiting services servicesDone results = case busy == 0 and servicesDone of
  True -> letGoServices (foldl letGo results workers) services
| False -> pause c workers serial free waiting services results.

pause : unsafe _ -> _ -> _ -> _ -> _ -> _ -> _ -> _ .
pause c workers serial free waiting services results =
  u = sleepMs 250;
  loop c workers serial free waiting services results.

# one leg, alone, on worker 0
alone c firstOf i =
  t0 = timeNow Unit;
  status = statusOf (Proc.wait (startLeg c i c.tree0 c.work0));
  r = (i, status, timeNow Unit - t0, "alone", firstOf i);
  u = report c r;
  r.

# ---- verdicts ---------------------------------------------------------------

resultLeg (i, status, seconds, lane, first) = i.
resultStatus (i, status, seconds, lane, first) = status.
bad status = or (status == "failed") (status == "timeout").
expectsFail c i = legWhy (c.legs ! i) != "".
# "new": failed where it is expected to pass.  "fixed": passed where it is
# expected to fail.  "red": failed as expected.
verdict c (i, status, seconds, lane, first) | status == "skipped" = "skipped".
verdict c (i, status, seconds, lane, first) | bad status and expectsFail c i = "red".
verdict c (i, status, seconds, lane, first) | bad status = "new".
verdict c (i, status, seconds, lane, first) | expectsFail c i = "fixed".
verdict c r = "passed".

countOf c v results = List.len (filter (fn r -> verdict c r == v) results).

jsonText s = Str.replace "\n" " " (Str.replace "\"" "\\\"" (Str.replace "\\" "\\\\" s)).
jsonLeg c (i, status, seconds, lane, first) = Str.join "" [
  "    ", chr 123, "\"name\": \"", jsonText (legName (c.legs ! i)), "\", \"status\": \"", status,
  "\", \"verdict\": \"", verdict c (i, status, seconds, lane, first), "\", \"seconds\": ", str seconds,
  ", \"lane\": \"", lane, "\", \"first\": \"", first, "\", \"log\": \"", jsonText (legLog c i), "\"", chr 125].

ordered results = List.concat (map (fn i -> filter (fn r -> resultLeg r == i) results)
  (List.range 0 (foldl (fn m r -> Numeric.max m (resultLeg r)) 0 results))).

timeOf c (i, status, seconds, lane, first) = "{seconds} {legName (c.legs ! i)}".

writeResults c results seconds =
  u = writeNow "{c.out}/results.json" (Str.join "" [
    chr 123, "\n  \"jobs\": ", str c.opts.jobs, ",\n  \"seconds\": ", str seconds,
    ",\n  \"compiler\": \"", jsonText c.compiler, "\",\n  \"legs\": [\n",
    Str.join ",\n" (map (jsonLeg c) (ordered results)), "\n  ]\n", chr 125, "\n"]);
  writeNow "{c.out}/times" (Str.join "\n" (map (timeOf c) (ordered results))).

# ---- preparing the trees ----------------------------------------------------

exports c tree = Str.join "\n" [
  "export SWEEP_TREE={quote tree} SWEEP_WORK={quote "{c.out}/prepare"} SWEEP_OUT={quote c.out}",
  "export SWEEP_COMPILER={quote c.compiler} SWEEP_MARK={quote "{c.out}/prepare/mark"}"].

copyTree c = "(cd {quote c.root} && git ls-files -c -o --exclude-standard -z | rsync -a --from0 --ignore-missing-args --files-from=- ./ \"$SWEEP_TREE/\") || exit 1".
copyWorkers workers = "for n in $(seq 0 {workers - 1}); do w=\"$SWEEP_OUT/worker-$n\"; mkdir -p \"$w\" && cp -R \"$SWEEP_TREE\" \"$w/tree\" && mkdir -p \"$w/tree/build\" \"$w/tree/.qos/build\" && ln -s \"$SWEEP_OUT/units\" \"$w/tree/build/units\" && ln -s \"$SWEEP_OUT/units\" \"$w/tree/.qos/build/units\" || exit 1; done".

prepareScript c workers = Str.join "\n" [
  exports c (case c.opts.inPlace of True -> c.root | False -> c.snapshot),
  "mkdir -p \"$SWEEP_OUT/legs\" \"$SWEEP_OUT/units\" \"$SWEEP_OUT/prepare\" \"$SWEEP_OUT/worker-0\" || exit 1",
  case c.opts.inPlace of True -> "true" | False -> copyTree c,
  ". {quote c.root}/checks/prelude.sh",
  "make -s -C \"$FPRISC_ROOT\" fpr || exit 1",
  "make -s -C qos portable || exit 1",
  case c.opts.inPlace of True -> "true" | False -> copyWorkers workers,
  ""].

servicesScript c = Str.join "\n" [
  exports c c.root,
  ". {quote c.root}/checks/prelude.sh",
  "exec python3 tools/check-services.py --jobs 2 --output \"$SWEEP_OUT/services\"",
  ""].

workerOf c n = case c.opts.inPlace of
  True -> (n, c.root, "{c.out}/worker-{n}", [], Free)
| False -> (n, "{c.out}/worker-{n}/tree", "{c.out}/worker-{n}", [], Free).

# ---- choosing and ordering --------------------------------------------------

timeFor times name = case filter (fn t -> snd t == name) times of Nil -> 0 | t :: more -> fst t.
weightOf times legs group = List.sum (map (fn i -> timeFor times (legName (legs ! i))) group).
heavierFirst times legs acc g =
  w = weightOf times legs g;
  List.append (filter (fn h -> weightOf times legs h >= w) acc) (g :: filter (fn h -> weightOf times legs h < w) acc).
timeLine line =
  sp = Str.find 32 line;
  (parseInt (Str.sub line 0 sp), Str.sub line (sp + 1) (strlen line - sp - 1)).

absolute root path = case Str.startsWith "/" path of True -> path | False -> "{root}/{path}".

laneWord l = case legSerial l of True -> "serial  " | False -> "parallel".
followWord l = case legFollows l of True -> "+ " | False -> "  ".
redWord l = case legWhy l == "" of True -> "" | False -> "(red) ".
listLine legs i = print "{laneWord (legs ! i)} {followWord (legs ! i)}{redWord (legs ! i)}{legName (legs ! i)}".
listAll legs chosen =
  u = map (fn g -> map (listLine legs) g) chosen;
  0.

newLine c r = print "** NEW FAILURE: {legName (c.legs ! resultLeg r)}\n   {legLog c (resultLeg r)}".
fixedLine c r = print "** NOW PASSES: {legName (c.legs ! resultLeg r)}\n   remove its `@ expect fail` line from checks/legs".
aloneLine c r = print "   passed alone after failing beside other legs: {legName (c.legs ! resultLeg r)}".
passedAlone (i, status, seconds, lane, first) = and (bad first) (status == "passed").

summary c results seconds total =
  new = filter (fn r -> verdict c r == "new") results;
  fixed = filter (fn r -> verdict c r == "fixed") results;
  red = countOf c "red" results;
  u0 = print "SWEEP: {countOf c "passed" results + List.len fixed} passed, {List.len new + red} failed, {countOf c "skipped" results} skipped (of {List.len results} legs run; {total - List.len results} not run), {seconds} s";
  u1 = print "       {red} of the failures are expected (`@ expect fail` in checks/legs); {List.len new} are new";
  u2 = map (newLine c) new;
  u3 = map (fixedLine c) fixed;
  u4 = map (aloneLine c) (filter passedAlone results);
  skipped = countOf c "skipped" results;
  u5 = case skipped of 0 -> Unit | n -> print "NOTE: {n} leg(s) skipped, which is not a pass (--strict makes this fail)";
  case new of
    Nil -> (case and c.opts.strict (skipped > 0) of True -> 1 | False -> 0)
  | some -> 1.

firstStatus first i = case filter (fn r -> resultLeg r == i) first of Nil -> "" | r :: more -> resultStatus r.
isNew c first i = anyOf (fn r -> and (resultLeg r == i) (verdict c r == "new")) first.

ensureNew out = case shellOk "mkdir -p \"$(dirname {quote out})\" && mkdir {quote out}" of
  True -> out
| False -> error "sweep: {out} exists already; --output must be a new directory".

prepared c workers =
  u = writeNow "{c.out}/prepare.sh" (prepareScript c workers);
  case shellOk "/bin/bash {quote "{c.out}/prepare.sh"} > {quote "{c.out}/prepare.log"} 2>&1" of
    True -> c
  | False -> error "sweep: preparation failed; see {c.out}/prepare.log".

startServices c waiting = case waiting of
  Nil -> NoServices
| some -> Services (must (Proc.start (jobSpec "exec /bin/bash {quote "{c.out}/services.sh"} > {quote "{c.out}/services.log"} 2>&1" 5400))).

sweepLegs : unsafe _ -> _ -> _ -> _ -> _ .
sweepLegs opts root legs chosen =
  began = timeNow Unit;
  out = ensureNew (absolute root (case opts.out == "" of True -> "build/sweep/run-{began}" | False -> opts.out));
  compiler = Str.trim (shellOut "cd {quote root} && cd \"$(python3 qos.py fprisc --print)\" && pwd");
  workers = Numeric.max 1 (Numeric.min opts.jobs (List.len chosen));
  c = prepared {opts = opts, root = root, out = out, compiler = compiler, legs = legs, snapshot = "{out}/snapshot",
       tree0 = (case opts.inPlace of True -> root | False -> "{out}/worker-0/tree"), work0 = "{out}/worker-0"} workers;
  times = case opts.times == "" of True -> [] | False -> map timeLine (linesOf (readNow (absolute root opts.times)));
  hasSerial = fn g -> anyOf (fn i -> legSerial (legs ! i)) g;
  hasService = fn g -> anyOf (fn i -> legService (legs ! i)) g;
  serial = filter hasSerial chosen;
  parallel = filter (fn g -> not (hasSerial g)) chosen;
  waiting = filter hasService parallel;
  free = foldl (heavierFirst times legs) [] (filter (fn g -> not (hasService g)) parallel);
  u3 = writeNow "{out}/services.sh" (servicesScript c);
  first = loop c (map (workerOf c) (List.range 0 (workers - 1))) serial free waiting (startServices c waiting) [];
  again = case opts.retry of False -> [] | True -> filter (fn g -> anyOf (isNew c first) g) chosen;
  redone = List.concat (map (fn g -> map (alone c (firstStatus first)) (filter (fn i -> not (legService (legs ! i))) g)) again);
  results = List.append (filter (fn r -> not (anyOf (fn d -> resultLeg d == resultLeg r) redone)) first) redone;
  seconds = timeNow Unit - began;
  u4 = writeResults c results seconds;
  summary c results seconds (List.len legs).

entry : unsafe _ -> _ .
entry argv =
  opts = options argv;
  root = must (IO.cwd Unit);
  legs = legsOf (readNow (absolute root opts.manifest));
  changed = case opts.since == "" of True -> opts.changed | False -> List.append opts.changed (changedSince root opts.since);
  narrowed = case changed of Nil -> (everyLeg legs, []) | some -> affected root legs changed;
  u0 = map (fn why -> print "sweep: {why}") (snd narrowed);
  picked = case opts.only of
    Nil -> fst narrowed
  | texts -> filter (fn i -> anyOf (fn t -> Str.contains t (legName (legs ! i))) texts) (fst narrowed);
  chosen = filter (fn g -> anyOf (fn i -> List.has i picked) g) (groupsOf legs);
  u1 = print "sweep: {List.sum (map List.len chosen)} of {List.len legs} legs, {opts.jobs} worker(s)";
  case opts.list of True -> listAll legs chosen | False -> sweepLegs opts root legs chosen.

> Script.exit (entry (args Unit)).
