# FP-RISC repin: typed client state, the plane's reasons, std/ui apps

Date: 2026-10-16. Kind: implementation record. FP-RISC `1d4309b` (fprisc
`docs/2026-10-16-CLIENT-STATE-AND-GAPS.md`), then `9699dbd` the same day
for the five red legs (below): the Sol profile's `Sys.loop` and the dedup
ceiling's stated reason.

## Builds again

No QOS kernel or application had built since FP-RISC's 2026-10-15 safety
tightening: every module pins the frozen std/actor v3.0
(`.fpr/store/201a0e9bf98a5154.fpr`), and that blob was not on
`core/trusted-modules.txt`, so it was checked as application code (ten
refusals in it, and every caller of it refused in turn: std/blockio,
std/net, blockep). The blob is byte-identical to fprisc's allow-listed
`std/actor.fpr` at `dcf9fbc` (2026-10-13); it is listed, as its v1.0 and
v2.0 already were. Nothing was re-frozen.

## Deaths carry their reason

The plane's `fail` is the kernel's `fpr_actor_fail`, which keeps the
reason, so a loaded process that traps reaches its launcher as `failed:
dead actor: errorproc: deliberate`, and a caller the block layer
fail-stops hears `dead actor: blk: request timed out (the disk worker
stalled)`. A `send` to an ended actor is still the bare `"dead actor"`.
The tests that compared a death to the bare text read the prefix or the
reason now: errornative (`tools/error-process-check.sh`), mailboxproc (a
killed actor is `dead actor: killed`), nativerefusal, blockservice,
diskstall, diskstallp (`tools/disk-harden-check.py`), netstall, netorphan,
netactor, netactorprocess, memoryproc, diskclaimrace, diskreclaimcancel,
diskresetcancel. FP-RISC also turned a refused VALUE at a primitive (an
index past the end, `chr` of a non-byte) into such a failure.

## Apps on std/ui

- `programs/liveboard.fpr` is on std/ui with typed client state (a `Tab`
  enumeration, `G.sendWith codec Add @Client.draft`); its check sends the
  page's typed `"*"` form, and its reload leg rebuilds with the compiler
  that built it (`$FPR_HOME/fpr`, unless `FPR` names another).
- `programs/maapp.fpr` (std/ma, retired) is `programs/uiapp.fpr`: the same
  render harness over std/ui, run on bare metal by check-all
  (`UIBEGIN`, `ui: ... same-statics`).
- `tests/mvuweb.fpr` styles its root with typed utilities: std/view
  generates CSS for those, not for class names, so its first paint had an
  empty stylesheet and the smoke's liveview leg failed.

## Verification

- `./qos.py test`: 16/16 (the liveview leg failed before the mvuweb fix).
- `check-all.sh` (152 legs): every leg this change touched passes when run
  again on the new pin -- native block service, disk hardening (native and
  Portable), failure injections, admission, the mailbox and error process
  legs, both liveboard legs, first-class paths (the schema now also lists
  `ks`, a List leaf: `leaves=5`), the std/ui harness.
- Five legs were red at the previous pin (FP-RISC `573cfd3`) as well, so
  not from this change; nothing had built to show them. All five are green
  the same day:
  - dedup ratchet: fprisc `compiler/Sol/Infer.hs` had grown past its
    ceiling by primitive declarations only; with `Sys.loop` it is 132 and
    the ratchet says so with the reason (fprisc);
  - the sketch tier: `sketch-mvutick.sol` needed `Sys.loop` under
    `fpr sol`, which fprisc's Sol profile has now;
  - Vec record folds: the leg expected x64 to report its specialization
    tier off; it has been on since fprisc `28dcacc`, so the leg expects the
    same dualized fold and named decline as on RISC-V;
  - Timer.qa: `tests/timer.fpr` and `tests/timerroute.fpr` no longer kill
    the timer service, which fprisc refuses since `285d35e` (the bound
    timer actor is the machine's, SUPERVISION S7);
  - sysdisk: `tests/sysed1.fpr` and `tests/sysed2.fpr` declare `editLine :
    String -> String`; inferred, v1's `s = s` was `a -> a`, so the reload
    gate refused v2 as a changed checked type. `sysbad` is still refused.
