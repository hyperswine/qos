# Hot open-per-operation sites: none worth holding

Date: 2026-11-12. Kind: survey and measured experiment. Branch
`held-fs-endpoints` (main `0e2cdb9` + `linear-endpoint`).

The roadmap's step 3 was to rank the `Svc.read`/`Svc.write` call sites by
how often they run and move the hot ones to held endpoints (8 messages per
operation down to 2).

## What runs often

- The launcher loop (`system.fpr`, about 1000 polls a second plus a clock
  repaint per frame) already holds its five endpoints; `linear-endpoint`
  makes it close them.
- Every other `Svc.*` call is per user action, startup, latent (the keypad
  scan has no in-tree caller) or test-only. The other open-per-operation
  helpers (`EP.readOnce`/`writeOnce`, `ED.*OnceUntil`) are per command,
  launch or permission prompt.
- The one loop that opens per operation is the `std/fs` forwarder: each
  `FS.append`/`readLatest`/`replay` from pos1, terra2 and other `FS.connect`
  clients opens, operates and closes an endpoint on Files.qa.

## The experiment

`epclient v2.0` adds deadline forms (`openUntil`, `readUntil`, `writeUntil`,
`closeUntil`). The forwarder here keeps the last endpoint for each of its six
operations (linear endpoints across turns via `AC.boundary`), reuses it while
the key is the same, reopens once on "no such handle" (the Files lease ends
60 s after open and is not renewed; nothing ran, so a resend is safe), and
gives an endpoint up on any other failure.

Measured with `tests/fsbench.fpr` (branch `qlog-payload-cache`), Portable,
pinned FP-RISC, one run each:

| Operation | open per op | held |
| --- | ---: | ---: |
| Append, one key | 12.7 ms | 12.5 ms |
| Latest, 200-record key | 69.8 ms | 69.5 ms |
| Latest, alternating keys | 0.96 ms | 0.98 ms |

The six messages saved (about 2 us at today's held-write cost) disappear in
milliseconds of storage work, and holding delays a revoked grant until the
lease ends. **Not recommended for merge.** The storage time itself is what
`qlog-payload-cache` removes (replay 69.6 -> 1.16 ms on the same bench).
Held endpoints pay where the owner's own work is cheap, as in `epbench`; no
such loop in the tree still opens per operation.
