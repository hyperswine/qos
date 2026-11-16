# Portable Sol sessions and Spectre Native bring-up

Design decision and bring-up note, 15 November 2026. These are separate targets.
Neither Portable app default has changed in this revision.

## QOS Portable: Sol is the default interactive language

Opening Terminal should attach to an already-running host Sol REPL. Closing the
window detaches the display; reopening it retains definitions and the guest
working directory. Start the service with QOS Portable and end it with the guest.
Scope the session to the guest user; do not share bindings across independent
guests. Use FP-RISC's existing `fpr sol --repl` evaluator and its per-command
transactions. The Terminal is its guest input/output frontend. The Editor should
create Sol buffers, suggest `.sol` on Save As, and run the saved guest script as
Sol. Opening an existing FP-RISC file must still respect its language. Keep an
explicit FP-RISC mode. Decide separately whether Editor runs should publish
definitions into the interactive session; default to isolated runs to avoid
unexpected redefinition.

The host supplies computation, not a second disk. Select a guest filesystem
provider when constructing the Sol session and pass guest-scoped capabilities
through to the QOS file service. Resolve paths, cwd, stat/list, reads, writes,
rename/delete and user module loads against the guest namespace. A prelude can
shadow names for convenience, but a native builtin, import, journal recovery or
subprocess must not silently fall back to the host filesystem. Trusted shipped
modules can come from a separate read-only runtime namespace. Disable host
shell/process escapes until they have an explicit capability policy.

First wire read/list and read-only evaluation. Enable writes only when transaction
validation, commit and recovery have a defined guest-side contract; mapping each
buffered write to an independent RPC does not make a multi-file commit atomic.
Acceptance: save a Sol file in Editor, import and read it from Terminal, write a
guest file and reopen it in Editor, reattach with bindings intact, and verify
a host-only sentinel cannot be read, imported or changed. A failed command must
discard buffered guest writes. Restart the guest to distinguish persistent files
from ephemeral REPL bindings.

## QOS Native: Spectre

Use **Spectre** for the Simple-Risc system running QOS Native. Keep the existing
simple-risc repository, Tang Nano machine identifiers and fprisc-84 hardware
preset names so current build tools remain usable. Portable's host Sol service
is not a dependency of Spectre.

[The original port plan](2026-11-12-TANG-NANO-QOS-NATIVE.md) describes the
scheduler, device and app gates. The first buildable slice is
[the timer probe](../hal/spectre/timer.S): board startup enters foreground code,
which installs mtvec, arms the timer, and waits for two machine timer interrupts.
Only the resumed foreground prints the success marker. It is a machine probe,
not a running QOS kernel.

To reproduce in an empty build directory, set QOS and FPRISC to the respective
checkout paths and run:

```sh
pin=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["revision"])' "$QOS/fprisc.lock.json")
for file in crt0.S link.ld; do
  git -C "$FPRISC" show "$pin:machine/tangnano20k/$file" > "$file" || exit 1
done
riscv64-unknown-elf-gcc -march=rv32im_zicsr -mabi=ilp32 -nostdlib -nostartfiles \
  -T link.ld -Wl,-Map,timer.map crt0.S "$QOS/hal/spectre/timer.S" -o timer.elf
riscv64-unknown-elf-objcopy -O binary timer.elf timer.bin
```

With pin 566870c3 the host build produced a 416-byte upload image. Physical
acceptance is pending: identify the fprisc-84 board and UART, upload via its ROM,
and capture `spectre timer-v1: two timer returns OK`. Repeat after reset.
Then link the real single-hart QOS actor/context-switch paths, audit atomic
helpers on RV32IM, and qualify timer wake and UART RX delivery before SD autoboot
or application loading. The probe itself is volatile; uploading it is not a
standalone cold boot.
