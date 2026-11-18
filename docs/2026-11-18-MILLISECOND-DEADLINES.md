# Millisecond deadlines: QOS re-pinned on the new std/actor

Date: 2026-11-18. Kind: implementation record, the time fix the
[qlink record](2026-11-18-QLINK.md) left to M5, done ahead of it because it
blocked any Spectre-84 session longer than 107 s. FP-RISC `b8a29c82`
(`fprisc.lock.json` bumped from `22ed0c71`).

## The change

On RV32, Int is 31 bits. `Sys.mtime` (10 MHz ticks) fits for 107 s, and
`std/actor` built its deadlines from it in microseconds, so after 107 s of
uptime `intMax - now` overflowed and the next storage call panicked. The owner
chose milliseconds on every target:

- FP-RISC: a new primitive `Sys.uptimeMs` (milliseconds since boot, panics
  rather than wraps; 31-bit milliseconds last 12.4 days), and `std/actor`
  deadlines in milliseconds (`nowUs` became `nowMs`; `deadlineAfter ms` no
  longer multiplies by 1000).
- QOS pins `std/actor` as a frozen store module, so every pinned module above
  it got a new version. A one-off script made the edits and minted each
  version with the compiler's own AST hash (probing a `#0000000000000000`
  pin), dependencies first.

## What moved

19 store versions, all with the same rewrite: `nowUs` to `nowMs`, literal
microsecond offsets (`nowMs Unit + 10000000`) to milliseconds,
`Wire.defaultMs * 1000` to `Wire.defaultMs`, the lease lifetime
(`60000000` to `60000`), the `qsys` margin check, and microsecond elapsed-time
bounds in tests.

| Module | Was | Now |
|---|---|---|
| std/actor | 201a0e9bf98a5154 (v3.0) | 2de24bf2bdd5cb87 (v4.0) |
| std/storage | a8f7ee14e1efae76 | d3bc6af554583437 |
| std/blockio | 8b4ffa1467ca03a5 | 12684c106eacea7e |
| std/block | 615ea5947fe13b00 | ac4ea92ddd273d16 |
| std/fs | 19932fc6492e8a87 | e2eac59ab17e6dd5 |
| std/lifecycle | 2ec580ebc636437d | 070befedf2d758e0 |
| mods/svc | 75479fb6d5f34670 | b4e4e109ca696787 |
| mods/ep | c66ad65e68dd97f5 | d65056c9d7dc9c18 |
| mods/epdeadline | 08a8ecf9d7c57d85 | 96e69ecbbd8c7fce |
| mods/epservice | e8bce05a1ddf73db | 436f606333c44f26 |
| mods/epclient | e09b467f350a5396 | decd41e2d3f54b1b |
| mods/blockep | bd295a609815dadd | e39ef0a30e25ff08 |
| mods/leaseslots | efa81888e7fe1099 | 0eba65251ebb9450 |
| mods/net | 464ca3ee0d89bc64 | 9450dfa41b157181 |
| mods/qlog (v22) | 045dbfa936f832eb | 75482a12ec46d57d |
| mods/files (v2) | 2b1a808ceef52eb5 | c7ff5f363c767e4b |
| mods/qlog (v10) | 7022992c8e4a9fba | 706553405f780d64 |
| std/fs (v5) | 84826bc9e8ddb4b5 | 032f415a28970b29 |
| mods/files (v3) | c7ff5f363c767e4b | 507d78ba90515060 |

The QLog versions also carry the `blkFlush dev` fix from the
[block class record](2026-11-18-BLOCK-CLASS-AND-BOARDS.md). 151 tree files
had their pins rewritten; `fpr.lock`, `.fpr/versions.db` and
`core/trusted-modules.txt` follow.

`blkWaitInbox`, the one C primitive that takes an FP-RISC deadline
(`std/blockio`'s poll loop), now reads milliseconds in both implementations
(`hal/classes/block.c`, `qos/appside/hal.c`).

## Findings on the way

- **A lock-driven cascade misses versions the lock does not list.**
  `mods/files` v2 (pinned by `tests/storagedeadlines`) pinned an older
  `std/fs` v5, which pinned QLog v10 and the old `std/actor`. None of the three
  were in `fpr.lock`, so the first pass left them on microseconds. The test
  then mixed clocks: a millisecond deadline read against a microsecond clock
  had expired before it was admitted, so Files kept a hung child and never
  counted it against its recovery quota. The second pass walked every store
  blob reachable from the tree's pins, not the lock; now no reachable module
  pins an old hash. Any later re-pin of a frozen module should start from
  reachability, not from the lock.
- **`blkWaitInbox` took microseconds.** It was the first cause of the same
  test's failure (a 20 ms budget waited 20 µs).

## Checks

- Portable (fresh disks): `storagedeadlines`, `storagebudgets`, `filessvc`,
  `filesshutdown`, `filesreclaim`, `apppolicy`, `appjobs`, `filepolicy` and
  `appsession` hold.
- `storageprotocol` (panics with `storage service: dead actor`) and
  `portableshutdown` (pins a `std/lifecycle#1f9abfd0` that is not in the
  store) fail identically on the tree before this change; not regressions.
- QEMU virt native fixtures `blockrange`, `disknative`, `blocklifecycle`,
  `blockmemory`, `blockconform` pass.
- Spectre-84 (SD boot, qlink console, FP-RISC `b8a29c82`): a 12,000-line
  soak (996,890 bytes in 116.8 s), then `ls` works at more than 2 minutes of
  uptime, where the old image panicked at 107 s.

## qlink: a reconnect during a board stream stalled

A host that left while the board was still streaming (an abandoned soak) and
reconnected found the board resending one frame forever. Two faults:

- `qhost` repeats `HELLO` every 300 ms until answered. A late answer meant a
  second `HELLO` reset the board again after the host had already reset; the
  host then acknowledged a frame the board had not sent in its session, the
  board ignores acknowledgements beyond what it has in flight, and resent the
  same frame forever. `HELLO` now carries a host nonce, repeated on every
  retry; the board starts a new session only for a new nonce and answers a
  repeat without resetting.
- While stuck, the board resends a window (about 1 KB, 100 ms at line rate)
  with blocking writes and did not read the UART meanwhile; the host's
  acknowledgements plus its `HELLO` overflowed the 32-byte receive FIFO.
  `qlink_sruart.c` now drains the FIFO into a 1 KB ring while waiting to
  transmit, and `qhost` sends no acknowledgements before the board answers.

The lossy-wire unit test passes with the change.

On the board the abandon-and-reconnect check then failed differently: after
a host left mid-stream, the board sent nothing at all, even its boot ROM
after an FPGA reload, until a USB replug. This is the documented BL616
wedge (simple-risc `boards/tangnano20k/README.md`, "Known issue: the
USB-UART bridge stops working"): closing and reopening the UART while the
FPGA is transmitting kills the bridge, and its prescribed fix is to stop
the stream from the same session and wait for silence before closing. A
board that resends into a departed host's port makes every reconnect such
a reopen. So the board stops sending when no host is there, and the host
stops it before closing:

- The board has no session at boot. A session ends on the host's `BYE`, or
  when the host has not acknowledged for 1.5 s while frames are in flight.
  Without a session the board sends no reliable frames and drops console
  output instead of blocking (so output before a host connects is lost).
- `qhost` sends `BYE` on every exit, including SIGINT, SIGTERM and SIGHUP,
  and waits until the line has been quiet for 150 ms (at most 2 s) before
  the port closes. A host killed with SIGKILL cannot; the board still goes
  quiet after 1.5 s, so a reopen must wait that long.

Board results (Spectre-84, after a replug): a soak abandoned after 3 s
leaves the board quiet (46 bytes in the next 3 s, then nothing), and three
reconnects each run `ls`; a `qhost` killed by SIGTERM 5 s into a soak leaves
it quiet (50 bytes) and the next connection works; a full 12,000-line soak
then runs at 8,541 B/s with no CRC errors or resends, as before.

With the 150 ms quiet wait, four rounds of abandon-then-reconnect each
leave the board silent (0 bytes in the next second) and reconnect cleanly.
Once, before those rounds, the board answered every `HELLO` with two bytes
(`00 fc`, like a frame read at the wrong rate) until the bitstream was
reloaded; the bridge itself was working. Not reproduced and not explained.

## Left open

`std/mvu` still reads `Sys.mtime` directly and wraps after 107 s on RV32; it
is not pinned by anything Spectre runs yet and moves with M5.
