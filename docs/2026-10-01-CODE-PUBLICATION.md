# Native loaded-code instruction caches

Date: 2026-10-01. Supersedes the remote `fence.i` limitation in
2026-10-01-PROCESS-IMAGES.md.

After image copying, BSS initialization and relocation, the loader calls
`fpr_code_publish` on the kernel runtime before registration and entry.
This fences locally and publishes a generation. Every kernel scheduler hart
acquires the generation and fences its instruction stream before dispatching
an actor from the new image, including harts waking from idle. The existing
spawn/ship doorbell supplies wakeup; no blocking IPI acknowledgement is needed.

The Native QEMU image gate passes concurrent images, a child retaining an
image after root exit, and final reclamation with this publication path.
QEMU confirms integration, not noncoherent instruction-cache hardware behavior.
The instrumented Base regression independently verifies 100 remote dispatches.
The compiler lock must include the new runtime API. Physical RISC-V validation
remains outstanding; Portable publication still uses its host cache-clear path.
