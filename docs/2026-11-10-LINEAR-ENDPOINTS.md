# Owned endpoints: mods/epclient

Date: 2026-11-10. Kind: a new module and its first callers, tested. Branch
`linear-endpoint` on main `4e60743`, FP-RISC pin unchanged (`e138e65`).

## Why

QOS used linear types in 9 places (survey of 10 Nov: `std/uart`, `endpointstate`,
`runprog`, `appjobs`, `std/hosted`, `std/hostedtimers`). Endpoints, the contract
every URL is reached by, were not among them. `EP.open` answers `(owner, handle)`:
two Ints that may be copied, kept after close or forgotten, while the owner holds
the handle until Close. The survey found the expected consequences:
`system.fpr` opened the launcher's five endpoints and never closed them,
`tests/kbdread.fpr` never closed its poll endpoint, `tests/filessvc.fpr` opened one
only to learn its owner, and `(0, 0)` stood for "not opened".

## The module

`programs/mods/epclient.fpr` (`epclient v1.0#5e2a0f910e610193`):

- `Endpoint 1 = Type (Endpoint Int Int)`, linear.
- `open : Int -> Int -> String -> String -> Result Endpoint String`.
- `read`/`write` answer `(Result IoV String, Endpoint)`: the endpoint comes back.
- `close`, `closeWithin ms` consume it. `owner : Endpoint -> (Int, Endpoint)`.
- `readClose`, `writeClose`: one operation, then close.
- `Route = Type (NoRoute | Route Int Int)`, plain data, for a holder that keeps an
  endpoint open for a long time and hands copies around. `routeOf` gives a route
  and the endpoint back; `readRoute`/`writeRoute` use it. A route whose endpoint
  was closed is answered by the owner as any unknown handle is.

The compiler now refuses an endpoint that is never closed ("used 0 time(s)"),
closed twice, or used after close.

**Why a new module and not ep v4.** The first attempt changed `ep.fpr` itself. A
v4 client talking to the v3 namespace failed at once (`register` answered
`Ok ` and `openAt`'s tuple pattern did not match): constructor tags belong to a
module version, so every module exchanging `Ep`/`Ns`/`OpenRep` messages would have
had to move to v4 together, and with them every frozen module pinning those. The
new module uses ep v3's own messages (the same pinned version), so it talks to
every namespace and owner unchanged, and callers move one at a time.

**Raw `ep` stays.** It is the wire protocol, unchecked. Owners use it, and so do
the tests of owners' defences against misbehaving clients, which have to misbehave:
`blocknamespace` (read after close, another client's handle), `qsysfail` (stale
reads, deliberately held handles), `filepolicy`. They were not moved.

## Callers moved

- **`system.fpr`**: the builtin launch (`runLauncher`) opens the launcher's five
  endpoints as owned endpoints, gives the capability set a route to each
  (`EC.NoRoute` where not granted or refused, in place of `(0, 0)`), and closes
  all five when `launcher_main` returns. Before, they were never closed. `Caps` is
  copied into every `svc*` call, so it carries routes, not owners.
- **graphics**: `GX.attach` answers an owned endpoint; `GX.meshes` hands it back.
  `Services.graphics` returns it. dungeon, terra2, guishell (Main) and
  `tests/gfxshare` take the owner id with `EC.owner` and close the endpoint at the
  end; guishell's shutdown uses `EC.closeWithin`.
- **Tests**: `epecho`, `epproc` (its ungranted probe now closes if it opens),
  `kbdread` (the poll endpoint is now closed), `epbench`, `filessvc` (closes after
  killing the owner).
- `tools/guishell-check.py`'s generated fault program attaches through the owned
  API and closes after killing the graphics owner.

## The lock

`./qos.py lock` adds the 14 epclient pins and the three `tests/epbench.fpr` pins
main's `fpr.lock` was missing (the stale lock behind the `versions` check-all
failure and the Pi build's refused `lock --check`). `lock --check` passes.

## Checks

With the pinned compiler (`e138e65`):

- Pass: `lock --check`, epecho, filessvc, gfxshare, kbdread, `tests/guishell.fpr`,
  `tools/epproc-check.sh` (native, QEMU), the QOSNative kernel boot to the launcher
  (`system.fpr` built with "linearity OK"), epbench, and Main Profile
  (`tools/guishell-check.py`, including the graphics-death injection).
- terra2 compiles (14 min).
- Fail, as on main: the native instruction ratchet (`Sys.ready` unbound in the
  tool's build, identical at `4e60743`) and Graphics.qa (`gfxapps-check.py`; here
  its terra2 build hit the check's own timeout). Both are among the nine known
  check-all failures.
- epbench, three alternating runs, main (raw `ep`) / branch (`epclient`): held
  write 722-753 / 485-684 ns, open-write-close 2,332-5,797 / 1,899-2,114 ns. The
  owned API costs nothing measurable; the spread is placement noise.
- `epclient.fpr` and `tests/epecho.fpr` also check clean with fprisc main plus the
  record-update fix (stricter callable ownership).
- Not run: the full check-all sweep, the Pi.

## Left

- Console capture, GPIO pins and netpolicy buffers (the survey's next candidates).
- Other modules that open endpoints and still use raw `ep` (`std/fs`,
  `std/loader`, the app session modules) can move when they are next touched.
- Hosted MVU models cannot hold an `Endpoint`: `std/hosted` gives `view` and
  `subs` the model and keeps it, so `model` must be unrestricted
  (fprisc `docs/2026-11-10-RECORD-UPDATE-OWNERSHIP.md`). Such apps hold a
  `Route` while a service owns the endpoint.
