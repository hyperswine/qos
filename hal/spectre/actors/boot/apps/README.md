# Running a separately compiled program on Spectre

Build from the QOS root with:

    sol hal/spectre/actors/boot/build-integrated.sol /tmp/spectre-build    # builds every app fixture

This invokes the FP-RISC RV32 Builtin compiler, separates generated functions
for section garbage collection, links an entry adapter, and rejects unexpected
relocation kinds. It emits a flat position-independent image and an ASCII hex
package for transfer through the existing create command. The kernel does not
link hello.fpr or its image. Store the single line from hello.sxa as the
contents of apps/hello.sxa, then enter:

    run apps/hello.sxa

The shell reads the named record with FS.readLatest and starts an application
actor. Use the returned slot number with `status SLOT` or `stop SLOT`.
Each of the two aligned execution windows holds 4 KiB. The serial create command accepts
1024 ASCII characters, including the command and file name.

See [actor app ABI and board check](ACTOR-APPS.md) for the SXA2 build,
cooperative scheduling contract and current acceptance test. The earlier
check-app.py and board.log document the original synchronous SXA1 milestone. check-job.py and job-board.log record the subsequent single-job milestone.
