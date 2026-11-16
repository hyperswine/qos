# Build one Spectre actor probe: sol hal/spectre/actors/build.sol ROOT TARGET
# ROOT is a scratch directory holding `src` (FP-RISC runtime, machine/virt,
# machine/tangnano20k), `atomic.c` and the target's sources at their usual
# places; TARGET is probe, idle, uart, sd, vfs or boot. SIMPLE_RISC names the
# Simple-Risc checkout (sd, vfs, boot); EXTRA adds compiler flags.
unsafe program.
S = use "spectre-build".
B = use "sol/lib/build".
> case args Unit of
    [root, name] -> S.target (B.query ["/bin/realpath", root]) (B.setting "SIMPLE_RISC" "") name
  | _ -> error "usage: sol hal/spectre/actors/build.sol ROOT probe|idle|uart|sd|vfs|boot".
