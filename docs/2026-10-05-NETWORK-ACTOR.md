# Frame HAL and network actor checkpoint

RV64's production virtio NIC HAL now exposes copied Ethernet frames, copied
MAC bytes, transmit and interrupt acknowledgement. It does not parse packets,
choose peers, buffer TCP payloads or select protocol replies. Legacy native
`netPoll/netRead/netWrite/netClose` entry points refuse direct callers.

`std/net` v1.0 (`e014c97bab46e124`) is the dedicated network actor. It serializes
poll/read/write/close requests, runs the allocation-free `netpolicy.fpr` parser
and encoder, retains its fair-poll cursor and MAC, and drives at most 32 received
frames before checking its mailbox. Writes use the policy's 1200-byte segment
limit. Native empty reads send FIN and release the peer; writes to closed
peers return an error without stopping the owner. C keeps the fixed, image-lifetime protocol arena, boxed/raw conversions,
String allocation and copying, NIC queues/DMA, atomics, fences and TX deadlines.
The opaque arena is accessible only to the installed owner.

Startup installs one candidate using CAS; losing candidates die before device
initialization. Status confirms initialization before clients proceed. Requests
and replies use the pinned actor module's correlation protocol. The creator can
permanently stop admission. Repeated stop is accepted; later transport requests
are refused. A failed owner stays installed and is never replaced or replayed.
Stop is a cooperative creator check on the message's caller handle, not a
security boundary against forged messages. Stop does not reset the NIC, flush
traffic, close every physical connection or reclaim DMA memory.

System starts the kernel owner before applications and stops admission before
Files shutdown. A missing NIC leaves networking offline without blocking storage
bootstrap. Loaded native processes receive the kernel owner through the shared
boot callback. They do not create private NIC owners, so unloading their images
does not free buffers still used by the NIC. Native runtime ABI v4 is required;
older process images must be rebuilt and are rejected by the loader.

Portable and RV32 use the same actor protocol over their compatibility C
transport. Ethernet frames and raw policy access remain unsupported there. The
RV64 transport remains the fixed 10.0.2.15:80, four-peer QEMU slirp demonstration:
16 KiB RX per peer, 1 KiB reads, no retransmission, congestion control or
TIME_WAIT. One native TX wait occupies the network service until completion or
its deadline; a device failure can stop all peers while unrelated actors run.
This is neither a general TCP implementation nor a network namespace service.

FPRLive and LiveView now use the owner. FPRLive retains received messages before
network RPCs: another receive within an RPC closes the prior borrow window.
Loaded-process tests also exposed an FP-RISC runtime defect: copying a foreign
image's nullary constructor left slab alignment padding uncleared. Generic
walkers treated stale bytes as a field. The copier now clears this padding,
with an explicitly poisoned-slab regression in `tests/base/images_probe.c`.

## Verification

- `tools/net-actor-check.py`: Portable one/two-hart lifecycle and competing
  startup; native virtio v1/v2 with target-matched one/two-hart images.
- `tools/net-process-check.py`: kernel-owner discovery, poll, stop permission,
  private frame refusal and process-image release, both NIC versions and hart
  counts.
- `tools/net-transport-check.py`: four concurrent peers, segmented binary echo.
- `tools/net-browser-check.py`: native LiveView HTTP/quit, POS WebSocket
  login/quit, repeated empty disconnect/slot reuse, and a withheld TX completion; heartbeat continues, owner fails,
  subsequent requests refuse the dead owner.
- `tools/net-policy-check.py`: malformed packets, checksums, fragments,
  buffering/backpressure, FIN/EOF, raw ABI, RV32/RV64 production objects and absence
  of TCP/ARP policy references in the RV64 NIC object.
- Existing FPRLive adversarial/capacity/soak/persistence suite, LiveView HTTP
  checks, and Qlog/bootstrap/loaded-process storage routing regressions.

These are local software/QEMU checks. Hardware, general TCP, network namespace
permissions, protocol budgets, physical reset/reprobe and automatic restart
remain outside this checkpoint.
