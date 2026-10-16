# FP-RISC repin: typed client state, the plane's reasons, std/ui apps

Date: 2026-10-16. Kind: implementation record. FP-RISC `1d4309b` (fprisc
`docs/2026-10-16-CLIENT-STATE-AND-GAPS.md`).

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
- Red, and red at the previous pin (FP-RISC `573cfd3`) as well, so not from
  this change; they could not be seen before because nothing built:
  - dedup ratchet: fprisc `compiler/Sol/Infer.hs` is 131 lines, the
    ceiling 127 (last changed 2026-10-13);
  - sysdisk: the loader refuses `sysed2` as "checked type, contract or
    ABI changed for an export";
  - Timer.qa: the aux-hart CLINT bridge leg;
  - Vec record folds: the compile-note half of the leg (the run prints
    `recfold: OK`);
  - the sketch tier's `sketch-mvutick.sol`: `Sys.loop` is unbound under
    `fpr sol` (its paths and hello parts pass).
