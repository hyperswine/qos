# Isolated service checks with bounded parallel execution

Date: 2026-10-25. Kind: implementation and validation record. Applies to the
service-runner changes based on QOS `986b025`.

`tools/check-services.py` runs the 16 service/storage checks previously listed
in the Portable CI shell loop. `tools/service_checks.py` is their shared
registry. CI and `check-all.sh` consume that registry through the runner; the
full sweep keeps a separate verdict for each check. Large KV replay, previously
in CI only, now has its own sweep leg too (163 legs total).

## Isolation boundary

A run snapshots the current tracked and non-ignored untracked QOS inputs, then
builds a fresh default Portable host against the selected FP-RISC compiler.
Each check receives a byte copy of that snapshot, including the prepared host.
Copies preserve executable permissions and timestamps; they are never hard
links into the working checkout. Git metadata, ignored build outputs, existing
disks, runtime stores and local caches are excluded. A source-content hash is
recorded in `snapshot.json`.

Each check therefore owns its source fixtures, `build/`, default `app.qa`,
plugin archives, host binaries, native kernels and disks, including fixed paths
inside older helpers such as `build-process-app.sh`. Each check also receives
its own `TMPDIR`, `XDG_CACHE_HOME` and default disk, and `FPR_PORT=0`. Ambient
runtime/device paths, compiler sockets and fault injection settings are cleared;
ambient make output/variant overrides and inherited jobserver settings are also
cleared. Tests then install their own explicit variants. The durable-storage check
no longer overrides this with a fixed global cache. Qsys honors `TMPDIR`.
The compiler daemon retains its existing unique short `/tmp/qos-fprd-*` socket
directory because Unix socket paths have a length limit.

The selected compiler is built once before scheduling. It is shared as a build
input, not copied/rebuilt per check. Normal local dependency selection still
applies (`FPRISC_ROOT`, configured path, sibling checkout); CI uses its pinned
compiler. Keep compiler inputs stable during a run, as with the existing suites.

`tools/service_worker.py` executes each test with owned subprocess sessions.
It preserves shutdown-signal delivery. It tracks explicitly launched sessions,
finds shell-created process groups inside them (including GNU timeout), kills
leftover descendants after a command ends, and cleans them up on failure,
timeout and cancellation. A process registry lets the supervisor recover when
a test interpreter itself needs forced termination. Existing compiler-daemon
helpers inherit their tracked session. These audited checks do not intentionally
launch untracked detached daemons.

## Scheduling and verdicts

The default is two workers; `--jobs` accepts one through four. The Portable
shutdown check runs exclusively before the pool because it asserts wall-clock
deadlines. All existing harts, Native/Portable variants, fault boundaries,
assertions and timeout guards remain. Each nonexclusive check is one job;
checks are not retried or reduced to make parallel execution green.

A failure does not hide other results: independent checks finish, the group
returns nonzero, and `results.json` identifies successful, failed, timed-out or
cancelled jobs. `--verdict NAME --results FILE` succeeds only for that check's
successful completion. Missing records fail. Original script-internal optional
tool skips retain their behavior; a zero exit still does not prove a skipped
Native/physical leg executed. CI installs the existing cross tools as before.

The full sweep runs this group once, then reads each individual verdict at the
original leg. Its global lock and serial treatment of other tests remain.
Service logs persist under `build/service-checks/` after sweep scratch cleanup.
The general Portable host/run leg now precedes the first shared-host consumers;
those checks no longer depend on a service check accidentally building it.

## Use and evidence

```sh
python3 tools/check-services.py --list
python3 tools/check-services.py -j 2
python3 tools/check-services.py -j 1 --only files-service --only editor-policy
python3 tools/check-services.py -j 2 --output /tmp/qos-services-new-run
QOS_CHECK_JOBS=2 ./qos.py test --all
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

An explicit output directory must be new. Runs retain `prepare.log`, the input
snapshot, per-check workspaces and `jobs/NAME/output.log`, process registries and
`results.json`. CI uploads the compact logs, manifest and result records on both
success and failure. Full workspaces stay local rather than being uploaded.

An initial attempt to time the old scripts found a pre-existing ABI mismatch:
the shared local qosp was ABI 22.105 while freshly built apps were 22.89.
That attempt is excluded from performance results. Fresh isolated host/app
builds agree, without replacing the developer's existing shared host.

## Validation and measurements

All 16 registered checks passed at two workers, split into the paired four-check
subset and the remaining twelve checks. No internal SKIP markers appeared. The
Native checks included one/two harts and virtio v1/v2; the exclusive shutdown
cases passed without changing their deadlines. Completed workers had empty
process registries. The actual sweep service-leg commands replayed those
completion records as 16 passed, zero failed, zero skipped.

The full host unittest suite passed 26 tests. These include private default
build/archive/disk paths, simultaneous ephemeral listeners, ambient runtime and
make-override normalization, exclusive scheduling, worker bounds, ordinary
command signal delivery, failure, timeout, cancellation, forced worker kill,
shell process groups, and honest partial/missing per-leg verdicts. Shell syntax,
Python compilation and CI YAML parsing also passed.

One local paired sample (including snapshot/host preparation) measured:

| Four representative checks | Wall time |
| --- | ---: |
| One worker | 399.15 s |
| Two workers | 239.86 s |

That is 1.66x, or 39.9% less wall time. The checks were files-service,
endpoint-state, editor-policy and storage-types. 480 tracked fixture/production
input paths compared byte-identically between their snapshots. The runner was
hardened during this work; prototype measurements are excluded. This is one
local sample, not a general benchmark or a hosted Linux CI time claim.

[Evidence summary](evidence/2026-10-25-service-checks/summary.json),
[one worker](evidence/2026-10-25-service-checks/serial-results.json),
[two workers](evidence/2026-10-25-service-checks/parallel-results.json),
[remaining checks](evidence/2026-10-25-service-checks/remaining-results.json),
[host tests](evidence/2026-10-25-service-checks/host-tests.log), and
[sweep verdict replay](evidence/2026-10-25-service-checks/sweep-verdict-replay.log).
Per-service logs and snapshot manifests are beside these records.

The full 163-leg sweep and hosted Linux CI have not been run. This does not
establish physical storage/power-cut qualification or board behavior.


## Combined default run and practical stopping point

The complete default 16-check group subsequently passed in one invocation:
`python3 tools/check-services.py --jobs 2`. It took **1059.54 s (17m40s)**
on this local host. All 16 passed, no internal skip markers appeared, and all
completed worker process registries were empty. The same eight process-isolation
and scheduling regressions also passed in the existing aarch64 Linux VM,
exercising the `/proc` cleanup path without installing dependencies.

Together with the paired sample's 39.9% wall-time reduction and FP-RISC's
19 removed repeated CI/Base invocations, this meets the first practical goal.
Stop here for this pass: keep two workers, the existing QOS order, all variants
and assertions, and the exclusive shutdown check. No additional cache or
scheduler layer was added to chase smaller gains. Focused `--only` checks remain
the normal edit loop; full runs remain integration gates.

[Combined results](evidence/2026-10-25-service-checks/combined-results.json),
[combined run log](evidence/2026-10-25-service-checks/combined-run.log), and
[Linux process regressions](evidence/2026-10-25-service-checks/linux-process-tests.log).
This is local and VM evidence, not hosted Linux CI or a full 163-leg sweep.
