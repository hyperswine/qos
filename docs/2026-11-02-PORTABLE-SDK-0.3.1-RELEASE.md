# QOS Portable SDK 0.3.1 release

Published 2 November 2026:
[desktop-v0.3.1](https://github.com/hyperswine/qos/releases/tag/desktop-v0.3.1).
The signed Homebrew manager index offers the macOS ARM64 SDK, requiring macOS
27.2 or later, Apple Command Line Tools, libgit2, libarchive and GLFW.

```sh
brew upgrade hyperswine/tap/qosmeta
qosmeta install 0.3.1
```

Installing preserves an existing default. Select it with
`qosmeta default 0.3.1`, or use an SDK project pin. An unversioned
`qosmeta install` selects the newest stable release from the index.

The native builder now enforces the same SDK pin policy as the managers:
compatible 0.x pins stay within their minor series, stable pins exclude
prereleases, exact pins preserve the complete tag, and noncanonical versions
are rejected. The installed SDK needs no source checkout, GHC, Cabal or Python.
Clang and the indexed native-library dependencies remain required.

This is a builder patch over the qualified SDK 0.3.0 payload. It retains the
private compiler at `94f699bc868f49c1e5b5019f9228512e85415993`, matched runtime
ABI `22.137`, static ELF linker, Main profile and bundled apps. It does not swap
in the separately released FP-RISC 0.13.1 compiler (codegen ABI 143).
The QOS source snapshot is clean revision
`81b8951e4f4f20b6bdd3caa479fda58bfa3f9bf6`.

The SDK archive SHA256 is
`672b790480f296d423a58b788158cd4c5affcf81f9e49490129d8748804f1575`.
Assets include the archive, checksums and release metadata. Existing release
archives are unchanged.

The exact SDK archive passed installed acceptance with source/GHC/Cabal/make
denied and the SDK read-only: external counter and clock effects, sessions with
1 and 4 harts, graphical Main, offline install/update, persistence across app
replacement and host restart, unrelated-record preservation, and host/installer
exclusion. The driver was freshly built with the SDK's matched private compiler.
Nineteen project test groups passed, including 20 native/reference version-policy
cases compiled with that private compiler. Seven direct packaged-builder pin
cases passed, alongside the compiler's corresponding matrix.

A fresh isolated public install through Homebrew's qosmeta 0.2.0 verified the
signed index, selected 0.3.1, matched the qualified archive hash and built an
external counter. Real user stores and defaults were preserved.
[Machine-readable evidence](evidence/2026-11-02-portable-sdk-0.3.1-release.json)
records this hosted/graphical qualification. It does not claim a new Pi or
bare-metal deployment. Exact SDK pins select a release; host Clang/system SDK
and build-path reproducibility remain separate contracts.
