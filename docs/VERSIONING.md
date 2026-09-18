# Versioning: `fpr commit`, the .fpr store, fpr.lock, and releases

## Three layers

Each layer answers one question, and each is built from the one below:

| layer   | artifact                                   | question it answers            | minted by              |
|---------|--------------------------------------------|--------------------------------|------------------------|
| module  | `.fpr/versions.db` + `.fpr/store/<hash>`   | what code is "qlog v2.0"?      | `fpr commit`           |
| tree    | `fpr.lock`                         | what does THIS tree pin?       | `./qos.py lock`        |
| release | git tag `vX.Y.Z` + `dist/qos-fpr-vX.Y.Z/`  | what did we ship, exactly?     | `./qos.py release`     |

**Module.** `fpr commit mymod.fpr` mints an immutable, hash-addressed
version (the rest of this document).  The pin hash is the compiler's
own `use "name#hash"` hash, so committing changes nothing about how
consumers spell a dependency -- it makes the spelling *resolvable
forever*: the blob is in the store, the name/version binding is in the
db, and both are tracked in git.

**Tree.** `./qos.py lock` scans every `Alias = use "spec#hash"` in the
tree's sources and writes `fpr.lock`: one line per pin with
the committed version it resolves to and the file that pins it.  A pin
whose hash has no store blob, or a blob but no `versions.db` binding
(a closure copy that was never itself committed), is UNRESOLVABLE and
the command fails naming it -- `./qos.py commit <module>` fixes it.
`./qos.py lock --check` is the read-only form (a check-all leg and the
first step of the release workflow): it fails when a pin is unbacked
or the checked-in lock is stale.

**Release.** `release.toml` at the repo root says what a release is:
the next `version`, the `apps` that get packed, the library `modules`
that get committed.  `./qos.py release [X.Y.Z] [--push]`:

1. refuses on a dirty tree or an existing tag; rewrites `version` when
   one is passed;
2. `fpr commit`s every listed module (no-op when unchanged; a refused
   commit -- unpinned use, or a signature break without `--major` --
   stops the release with the compiler's own fix printed);
3. regenerates `fpr.lock` and refuses if any pin is unbacked;
4. runs the smoke set (`--full` = check-all.sh, `--skip-tests` = none);
5. packs each app with `qos.py pack --bundle` into
   `dist/qos-fpr-vX.Y.Z/<name>/` and re-stamps its `.qa` MANIFEST with
   `version` (the app's own `#: version` directive, else the release
   version), `release`, `git` (describe) and `built`.  QAR2's
   integrity sha covers the IMAGE only, so the stamp never touches
   what the loader verifies;
6. writes `RELEASE.txt` (git rev, per-app sha256, the lock),
   `SHA256SUMS`, a copy of `fpr.lock`, and
   `dist/qos-fpr-vX.Y.Z-<os>-<arch>.tar.gz`;
7. commits `release.toml` + `fpr.lock` + `.fpr/` as "Release vX.Y.Z",
   mints the annotated tag `vX.Y.Z` with `RELEASE.txt` as its message,
   and with `--push` pushes branch and tag.

The tag landing on GitHub runs `.github/workflows/release.yml`, which
rebuilds the same bundles from the tagged tree (`qos.py release
<tag> --no-git --skip-tests`, after `lock --check`) and publishes a
GitHub Release with the tarball, `SHA256SUMS` and `fpr.lock` attached
and `RELEASE.txt` as the notes.  Nothing is uploaded by hand: the
release assets are what a checkout of the tag builds.

So a shipped `.qa` names its release, the release names its git
commit and its module versions, and each module version names its
exact source -- one chain, every link content-addressed or tagged.
Cut the first tag from `main`, not a feature branch: a tag on a
squash-merged branch would point at a commit `main` never contains.

## The model (module layer)


`mymod.fpr` is a mutable **scratch area** for the id `mymod` — not the
identity-bearing artifact. `fpr commit mymod.fpr` mints the identity:

    .fpr/store/<hash>.fpr     the exact source (content blob)
    .fpr/versions.db          append-only:  name version hash

The hash is the frontend's own pin hash — `Modules.hashAST` over the
pin-normalized tree, a Merkle root over the dependency tree — i.e. the
SAME hash the compiler already prints on every unpinned `use`. So a
committed version is addressable with syntax that already existed:

    M = use "mymod#824900fc92b96248".

Resolution order for a pinned use: the scratch file if its hash still
matches; otherwise `.fpr/store/<hash>.fpr` (with a note). The scratch
file drifting — or being deleted outright — no longer breaks pinned
consumers: the store entry is the identity, the file is a working copy.

## Semver by signature diff (checked at commit time)

* identical hash → no-op.
* prior signature ⊆ new signature (every exported name keeps its arity
  and declared sig; additions fine) → **patch** bump (v1.0 → v1.1).
* anything removed or changed → refused with the exact missing entries
  listed; `--major` mints v(N+1).0.

This subset check is the commit-time face of the LiveReload
row-compatibility question: any minor/patch version is safe to reload
into **by construction** — the check ran before the version could be
addressed by hash. Only major versions carry compatibility risk that
needs explicit runtime handling (`LiveReload` clauses).

## The pkgstore mapping

`.fpr/` is structurally pkgstore (tools' client.py/server.py), one
level down:

    .fpr/store/<hash>.fpr      =  store/<sha256>       (content blobs, dedup'd)
    .fpr/versions.db           =  index.db             (append-only bindings)
    same-version rebind error  =  the 409 invariant    ("bindings are immutable
                                                        — publish a new version")

So `fpr push` against a pkgstore is exactly: POST the blob to /upload,
POST the (name, version, hash) binding to /index — and `fpr pull` is
GET /index/{name} → GET /blob/{hash} → verify → drop into .fpr/store.
No new concepts on either side; pkgstore stays policy-free ("no auth,
no policy, no builds — policy lives on top") and the commit semantics
(signature-diff classification) stay client-side, exactly where
pkgstore's design says policy belongs. Wiring the two HTTP calls is
deliberately left as the seam — the formats already agree.

## Open question carried forward

Whether a dependent (mylib pinning mymod#h) is mechanically forced to
re-commit when its reference changes, or only when its own exported
signature changes as a consequence — old versions remain addressable
forever, so staying pinned indefinitely is at least *coherent*.
