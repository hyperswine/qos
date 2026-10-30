# QOS Portable 0.2.0: `qos build`, no global `fpr`

Date: 2026-10-30. This follows the
[0.1.0 desktop release](2026-10-29-DESKTOP-RELEASE.md) and supersedes it
wherever the two differ about commands.

QOS Portable 0.2.0 installs only the `qos` command. 0.1.0 also exported its
private compiler as a global `fpr`. That clashes with the standalone FP-RISC
toolchain, which is meant to own `fpr` and `sol`
(FP-RISC `docs/2026-10-30-INSTALLED-TOOLCHAIN-ROADMAP.md`). Nothing else
changes: the compiler, Main, the onboard apps and both hosts are byte-identical
to 0.1.0, so existing disks and installed apps keep working.

## Migration

| 0.1.0 | 0.2.0 |
|---|---|
| `fpr build --target=qos-portable` | `qos build` |

`qos build` has existed since 0.1.0 and always runs the package's private,
hash-matched compiler. Scripts that call `fpr build --target=qos-portable`
must switch. After the upgrade, `fpr` is either not found, or it is the
standalone FP-RISC compiler, which refuses that target and points at
`qos build`. The formula's caveats say so. `qos new`, `qos disk create`,
`qos install` and `qos run` are unchanged.

## What changed in the tree

- `packaging/homebrew/qos-portable.rb.in`: no `bin/fpr` wrapper. The caveats
  and the formula test use `qos build`, and the caveats carry the migration
  note. `conflicts_with "qos-fpr"` stays, because both formulas install `qos`.
- `tools/stage-portable-sdk.py` no longer links `bin/fpr`.
  `tools/package-portable-sdk.py` refuses a stage that exports it.
- `tools/portable_sdk.py`: `qos new` and the compiler-mismatch refusal now
  name `qos build`. The same change is made to the `qos.py` message for
  desktop projects.
- `tools/portable-sdk-check.py` and `tools/portable-upgrade-check.py` build
  with `qos build`. The acceptance now denies the whole folder that holds
  the checkouts, which covers sibling worktrees and the main checkouts.

## Building it

The release pins FP-RISC `94f699b`, as 0.1.0 did. Rebuilding that revision
today resolved Haskell `network-3.2.10.0`, where the 0.1.0 compiler used
3.2.7.0. That would not be the same compiler. So 0.2.0 ships the exact 0.1.0
binary (`b20b50c4…`), copied from the installed 0.1.0 package, together with
the notice inventory recorded with it. Main, the onboard apps, the driver and
both hosts were rebuilt with that binary. They came out byte-identical to
0.1.0's. A future compiler change should pin its Cabal plan, because a
rebuild from the same source revision is not reproducible today.

```sh
# fprisc worktree at 94f699b, with fpr = the 0.1.0 package's compiler/fpr
export FPRISC_ROOT=../fprisc-pin
make -C qos portable portable-gl
python3 tools/main-profile.py --output .qos/sdk-profile
make -s qos-app PROG=tests/sdkdesktop.fpr QA_OUT=/tmp/driver.qa BUILD=.qos/sdk-driver-build
python3 tools/stage-portable-sdk.py --fprisc ../fprisc-pin --profile .qos/sdk-profile --output /tmp/q2/stage
python3 tools/package-portable-sdk.py --sdk /tmp/q2/stage --compiler-licenses NOTICES \
  --version 0.2.0 --output /tmp/q2/release
```

The candidate was packaged from QOS `f4d8ec2` with clean flags in both
repositories (archive SHA-256 `2a25165a…`).

## Qualification on this Mac (macOS AArch64)

Every SDK command ran under `sandbox-exec`, with the whole checkout folder,
GHC and Cabal denied and the SDK read-only.

- **0.1.0 acceptance.** The graphical installed-SDK acceptance passed on a
  copy of the installed 0.1.0 package, now building with `qos build`.
- **Upgrade from 0.1.0 to 0.2.0.** `tools/portable-upgrade-check.py`
  prepared a counter disk with saved count 2 under 0.1.0. Verifying under
  0.2.0, the disk was byte-identical, the app was rebuilt with `qos build`
  and replaced, the runtime restored count 2, and unrelated records were
  preserved.
- **0.2.0 acceptance.** The graphical acceptance passed on 0.2.0 unpacked
  from the release tarball. Its prefix has no `bin/fpr`, and PATH held only
  `qos`, Python, Clang and lld.

`brew style` on the generated formula reports only findings already present
in the published 0.1.0 template (dependency order, the `opt_bin` helpers,
line length, and Homebrew-internal Sorbet and frozen-string notices).
See the [evidence](evidence/2026-10-30-desktop-release-0.2.0.json).

## Published and installed (2026-10-30, later)

[QOS Portable 0.2.0](https://github.com/hyperswine/qos/releases/tag/desktop-v0.2.0)
is published. The tag `desktop-v0.2.0` points at the build commit `f4d8ec2`,
and the release carries the tarball, `SHA256SUMS`, `release.json` and the
formula. The downloaded tarball matches its checksum. `Formula/qos-portable.rb`
in `hyperswine/homebrew-tap` is updated at `91922cc`.

The actual Homebrew path was then tested on this Mac:

1. The graphical installed-SDK acceptance passed against the installed 0.1.0
   Cellar prefix, and the upgrade disk was prepared (saved count 2, every
   record fingerprinted).
2. `brew update` and `brew upgrade hyperswine/tap/qos-portable` moved
   0.1.0 to 0.2.0. Homebrew also upgraded `z3`, an outdated dependency of
   `llvm`, to 5.3.3; `llvm`'s linkage was checked afterwards.
   `/opt/homebrew/bin/fpr` is gone, and `qos --version` reports 0.2.0.
3. The upgrade check against the 0.2.0 Cellar passed. The disk was
   byte-identical after the upgrade and before launch; the app was rebuilt
   with `qos build` and replaced; count 2 was restored; and unrelated
   records were preserved.
4. `brew test qos-portable` passed, and `brew linkage` reports no missing
   libraries.
5. The graphical installed-SDK acceptance passed against the 0.2.0 Cellar
   prefix, with no Python bytecode written into the package.

See the [Homebrew evidence](evidence/2026-10-30-desktop-release-0.2.0-homebrew.json).
The acceptance removes write bits from the keg while it runs; they were
restored afterwards. An older `0.1.0-rc1` keg is still in the Cellar, and
`brew cleanup` cannot remove it until its leftover unwritable files are fixed.

## Not done yet

- This branch (`portable-0.2`) is not merged into `main`; the release tag
  points at its commit `f4d8ec2`.
- Once 0.2.0 is published, the FP-RISC formula can drop its
  `conflicts_with "qos-portable"`.
