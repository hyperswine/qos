# Development source saves to QOS publication — 2026-10-04

The Portable development loop now connects the existing host compiler daemon to
immutable QOS publication and the owned MVU runner. Register source files when
launching an app:

```
./qos.py run app.fpr --watch-module math=path/to/math.fpr
```

Registration starts the compiler daemon automatically. Paths resolve relative
to the caller's workspace; names are lowercase identifiers of at most 16
characters. Only explicitly registered files can be watched. The app opts into
`MV.runWatched` with `Dev.watchFrom publisher "math" loadedHash`, where `publisher`
is the one `std/qpublication` actor for its catalog. The reload adapter still
calls `LR.loadPublished` and adopts a complete new environment on success.

## Build and publication order

The daemon's `publication:<name>` operation accepts source bytes; `watch:<name>:<hash>`
reads a registered source and returns either `Same` or a versioned package. It
uses a private per-module source store under `FPRD_BUILD/fprd-versions`:

1. Run normal `fpr commit` checking and compatibility classification. Dependencies
   must form a pinned closure. Incompatible changes are refused without `--major`.
2. Read the committed version binding and build its immutable source blob with
   the existing relocatable `plugin-qa` pipeline. Mutable scratch source is not
   the build input. Packages are cached by root identity and host/ABI/codegen.
3. Return a framed name/version/root-hash header and complete QA bytes through
   the existing compiler syscall channel. The daemon neither writes QOS storage
   nor attaches runtime code.
4. `std/devreload` calls the QOS publisher, waits for image and catalog writes to
   succeed, then sends the typed reload notification onto the runner-owned port.
5. The runner's adapter resolves the durable archive and passes the actual
   loaded baseline and candidate identities through the existing runtime gate.

`Dev.publishSource me publisher name from source` exposes the same path for an
in-app editor's source string, returning the published Reload identity. The
`std/compile` wrappers decode packages and refuse malformed headers.

Invalid source and incompatible signatures leave the old publication and model
intact. Repeated identical source bytes reuse the last compiler reply. Unchanged
accepted identities return no package and cause no writes. A QOS write failure
retains the worker's known hash, so the frozen package is retried on the next
poll; only successful publication advances it. Diagnostics are logged once per
changed error. Each worker turn resets temporary allocation while retaining its
state. Persistent daemon version histories are protected by a per-module writer
lock, including across daemon processes.

## Lifecycle and evidence

`qos.py run` owns a short private socket, checks daemon startup before running the
app, and reports startup logs on refusal. Its context closes the compiler process
group (including an active build), reaps the daemon and removes the socket on
normal exit, Ctrl-C or termination. This avoids long Unix-socket paths in nested
workspaces and orphan compiler services after a development run.

`tools/dev-publication-check.py` is in `check-all`. It runs a real app on one/four
Portable harts, edits a registered source file through invalid, incompatible and
compatible versions, and checks retained model state, old callable code, new
code, exactly two source versions and exactly two QOS publications. It injects
one catalog upload failure and proves the unchanged compiled package is retried.
It checks owned worker shutdown and daemon/socket cleanup, and separately
terminates a live run to verify cleanup. No modules are seeded onto its test disk:
both versions arrive through the real compiler channel.

The legacy editor compile operation and legacy self-host package/reload example
also passed. The self-host example now declares `String -> String` in both
versions: its previously polymorphic first version disagreed with the string-only
replacement under the checked reload gate.

## Remaining work

Whole-program restart for incompatible versions remains separate. This loop
refuses them instead of generating migrations or restarting the app. Runtime
refusals after successful publication still require explicit rebasing policy.
Source watching follows the named root; pinned dependency changes require an
updated root pin. Failed compiler/build replies are cached until another save
(except writer-lock contention, which retries).

Compilation uses the existing synchronous compiler channel and can pause work on
its hart; this stage makes no responsiveness or WCET claim while compiling. Native
QOS has no equivalent development compiler/upload bridge verified here. The
existing compiler-channel reply-size limit still applies. The catalog still
requires one QOS publisher and reserved immutable keys, and has no history
checkpointing or code-image reclamation. Full QOS check-all was not rerun.
