#!/usr/bin/env python3

"""qos.py -- the pipeline layer over the whole tree.

The Makefiles stay what they are: MECHANISM (cross-compilation,
linking, packaging -- the root Makefile and qos/Makefile know how each
artifact is made).  This file is the POLICY layer the project always
gets used as anyway: one command from the repo root that knows how the
pieces compose -- compiler -> .qa -> host -> disk -> QEMU -> browser --
and where every intermediate lives, so you never cd between component
directories or thread app.qa paths by hand again.

    ./qos.py fprisc ~/src/fprisc    say where the fprisc checkout is, once
                                    (remembered in fprisc.path; $FPRISC_ROOT
                                    or --fprisc DIR override it; a sibling
                                    ../fprisc needs no saying at all)
    ./qos.py build                  bring fpr + qosp up to date
    ./qos.py new myapp --template mvu           scaffold a WORKING app in
                                    apps/myapp/ (templates: min |
                                    service | mvu | notes) -- it runs,
                                    self-checks, and packs immediately
    ./qos.py dev apps/myapp/app.fpr             the SKETCH loop: run
                                    INTERPRETED (sol profile: actors, MVU,
                                    paths, transactions), rerun on save
    ./qos.py run tests/dtree.fpr    compile + host on qosp (the default)
    ./qos.py run tests/pathnotes.fpr            a program DECLARES its own
                                    harness in `#:` header lines: plugins
                                    to build + seed onto a fresh QLOG disk
                                    (`#: plugins a.fpr b.fpr`, FPR_DISK
                                    pointed at it) and its success line
                                    (`#: expect ...` -- a run that misses
                                    it, or panics, exits nonzero).  Flags
                                    do the same ad hoc: --plugin x.fpr
                                    (repeatable, overrides the directive),
                                    --no-plugins, --disk my.img (use an
                                    existing image verbatim), --expect s
    ./qos.py pack tests/pathnotes.fpr --bundle  dist/pathnotes/: the named
                                    .qa (its dependency closure inside),
                                    the seeded disk, qosp + run.sh -- a
                                    self-contained folder to hand out
    ./qos.py run programs/interactive_desktop_gl.fpr  ... on qosp-gl
    ./qos.py run tests/fmath.fpr --on virt      ... on bare-metal QEMU
    ./qos.py run sol/examples/todo.sol          ... .sol runs the sol profile
    ./qos.py serve tests/mvuweb.fpr --port 8080 LiveView app, URL printed
    ./qos.py native                 kernel + disk + interactive QEMU boot
    ./qos.py native --apps a.qa b.qa --smoke    seeded, scripted boot check
    ./qos.py disk my.img 8 a.qa     seed a QLOG image (mkdisk)
    ./qos.py commit mods/qlog.fpr   fpr commit (the .fpr store)
    ./qos.py lock --check           every `use "x#hash"` pin has a committed
                                    version; fpr.lock is current
    ./qos.py release 0.2.0 --push   cut a release: commit the modules, lock,
                                    smoke, stamped dist bundles, tag v0.2.0
    ./qos.py test                   the fast smoke set;  --all = check-all.sh
    ./qos.py install --prefix DIR   the tree as a toolchain: DIR/bin/{fpr,qos,sol}
    ./qos.py clean

Artifacts never land in the tree.  Every run writes to the WORKSPACE:
`.qos/` under the directory you invoke from (QOS_OUT overrides) holds
the program's .qa, its build/ intermediates, and the host's qosp.disk
and qos-store/ state; packs go to `dist/` beside it.  From the repo
root that is ./.qos and ./dist; from your own project it is yours.  An
installed tree (`qos.py install`, `brew install qos-fpr`) is read-only
to every command, and its fpr and qosp are shipped, never rebuilt.

Everything delegates to make for staleness (an up-to-date tree is a
no-op), so this adds no second dependency graph -- just one honest
entry point over the existing one.
"""

import argparse
import os
import re
import shutil
import json
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parent
QOS = ROOT / "qos"
# an installed tree (`qos.py install`, the Homebrew formula) carries this
# marker: its fpr / qosp are shipped, never rebuilt, and nothing below
# ROOT is written -- every artifact goes to the workspace
INSTALLED = (ROOT / ".installed").is_file()


# ---- the fprisc checkout ------------------------------------------------------
# The compiler, runtime and language libraries live in the separate
# fprisc repository; this tree holds the QOS programs and hosts.  One
# path names that checkout, found in this order:
#     --fprisc DIR          this invocation
#     $FPRISC_ROOT          this shell
#     fprisc.path           this checkout (`./qos.py fprisc DIR` writes it)
#     ../fprisc             a sibling checkout, nothing to say
#     toolchain/            an installed tree ships its own
# Nothing is copied or linked: the path is handed to the Makefiles as
# FPRISC_ROOT (dependency.mk applies the same order when make is run
# directly) and to the compiler as FPR_PATH, its module search root.
FPRISC_FILE = ROOT / "fprisc.path"
FPRISC_LOCK = ROOT / "fprisc.lock.json"
FPRISC_MARKS = ("Makefile", "compiler/Main.hs", "runtime/runtime.c", "core/prelude.fpr")


def is_fprisc(path):
    return all((path / n).is_file() for n in FPRISC_MARKS)


def fprisc_root(given=None, root=ROOT):
    """(the checkout, how it was found), or SystemExit with the ways to say."""
    if (root / ".installed").is_file():
        return root / "toolchain", "the installed toolchain"
    remembered = (root / FPRISC_FILE.name).read_text().strip() if (root / FPRISC_FILE.name).is_file() else None
    for value, how in ((given, "--fprisc"), (os.environ.get("FPRISC_ROOT"), "$FPRISC_ROOT"),
                       (remembered, FPRISC_FILE.name), (str(root.parent / "fprisc"), "the sibling checkout ../fprisc")):
        if not value:
            continue
        path = Path(value).expanduser().resolve()
        if is_fprisc(path):
            return path, how
        if not how.startswith("the sibling"):
            raise SystemExit(f"qos: {how} names {path}, which is not an fprisc checkout (no compiler/Main.hs)")
    raise SystemExit("qos: no fprisc checkout found -- say where it is once: ./qos.py fprisc /path/to/fprisc "
                     "(or export FPRISC_ROOT, or clone fprisc beside this repository)")


_pre = argparse.ArgumentParser(add_help=False)
_pre.add_argument("--fprisc")
_given = _pre.parse_known_args()[0].fprisc
if sys.argv[1:2] == ["fprisc"]:
    TOOLCHAIN, TOOLCHAIN_HOW = None, None  # the command that sets the path must run without one
else:
    TOOLCHAIN, TOOLCHAIN_HOW = fprisc_root(_given)
COMPILER = TOOLCHAIN / "fpr" if TOOLCHAIN else None
if TOOLCHAIN:
    os.environ["FPRISC_ROOT"] = str(TOOLCHAIN)
    os.environ["FPR_HOME"] = str(ROOT)
    os.environ["FPR_PATH"] = str(TOOLCHAIN)
    os.environ["FPR_FOREIGN"] = str(ROOT / "core" / "foreign.fpr")  # the primitives QOS implements, declared by QOS


class Workspace:
    """Where one invocation's artifacts go.  The TREE (ROOT) holds the
    toolchain -- fpr, qosp, std, hal -- and is read-only to a run; the
    WORKSPACE is the project you invoke qos from: `.qos/` under the
    current directory (QOS_OUT overrides) for the per-program .qa, the
    intermediates under build/, the host's qosp.disk and qos-store/
    state, and `dist/` beside it for packs.  In a checkout, run from
    the repo root, that is ROOT/.qos and ROOT/dist; installed, it is
    your project's own directory -- the same code path either way."""

    def __init__(self):
        self.project = Path.cwd()
        env = os.environ.get("QOS_OUT")
        self.out = Path(env).resolve() if env else self.project / ".qos"
        self.build = self.out / "build"
        self.dist = self.project / "dist"

    def qa(self, prog):
        return self.out / f"{Path(prog).stem}.qa"

    def image(self, prog):
        return self.out / f"{Path(prog).stem}.elf"

    def path(self, name):
        return self.out / name

    def mk(self):
        self.build.mkdir(parents=True, exist_ok=True)
        return self

    def make_vars(self):
        """the Makefile knobs that move every per-program output here"""
        return [f"BUILD={self.build}"]


WS = Workspace()


def rel(p):
    """a path as the user would type it from where they are"""
    try:
        return os.path.relpath(p, Path.cwd())
    except ValueError:
        return str(p)


def say(msg):
    print(f"\033[36m[qos]\033[0m {msg}", flush=True)


def die(msg, code=1) -> NoReturn:
    print(f"\033[31m[qos]\033[0m {msg}", file=sys.stderr)
    sys.exit(code)


def sh(cmd, cwd=ROOT, env=None, quiet=False, check=True):
    e = dict(os.environ)
    if env:
        e.update({k: str(v) for k, v in env.items()})
    r = subprocess.run(
        cmd, cwd=cwd, env=e,
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.STDOUT if quiet else None)
    if check and r.returncode != 0:
        die(f"failed ({r.returncode}): {' '.join(map(str, cmd))}", r.returncode)
    return r.returncode


PANICS = ("*** FPRISC PANIC", "*** SOL PANIC")


def run_scan(cmd, cwd, env=None, expect=None):
    """Stream a child's output live; if expect is set, also scan for it
    and report the verdict in the exit code.  A panic line in the output
    fails the run even when the host process exits 0 (a hosted image's
    panic is qosp's output, not its exit code)."""
    e = dict(os.environ)
    if env:
        e.update({k: str(v) for k, v in env.items()})
    p = subprocess.Popen(cmd, cwd=cwd, env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    hit = expect is None
    panic = None
    try:
        for raw in p.stdout: # type: ignore
            line = raw.decode("utf-8", "replace")
            sys.stdout.write(line)
            sys.stdout.flush()
            if expect and expect in line:
                hit = True
            if panic is None and any(m in line for m in PANICS):
                panic = line.strip()
        p.wait()
    except KeyboardInterrupt:
        p.terminate()
        p.wait()
    if panic:
        die(f"run panicked: {panic}")
    if expect:
        if hit:
            say(f"expect: found {expect!r}")
        else:
            die(f"expect: {expect!r} never appeared")
    return p.returncode


# ---- resolution -------------------------------------------------------------

def resolve_prog(prog):
    """A program path as typed from anywhere -> the root-relative path
    the Makefile wants (a program of the fprisc checkout resolves too)."""
    p = Path(prog)
    for cand in (Path.cwd() / p, ROOT / p, TOOLCHAIN / p):
        if cand.is_file():
            return os.path.relpath(cand.resolve(), ROOT)
    die(f"no such program: {prog} (looked in ., the repo root, and the fprisc checkout {TOOLCHAIN})")


def prog_directives(path):
    """`#: key val val...` lines in a program's header comment -- the
    program declares its own harness (today: plugins) instead of every
    caller hand-rolling make plugin-qa + mkdisk + FPR_DISK.  Scanned in
    the first 60 lines; repeated keys extend."""
    d = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= 60:
                    break
                line = line.strip()
                if line.startswith("#:"):
                    parts = line[2:].split()
                    if parts:
                        d.setdefault(parts[0], []).extend(parts[1:])
    except OSError:
        pass
    return d


# ---- the stages -------------------------------------------------------------

def build_fpr():
    if INSTALLED:
        if not COMPILER.is_file():
            die(f"installed tree at {ROOT} has no fpr: reinstall (qos.py install / brew reinstall qos-fpr)")
        return
    say("fpr (compiler; no-op when fresh)")
    sh(["make", "-s", "fpr"], cwd=ROOT, quiet=True)


def build_qosp(gfx=False):
    target = "portable-gl" if gfx else "portable"
    host = "qosp-gl" if gfx else "qosp"
    if INSTALLED:
        if not (QOS / host).is_file():
            die(f"installed tree at {ROOT} has no {host}" + (" (built only where GLFW was found at install)" if gfx else "") + ": reinstall")
        return
    say(f"{host} (portable host; no-op when fresh)")
    sh(["make", "-s", target], cwd=QOS, quiet=True)


def build_native():
    say(f"{rel(WS.path('qos-native.elf'))} + disk.img")
    WS.mk()
    disk = WS.path("disk.img")
    sh(["make", "-s", "native", str(disk), f"KERNEL={WS.path('qos-native.elf')}", f"DISK={disk}"]
       + WS.make_vars(), cwd=QOS, quiet=True)


def build_app(prog, harts=None):
    qa = WS.mk().qa(prog)
    say(f"qos-app {prog} -> {rel(qa)}")
    target = "qos-app"  # qos-app.mk picks the image this host's qosp runs
    cmd = ["make", "-s", target, f"PROG={prog}", f"QA_OUT={qa}"] + WS.make_vars()
    if harts:
        cmd.append(f"HARTS={harts}")
    sh(cmd, cwd=ROOT, quiet=True)
    return qa


def build_plugins(prog, plugins, size_mb=8):
    """Build each .fpr as a plugin .qa (sub-slot = list order), seed a
    fresh QLOG image named after the program, return its path.  Mirrors
    the livereload harness: plugsyms after the shell build, then one
    plugin-qa per module, then mkdisk."""
    sh(["make", "-s", "plugsyms"] + WS.make_vars(), cwd=ROOT, quiet=True)
    qas = []
    for slot, p in enumerate(plugins):
        r = resolve_prog(p)
        out = WS.build / f"{Path(r).stem}.qa"
        say(f"plugin-qa {r} (sub-slot {slot})")
        sh(["make", "-s", "plugin-qa",
            f"PROG={r}", f"PLUGSLOT={slot}", f"PLUG_OUT={out}", f"QA_OUT={WS.qa(prog)}"] + WS.make_vars(),
           cwd=ROOT, quiet=True)
        qas.append(str(out))
    img = WS.build / f"plugdisk-{Path(prog).stem}.img"
    say(f"disk: {rel(img)} <- {' '.join(Path(q).name for q in qas)}")
    sh([sys.executable, str(ROOT / "tools" / "mkdisk.py"), str(img), str(size_mb)] + qas,
       cwd=WS.build, quiet=True)
    return img


def asset_env(prog):
    """`#: music <file>` (relative to the program): the host resolves music
    beside the .qa or under FPR_ASSETS -- for `run`, point FPR_ASSETS at
    the file's directory; `pack` copies the file into the bundle instead."""
    files = prog_directives(ROOT / prog).get("music", [])
    if not files:
        return {}
    return {"FPR_ASSETS": str((ROOT / prog).parent.joinpath(files[0]).resolve().parent)}


def wants_gl(prog):
    """`#: host gl` (or the _desktop_gl name) = the program draws through
    the GLES scene walker: run and pack it on qosp-gl."""
    return Path(prog).stem.endswith("_desktop_gl") or "gl" in prog_directives(ROOT / prog).get("host", [])


def declared_plugins(a, prog):
    """The program's plugin harness: --plugin flags win, then the
    program's own `#: plugins` line; --no-plugins silences both."""
    if getattr(a, "no_plugins", False):
        return []
    return getattr(a, "plugin", None) or prog_directives(ROOT / prog).get("plugins", [])


# ---- commands ---------------------------------------------------------------

def cmd_build(a):
    t0 = time.time()
    build_fpr()
    if a.what in ("all", "host"):
        build_qosp()
    if a.what in ("all", "native"):
        build_native()
    say(f"build done in {time.time() - t0:.1f}s")


def cmd_run(a):
    t0 = time.time()
    prog = resolve_prog(a.prog)
    build_fpr()

    # the program's declared harness (overridable per flag): plugins to
    # seed, and its own success line (`#: expect ...`) -- a run that
    # misses it fails, so every program is its own smoke test
    plugins = declared_plugins(a, prog)
    d = prog_directives(ROOT / prog)
    expect = a.expect or (" ".join(d["expect"]) if "expect" in d else None)
    if plugins and a.on in ("virt", "sol"):
        die(f"--on {a.on}: plugin modules ride FPR_DISK, which is the qosp host's; run on qosp (or seed `./qos.py native --apps` yourself)")
    if plugins and a.disk:
        die("--disk and plugins together: an explicit image is used verbatim (pass --no-plugins, or drop --disk to seed one)")

    if prog.endswith(".sol") or a.on == "sol": # type: ignore
        # a script runs where YOU are: its paths, its files, its cwd
        say(f"sol profile: {prog}")
        return run_scan([str(COMPILER), "sol", str((ROOT / prog).resolve())], cwd=Path.cwd(), expect=expect)
    if a.on == "virt":
        say(f"bare-metal QEMU virt: {prog}")
        cmd = ["make", "-s", "bare-metal-run", f"PROG={prog}", f"IMAGE={WS.mk().image(prog)}"] + WS.make_vars()
        if a.harts:
            cmd.append(f"HARTS={a.harts}")
        return run_scan(cmd, cwd=ROOT, expect=expect)

    # the default: host the .qa on qosp
    gfx = a.gfx or wants_gl(prog)
    host = "qosp-gl" if gfx else "qosp"
    qa = build_app(prog, a.harts)
    build_qosp(gfx=gfx)
    env = asset_env(prog)
    if a.port:
        env["FPR_PORT"] = a.port
    if a.harts:
        env["FPR_HARTS"] = a.harts
    if plugins:
        env["FPR_DISK"] = str(build_plugins(prog, plugins))
    elif a.disk:
        env["FPR_DISK"] = str(Path(a.disk).resolve())
        say(f"disk: {a.disk} (as given)")
    if a.fresh_disk:
        WS.path("qosp.disk").unlink(missing_ok=True)
        say("qosp.disk: fresh")
    # `#: fprd` (or --fprd): the program compiles/packages at runtime
    # through Sys.compile, so start the host compiler daemon for the run
    fprd_proc = None
    if a.fprd or "fprd" in d:
        sock = str(WS.build / f"fprd-{os.getpid()}.sock")
        say(f"fprd: compiler daemon on {rel(sock)}")
        fprd_proc = subprocess.Popen(
            [sys.executable, "tools/fprd.py", sock], cwd=ROOT, env={**os.environ, "FPRD_BUILD": str(WS.build)},
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        env["FPRD_SOCK"] = sock
        time.sleep(0.8)
    say(f"{host}: {prog}" + (f"  (port {a.port})" if a.port else ""))
    # the host runs IN the workspace: qosp.disk and qos-store/ (the
    # app's durable state) are the project's, not the toolchain's
    try:
        rc = run_scan([str(QOS / host), "--yes", str(qa)], cwd=WS.out, env=env, expect=expect)
    finally:
        if fprd_proc:
            fprd_proc.terminate()
    say(f"total {time.time() - t0:.1f}s")

    return rc


def cmd_pack(a):
    """One program -> one shippable folder.  dist/<name>/ holds the
    named .qa (the container: its whole dependency closure is inside),
    the seeded QLOG disk when the program declares plugins, and with
    --bundle the qosp host binary + a run.sh -- a folder you can hand
    to someone."""
    t0 = time.time()
    prog = resolve_prog(a.prog)
    d = prog_directives(ROOT / prog)
    name = a.name or (d.get("name") or [Path(prog).stem])[0]
    size_mb = int((d.get("disk-mb") or ["8"])[0])
    build_fpr()
    gfx = a.gfx or wants_gl(prog)
    host = "qosp-gl" if gfx else "qosp"
    built = build_app(prog, a.harts)
    build_qosp(gfx=gfx)
    out = Path(a.out).resolve() if a.out else WS.dist / name
    out.mkdir(parents=True, exist_ok=True)
    qa = out / f"{name}.qa"
    shutil.copy2(built, qa)
    pieces = [f"{qa.name} ({qa.stat().st_size // 1024}KB)"]
    for f in d.get("music", []):
        src = (ROOT / prog).parent / f
        shutil.copy2(src, out / src.name)
        pieces.append(f"{src.name} ({src.stat().st_size // 1024}KB, music)")
    disk = None
    plugins = declared_plugins(a, prog)
    if plugins:
        img = build_plugins(prog, plugins, size_mb)
        disk = out / f"{name}.disk"
        shutil.copy2(img, disk)
        pieces.append(f"{disk.name} ({disk.stat().st_size // 1024}KB, {len(plugins)} plugin(s))")
    if a.bundle:
        shutil.copy2(QOS / host, out / host)
        runner = out / "run.sh"
        lines = ["#!/bin/sh",
                 f"# {name} -- packed by qos.py ({time.strftime('%Y-%m-%d')}); self-contained",
                 'cd "$(dirname "$0")"']
        if disk is not None:
            lines.append(f'export FPR_DISK="${{FPR_DISK:-{disk.name}}}"')
        lines.append(f'exec ./{host} --yes {name}.qa "$@"')
        runner.write_text("\n".join(lines) + "\n")
        runner.chmod(runner.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        pieces.append(f"{host} + run.sh")
    rel = os.path.relpath(out, Path.cwd())
    say(f"packed {rel}/: " + ", ".join(pieces))
    if a.bundle:
        say(f"run it anywhere: {rel}/run.sh")
    elif disk is not None:
        say(f"run it: (cd {rel} && FPR_DISK={disk.name} {QOS / host} --yes {name}.qa)")
    else:
        say(f"run it: {QOS / host} --yes {rel}/{name}.qa")
    say(f"pack done in {time.time() - t0:.1f}s")


def watch_set(prog_abs):
    """The file + its transitive `use` targets, textually scanned --
    what a save should rerun.  Extension resolution mirrors the
    compiler: the importer's own extension first, the sibling second."""
    seen, out = set(), []

    def visit(p):
        try:
            p = p.resolve()
        except OSError:
            return
        if p in seen or not p.is_file():
            return
        seen.add(p)
        out.append(p)
        try:
            src = p.read_text(errors="replace")
        except OSError:
            return
        exts = [p.suffix, ".sol" if p.suffix == ".fpr" else ".fpr"]
        for spec in re.findall(r'use\s+"([^"#]+)', src):
            names = [Path(spec)] if Path(spec).suffix in (".sol", ".fpr") else [Path(spec).with_suffix(e) for e in exts]
            # Follow importer-local modules first, then QOS and language roots.
            local = [p.parent / name for name in names]
            fallback = [root / name for name in names for root in (ROOT, TOOLCHAIN)]
            for c in local + fallback:
                if c.is_file():
                    visit(c)
                    break

    visit(Path(prog_abs))
    return out


def cmd_dev(a):
    """The sketch loop: run the program on the SOL profile (interpreted
    bytecode -- actors, MVU, paths, transactions all live), then rerun
    on every save of the file or anything it uses."""
    prog = resolve_prog(a.prog)
    build_fpr()
    e = dict(os.environ)
    say(f"dev {prog}: sol profile, rerun on save")

    def mt(f):
        try:
            return f.stat().st_mtime_ns
        except OSError:
            return 0

    while True:
        t0 = time.time()
        try:
            r = subprocess.run([str(COMPILER), "sol", str((ROOT / prog).resolve())], cwd=Path.cwd(), env=e).returncode
            say(f"dev: exit {r} in {time.time() - t0:.1f}s")
        except KeyboardInterrupt:
            print()
            say("dev: app interrupted")
        files = watch_set(ROOT / prog)
        say(f"dev: watching {len(files)} file(s) -- save to rerun, Ctrl-C to leave")
        try:
            base = {f: mt(f) for f in files}
            changed = None
            while changed is None:
                time.sleep(0.3)
                changed = next((f for f in files if mt(f) != base[f]), None)
            say(f"dev: changed {os.path.relpath(changed, ROOT)}")
        except KeyboardInterrupt:
            print()
            say("dev: bye")
            return 0


def cmd_serve(a):
    prog = resolve_prog(a.prog)
    build_fpr()
    qa = build_app(prog)
    build_qosp()
    say(f"serving {prog} at http://127.0.0.1:{a.port}/  (Ctrl-C stops)")

    return run_scan([str(QOS / "qosp"), "--yes", str(qa)], cwd=WS.out, env={"FPR_PORT": a.port})


# ---- scaffolding templates (qos.py new) -------------------------------------
# Every template is a WORKING app: it compiles, runs, and carries its
# own `#:` harness + expect line, so run/test/pack work immediately.
# Tokens: __NAME__ = project name, __STD__ = library module search namespace.

TPL_MIN = {"app.fpr": '''\
# __NAME__ -- a minimal QOS app: pure compute through std, one result line.
#   ./qos.py run apps/__NAME__/app.fpr
#: name __NAME__
#: expect __NAME__: ok fold=55

STD = use "__STD__/std".
Std = STD.Std.

main =
  s = Std.fold 1 10 (fn i acc -> acc + i) 0;
  "__NAME__: ok fold={s}".
'''}

TPL_SERVICE = {"app.fpr": '''\
# __NAME__ -- the smallest two-actor app: a SERVICE actor owning its
# accumulator in its loop args, a client asking through the rpc shape
# (send + selective receiveFrom).  Grow it by adding message arms.
#   ./qos.py run apps/__NAME__/app.fpr
#: name __NAME__
#: expect __NAME__: replies 5 15 36

worker : unsafe Int -> a .
worker me = wloop me 0.
wloop : unsafe Int -> Int -> a .
wloop me acc =
  m = receive me;
  (from, v) = m;
  _ = send from (acc + v);
  wloop me (acc + v).

# (named askW: the prelude already exports an `ask`)
askW me w v =
  _ = send w (me, v);
  receiveFrom me w.

main =
  me = myself 0;
  w = spawn worker;
  a = askW me w 5;
  b = askW me w 10;
  c = askW me w 21;
  _ = kill w;
  "__NAME__: replies {a} {b} {c}".
'''}

TPL_MVU = {"app.fpr": '''\
# __NAME__ -- an MVU app on std.mvu with a DECLARED Model, so @Model is
# a live schema: any actor (a debug shell, a supervisor, your tests)
# can send ("set", "cap 20") / ("dump", "") to the message port while
# it runs -- value-space iteration from day one (docs/PATHS.md).
#   ./qos.py run apps/__NAME__/app.fpr
#: name __NAME__
#: expect __NAME__: done count=12 note=hi

MV = use "__STD__/mvu".
L = use "__STD__/lens".

MApp = MV.MApp.  MQuit = MV.MQuit.  EMsg = MV.EMsg.
ETick = MV.ETick.  STick = MV.STick.  SPort = MV.SPort.

Model = {count : Int, cap : Int, note : String, port : Int}.

appInit env = {count = 0, cap = 12, note = "hi", port = env}.

appUpdate me env ev m = case ev of
    ETick -> tickUp m
  | EMsg tag arg -> onMsg m tag arg
  | e -> (m, Nil).

tickUp m =
  m2 = {m | count = m.count + 1};
  case m2.count >= m2.cap of
    True -> (m2, MQuit :: Nil)
  | False -> (m2, Nil).

# the wire: sets are transactional (bad path -> printed, ignored),
# dump walks the schema -- no per-app inspector code
onMsg m tag arg = case L.strEq tag "set" of
    True -> onSet m arg
  | False -> case L.strEq tag "dump" of
      True -> u = print "-- __NAME__ --\\n{L.dump (@Model) m ""}--"; (m, Nil)
    | False -> (m, Nil).
onSet m pv = case L.setWords (@Model) pv m of
    Ok m2 -> (m2, Nil)
  | Err e -> u = print "__NAME__: {e}"; (m, Nil).

appSubs m = STick 1 :: SPort m.port :: Nil.
appSkey m = 0.
appView vp m = "__NAME__" :: Nil.
appVals self env vp m = "count={m.count}" :: Nil.
appDone m = "__NAME__: done count={m.count} note={m.note}".

main =
  me = myself 0;
  clint = device "clint";
  mt = reg32 clint 49144;
  render = spawn MV.textRender;
  port = spawn MV.port;
  cfg = { env = port, mt = mt, tick = 3000, input = 0, render = render };
  app = MApp appInit appUpdate appSkey appView appVals appDone appSubs;
  r = MV.run me cfg app;
  _ = kill port;
  r.
'''}

TPL_NOTES = {
    "app.fpr": '''\
# __NAME__ -- the notes-app shape (tests/pathnotes.fpr, distilled):
# MVU + message port + first-class paths + the LOADER SERVICE.  The
# commit function lives behind std.loader (over std.fs -- the app
# touches no device); a ("swap", "edit2") message hot-swaps it mid-run
# through the gates, and the loader records the live set as sys/live.
# The driver actor below scripts a demo run -- replace it with your
# real input.
#   ./qos.py run apps/__NAME__/app.fpr
#: name __NAME__
#: plugins apps/__NAME__/edit1.fpr apps/__NAME__/edit2.fpr
#: expect __NAME__: done notes=one|Two n=2 ver=caps.v2

FS = use "__STD__/fs".
LD = use "__STD__/loader".
MV = use "__STD__/mvu".
L = use "__STD__/lens".

MApp = MV.MApp.  MQuit = MV.MQuit.  EMsg = MV.EMsg.  SPort = MV.SPort.

Model = {notes : List String, count : Int, ver : String, port : Int}.

revL : unsafe List a -> List a -> List a .
revL acc l = case l of Nil -> acc | x :: r -> revL (x :: acc) r.
joinBar : unsafe List String -> String -> String .
joinBar l acc = case l of
    Nil -> acc
  | s :: r -> joinBar r (joinOne acc s).
joinOne acc s = case strlen acc == 0 of True -> s | False -> "{acc}|{s}".

appInit env =
  (ld, port) = env;
  nm = LD.bind "editName";
  {notes = Nil, count = 0, ver = nm "", port = port}.

appUpdate me env ev m = case ev of
    EMsg tag arg -> onMsg me env m tag arg
  | e -> (m, Nil).

onMsg me env m tag arg = case L.strEq tag "note" of
    True -> onNote m arg
  | False -> case L.strEq tag "swap" of
      True -> onSwap me env m arg
    | False -> case L.strEq tag "quit" of
        True -> (m, MQuit :: Nil)
      | False -> (m, Nil).

# resolved at the step, never stored in the model (a stored closure
# would pin its version across a swap)
onNote m line =
  f = LD.bind "editLine";
  ({m | notes = f line :: m.notes, count = m.count + 1}, Nil).

# a swap is ONE message to the Loader service, which gates it (shell
# stamp + arity chain) and records the new live set as sys/live
onSwap : Int -> _ -> _ -> String -> _ .
onSwap me env m id =
  (ld, port) = env;
  r = LD.load me ld id;
  case r of
    Ok u -> swapOk m
  | Err e -> (m, Nil).
swapOk m =
  nm = LD.bind "editName";
  ({m | ver = nm ""}, Nil).

appSubs m = SPort m.port :: Nil.
appSkey m = 0.
appView vp m = "__NAME__" :: Nil.
appVals self env vp m = "n={m.count}" :: Nil.
appDone : unsafe _ -> String .
appDone m =
  "__NAME__: done notes={joinBar (revL Nil m.notes) ""} n={m.count} ver={m.ver}".

# ---- the scripted demo driver: replace with real input --------------

driver : Int -> Int -> String .
driver port me =
  _ = send port ("note", "one");         # v1: verbatim
  _ = send port ("swap", "edit2");       # hot swap at a step boundary
  _ = send port ("note", "two");         # -> "Two"
  _ = send port ("quit", "");
  "driver done".

main =
  me = myself 0;
  fs = FS.serve (device "blk");
  ld = LD.serve fs;
  r0 = LD.load me ld "edit1";
  _ = case r0 of Ok u -> 0 | Err e -> error "__NAME__ load edit1: {e}";
  clint = device "clint";
  mt = reg32 clint 49144;
  render = spawn MV.textRender;
  port = spawn MV.port;
  _ = spawn (driver port);
  cfg = { env = (ld, port), mt = mt, tick = 3000, input = 0, render = render };
  app = MApp appInit appUpdate appSkey appView appVals appDone appSubs;
  r = MV.run me cfg app;
  _ = kill port;
  r.
''',
    "edit1.fpr": '''\
# edit1 -- the commit function, v1: verbatim.  The swap surface is one
# monomorphic function; keep the exports and arities stable and any
# later version hot-swaps through the compat gate.
editLine s = s.
editName u = "plain.v1".
''',
    "edit2.fpr": '''\
# edit2 -- SIGNATURE-COMPATIBLE successor: capitalizes the first letter.
editLine s = case strlen s == 0 of
    True -> s
  | False -> "{upA (charAt s 1)}{substr s 2 (strlen s - 1)}".
upA c = case c >= 97 of
    True -> upB c
  | False -> chr c.
upB c = case c <= 122 of
    True -> chr (c - 32)
  | False -> chr c.
editName u = "caps.v2".
''',
}

TEMPLATES = {"min": TPL_MIN, "service": TPL_SERVICE, "mvu": TPL_MVU, "notes": TPL_NOTES}


def cmd_new(a):
    tpl = TEMPLATES[a.template]
    name = a.name
    if not name.replace("_", "").isalnum() or not name[0].islower():
        die(f"name {name!r}: lowercase start, alphanumeric/underscore only (it becomes fn-safe identifiers)")
    # Apps in either location import libraries through the module search path.
    in_tree = not INSTALLED and Path.cwd().resolve().is_relative_to(ROOT)
    dest = ROOT / "apps" / name if in_tree else Path.cwd() / name
    std = "std"
    if dest.exists():
        die(f"{rel(dest)} already exists")
    dest.mkdir(parents=True)
    for fn, body in tpl.items():
        (dest / fn).write_text(body.replace("__NAME__", name).replace("__STD__", std))
    r = rel(dest)
    me = "./qos.py" if in_tree else "qos"
    say(f"new {a.template} app: {r}/ ({', '.join(tpl)})")
    say(f"run it:   {me} run {r}/app.fpr   (its `#: expect` line IS the check)")
    say(f"ship it:  {me} pack {r}/app.fpr --bundle")


def cmd_native(a):
    build_fpr()
    build_native()
    disk = WS.path("disk.img")
    if a.apps:
        disk = WS.path("disk-seeded.img")
        say(f"seeding {disk.name} with {len(a.apps)} app(s)")
        sh([sys.executable, str(ROOT / "tools" / "mkdisk.py"), str(disk),
            "8"] + [str(Path(p).resolve()) for p in a.apps], cwd=WS.out)
    qemu = ["qemu-system-riscv64", "-accel", "tcg,thread=multi",
            "-machine", "virt", "-smp", str(a.smp), "-m", a.mem,
            "-nographic", "-bios", "none", "-kernel", str(WS.path("qos-native.elf")),
            "-drive", f"file={disk},if=none,format=raw,id=hd0",
            "-device", "virtio-blk-device,drive=hd0"]
    if a.smoke:
        say("smoke boot (scripted, ~10s)")

        p = subprocess.Popen(qemu, cwd=WS.out, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL)

        p.stdin.write(b"yyyy") # type: ignore
        p.stdin.flush() # type: ignore
        t0, buf = time.time(), b""
        ok = False
        while time.time() - t0 < 20:
            b = p.stdout.read1(4096) # type: ignore
            if not b:
                break
            buf += b
            if b"app launcher" in buf:
                ok = True
                break
        p.kill()
        if not ok:
            die("smoke boot: launcher never appeared")
        say(f"launcher up at +{time.time() - t0:.2f}s")
        return 0

    say(f"booting QOS Native ({a.smp} harts, {a.mem}, {disk.name}) -- " "q quits the launcher; C-a x kills QEMU")
    return subprocess.call(qemu, cwd=WS.out)

def cmd_disk(a):
    build_fpr()  # apps may have just been rebuilt; mkdisk itself is pure
    say(f"mkdisk {a.img} ({a.size_mb}MB, {len(a.apps)} app(s))")
    sh([sys.executable, str(ROOT / "tools" / "mkdisk.py"), a.img, str(a.size_mb)] + a.apps, cwd=Path.cwd())

# ---- fprisc: the one path, and its pin for releases ---------------------------

def fprisc_git(*args):
    return subprocess.check_output(["git", "-C", str(TOOLCHAIN), *args], text=True).strip()


def fprisc_pin():
    return json.loads(FPRISC_LOCK.read_text())["revision"] if FPRISC_LOCK.is_file() else None


def fprisc_release_check():
    """A release names the exact compiler it was cut with: the checkout
    must be clean and at the pinned commit (fprisc.lock.json)."""
    try:
        if fprisc_git("status", "--porcelain", "--untracked-files=normal"):
            die("fprisc has uncommitted changes; commit them, then ./qos.py fprisc --pin")
        if fprisc_git("rev-parse", "HEAD") != fprisc_pin():
            die("fprisc is not at the commit fprisc.lock.json pins; ./qos.py fprisc --pin and commit the lock")
    except (OSError, subprocess.CalledProcessError) as exc:
        die(f"fprisc: {exc}")


def cmd_fprisc(a):
    global TOOLCHAIN, TOOLCHAIN_HOW
    if a.path:
        path = Path(a.path).expanduser().resolve()
        if not is_fprisc(path):
            die(f"{path} is not an fprisc checkout (expected {', '.join(FPRISC_MARKS)})")
        if INSTALLED:
            die("an installed tree uses the toolchain it shipped")
        FPRISC_FILE.write_text(str(path) + "\n")
        say(f"fprisc: {path} (remembered in {FPRISC_FILE.name}; $FPRISC_ROOT and --fprisc still win)")
        return 0
    if TOOLCHAIN is None:
        TOOLCHAIN, TOOLCHAIN_HOW = fprisc_root(_given)
    if a.print:
        print(TOOLCHAIN)
        return 0
    if a.pin:
        try:
            if fprisc_git("status", "--porcelain", "--untracked-files=normal"):
                die("commit the fprisc changes before pinning")
            rev = fprisc_git("rev-parse", "HEAD")
        except (OSError, subprocess.CalledProcessError) as exc:
            die(f"fprisc: {exc}")
        FPRISC_LOCK.write_text(json.dumps({"repository": "fprisc", "revision": rev, "layout": 1}, indent=2) + "\n")
        say(f"fprisc.lock.json: {rev[:12]} (commit it with the release)")
        return 0
    say(f"fprisc: {TOOLCHAIN} (from {TOOLCHAIN_HOW})")
    try:
        head = fprisc_git("rev-parse", "HEAD")
        pin = fprisc_pin()
        say(f"fprisc: at {head[:12]}" + ("" if pin is None else f", releases pin {pin[:12]}" + (" (same)" if pin == head else " (differs; --pin to move it)")))
    except (OSError, subprocess.CalledProcessError):
        pass
    return 0


def cmd_commit(a):
    build_fpr()
    mod = resolve_prog(a.mod)
    return sh([str(COMPILER), "commit"] + (["--major"] if a.major else []) + [mod], cwd=ROOT, check=False)

# ---- versions: pins, the lock, releases -------------------------------------
# Three layers, each answering one question (docs/VERSIONING.md):
#   module   `fpr commit`  -> .fpr/versions.db + .fpr/store   what code is "qlog v2.0"?
#   tree     fpr.lock      -> every `use "x#hash"` pin, named   what does THIS tree pin?
#   release  release.toml  -> git tag vX.Y.Z + dist bundles     what did we ship?

RELEASE_TOML = ROOT / "release.toml"
LOCK_PATH = ROOT / "fpr.lock"
PIN_RE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*use\s+"([^"#]+)#([0-9a-f]{16})"', re.M)


def read_release():
    """release.toml: version + the app and module sets a release is made of."""
    import tomllib
    if not RELEASE_TOML.is_file():
        die("release.toml missing (version, apps, modules)")
    with open(RELEASE_TOML, "rb") as f:
        r = tomllib.load(f)
    for k in ("version", "apps", "modules"):
        if k not in r:
            die(f"release.toml: no `{k}`")
    return r


def set_release_version(v):
    src = RELEASE_TOML.read_text()
    new, n = re.subn(r'^version\s*=\s*"[^"]*"', f'version = "{v}"', src, count=1, flags=re.M)
    if n != 1:
        die("release.toml: no `version = \"...\"` line to update")
    RELEASE_TOML.write_text(new)


def git(*args, check=True):
    r = subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode != 0:
        die(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def git_describe():
    return git("describe", "--tags", "--always", "--dirty", check=False) or "unknown"


def versions_db():
    """.fpr/versions.db -> {hash: (name, version)} (last binding wins)."""
    db = {}
    p = ROOT / ".fpr" / "versions.db"
    if p.is_file():
        for line in p.read_text().splitlines():
            w = line.split()
            if len(w) >= 3:
                db[w[2]] = (w[0], w[1])
    return db


def tree_pins():
    """Every `Alias = use "spec#hash"` in this tree's sources (programs,
    apps, std, tests: not the store blobs, not a workspace or build
    directory, not a shipped toolchain), as (spec, hash, importer)."""
    pins = []
    for p in sorted(ROOT.rglob("*.fpr")):
        rel = p.relative_to(ROOT)
        if rel.parts[0].startswith(".") or rel.parts[0] in ("build", "dist", "toolchain", "qos", "hal", "loader", "docs"):
            continue
        try:
            src = p.read_text(errors="replace")
        except OSError:
            continue
        for m in PIN_RE.finditer(src):
            pins.append((m.group(2), m.group(3), str(rel)))
    return pins


def render_lock():
    """The lock text + the list of pins that are NOT resolvable from the
    store under a committed version.  A pin is honest when its hash has
    a blob in .fpr/store AND a name/version binding in versions.db."""
    db = versions_db()
    store = ROOT / ".fpr" / "store"
    rows, bad = [], []
    for spec, h, by in tree_pins():
        blob = (store / f"{h}.fpr").is_file()
        name, ver = db.get(h, (Path(spec).name, "-"))
        if not blob or h not in db:
            why = "no store blob" if not blob else "blob present but never `fpr commit`ed (no version binding)"
            bad.append((spec, h, by, why))
        rows.append((spec, ver, h, by))
    seen, uniq = set(), []
    for r in rows:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    lines = ["# fpr.lock -- generated by `qos.py lock`; do not edit by hand.",
             "# Every `use \"spec#hash\"` pin in this tree, resolved to its",
             "# committed version (.fpr/versions.db) and content blob (.fpr/store).",
             "# spec  version  hash  pinned-by"]
    for spec, ver, h, by in uniq:
        lines.append(f"{spec} {ver} {h} {by}")
    return "\n".join(lines) + "\n", bad


def cmd_lock(a):
    text, bad = render_lock()
    for spec, h, by, why in bad:
        say(f"UNRESOLVABLE pin {spec}#{h} in {by}: {why}")
    if bad:
        die(f"{len(bad)} pin(s) not backed by a committed version -- `./qos.py commit <module>` each, then re-run")
    n = sum(1 for l in text.splitlines() if l and not l.startswith("#"))
    if a.check:
        cur = LOCK_PATH.read_text() if LOCK_PATH.is_file() else ""
        if cur != text:
            die(f"{LOCK_PATH.relative_to(ROOT)} is stale -- run `./qos.py lock` and commit it")
        say(f"lock: OK, {n} pin(s) all resolvable from the store, fpr.lock current")
        return 0
    LOCK_PATH.write_text(text)
    say(f"wrote {LOCK_PATH.relative_to(ROOT)}: {n} pin(s)")
    return 0


def restamp_qa(path, stamps):
    """Rewrite a .qa's MANIFEST with release identity (version, release,
    git, built).  QAR2's integrity sha covers the IMAGE only, so the
    manifest can carry provenance without touching what the loader
    verifies (docs/QA-FORMAT.md)."""
    b = path.read_bytes()
    if b[:5] != b"QAR2\n":
        die(f"{path}: not a QAR2 archive")
    head, _, rest = b.partition(b"\n\n")
    secs = []
    for line in head.decode().split("\n")[1:]:
        name, o, n = line.split()
        secs.append((name, rest[int(o):int(o) + int(n)]))
    blobs = dict(secs)
    man = blobs["MANIFEST"].decode()
    keep = [l for l in man.split("\n") if l and not re.match(r'^(version|release|git|built)\s*=', l)]
    man = "\n".join(keep) + "\n" + "".join(f'{k} = "{v}"\n' for k, v in stamps)
    blobs["MANIFEST"] = man.encode()
    off, table = 0, []
    for name, _ in secs:
        table.append(f"{name} {off} {len(blobs[name])}")
        off += len(blobs[name])
    path.write_bytes(b"QAR2\n" + "\n".join(table).encode() + b"\n\n" + b"".join(blobs[name] for name, _ in secs))


def app_stamps(prog, version, tag=None):
    """The identity a packed app carries: its own `#: version` when it
    declares one, else the release version; the git describe; the date."""
    d = prog_directives(ROOT / prog)
    v = (d.get("version") or [version])[0]
    return [("version", v), ("release", tag or f"v{version}"), ("git", git_describe()),
            ("built", time.strftime("%Y-%m-%d"))]


def sha256_of(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_release(a):
    """Cut a release: commit the library modules (fpr commit), regenerate
    and check the lock, run the smoke set, pack every release app as a
    stamped self-contained bundle under dist/qos-fpr-vX.Y.Z/, write the
    RELEASE manifest + SHA256SUMS + a tarball, then commit the version
    files and mint the annotated tag vX.Y.Z (--push sends branch + tag;
    the GitHub release itself is cut by .github/workflows/release.yml
    when the tag lands)."""
    import tarfile
    if not INSTALLED:
        fprisc_release_check()
    t0 = time.time()
    release = read_release()
    version = (a.version or release["version"]).lstrip("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        die(f"version must be X.Y.Z, got {version!r}")
    tag = f"v{version}"
    do_git = not a.no_git
    if do_git:
        dirty = git("status", "--porcelain")
        if dirty:
            die("working tree not clean -- commit or stash first:\n" + dirty)
        if git("tag", "-l", tag):
            die(f"tag {tag} already exists")
        if a.version and a.version.lstrip("v") != release["version"]:
            set_release_version(version)
            say(f"release.toml: version {release['version']} -> {version}")
    elif a.version and a.version.lstrip("v") != release["version"]:
        die(f"--no-git: release.toml says {release['version']}, tag says {version}; they must agree")
    build_fpr()
    # 1. module identity: every library module gets a committed version
    for mod in release["modules"]:
        m = resolve_prog(mod)
        r = subprocess.run([str(COMPILER), "commit", m], cwd=ROOT, capture_output=True, text=True)
        out = (r.stdout + r.stderr).strip().splitlines()
        if r.returncode != 0:
            for l in out:
                print("   " + l)
            die(f"fpr commit {m} refused -- fix as printed (pin the use / `./qos.py commit {m} --major`) and re-run")
        say(f"commit {m}: {out[-1] if out else 'ok'}")
    # 2. the lock: every pin in the tree is a named, stored version
    text, bad = render_lock()
    for spec, h, by, why in bad:
        say(f"UNRESOLVABLE pin {spec}#{h} in {by}: {why}")
    if bad:
        die("pins not backed by committed versions; add the module to release.toml `modules` or commit it")
    LOCK_PATH.write_text(text)
    say(f"fpr.lock: {sum(1 for l in text.splitlines() if l and not l.startswith('#'))} pin(s)")
    # 3. proof: the smoke set (the full sweep is --full)
    if a.full:
        say("the full sweep (check-all.sh)")
        if subprocess.call(["sh", "check-all.sh"], cwd=ROOT) != 0 or Path("/tmp/ck-fail.flag").exists():
            die("check-all.sh failed; not releasing")
    elif not a.skip_tests:
        cmd_test(argparse.Namespace(all=False, legs=[]))
    # 4. the artifacts: one stamped bundle per app
    out = WS.dist / f"qos-fpr-{tag}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    lines = [f"qos-fpr {tag}", f"git {git_describe()} ({git('rev-parse', 'HEAD', check=False) or '?'})",
             f"fprisc {json.loads((ROOT / 'fprisc.lock.json').read_text())['revision']}",
             f"date {time.strftime('%Y-%m-%d')}", f"host {os.uname().sysname.lower()}-{os.uname().machine}", "", "apps:"]
    for app in release["apps"]:
        prog = resolve_prog(app)
        d = prog_directives(ROOT / prog)
        name = (d.get("name") or [Path(prog).stem])[0]
        cmd_pack(argparse.Namespace(prog=prog, out=str(out / name), name=name, bundle=True, gfx=False,
                                    harts=None, plugin=None, no_plugins=False))
        qa = out / name / f"{name}.qa"
        stamps = app_stamps(prog, version, tag)
        restamp_qa(qa, stamps)
        lines.append(f"  {name}  version {stamps[0][1]}  sha256 {sha256_of(qa)}  ({prog})")
    lines += ["", "modules (fpr.lock):"] + ["  " + l for l in text.splitlines() if l and not l.startswith("#")]
    (out / "RELEASE.txt").write_text("\n".join(lines) + "\n")
    shutil.copy2(LOCK_PATH, out / "fpr.lock")
    sums = [f"{sha256_of(p)}  {p.relative_to(out)}" for p in sorted(out.rglob("*")) if p.is_file() and p.name != "SHA256SUMS"]
    (out / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    tarball = out.with_name(f"{out.name}-{os.uname().sysname.lower()}-{os.uname().machine}.tar.gz")
    with tarfile.open(tarball, "w:gz") as tf:
        tf.add(out, arcname=out.name)
    say(f"dist: {rel(out)}/ + {tarball.name} ({tarball.stat().st_size // 1024}KB)")
    # 5. identity in git: the version files, then the tag
    if do_git:
        git("add", "release.toml", "fprisc.lock.json", str(LOCK_PATH.relative_to(ROOT)), ".fpr")
        if git("status", "--porcelain"):
            git("commit", "-q", "-m", f"Release {tag}\n\n" + "\n".join(lines))
            say(f"committed release {tag}")
        git("tag", "-a", tag, "-F", str(out / "RELEASE.txt"))
        say(f"tagged {tag}")
        if a.push:
            branch = git("rev-parse", "--abbrev-ref", "HEAD")
            sh(["git", "push", "-u", "origin", branch], cwd=ROOT)
            sh(["git", "push", "origin", tag], cwd=ROOT)
            say(f"pushed {branch} + {tag} (the release workflow attaches the bundles)")
        else:
            say(f"not pushed: `git push origin {git('rev-parse', '--abbrev-ref', 'HEAD')} {tag}` when ready")
    say(f"release {tag} done in {time.time() - t0:.0f}s")
    return 0


SMOKE = [
    # (label, list-of-(prog, backend, expect))
    ("hello / qosp",      "tests/hello.fpr",    "qosp", "hello from a .qa"),
    ("mvu engine",        "tests/mvutick.fpr",  "qosp", "4 statics builds"),
    ("disk v2",           "tests/qdisk2.fpr",   "qosp", "torn=True"),
    ("dtree == GHC",      "tests/dtree.fpr",    "qosp", "root split: col 1"),
    ("bigfree",           "tests/bigfree.fpr",  "qosp", "BIGFREE HOLDS"),
    ("equality is deep",  "tests/eq.fpr",       "qosp", "ok  (1, 2) == (3, 4)"),
    ("dungeon rules",     "tests/dungeon.fpr",  "qosp", "dungeon rules: done"),
    ("fmath / virt",      "tests/fmath.fpr",    "virt", "FMATH HOLDS"),
    ("autodrop / virt",   "tests/autodrop.fpr", "virt", "AUTODROP HOLDS"),
    ("bigframe / virt",   "tests/bigframe.fpr", "virt", "sum3=57569"),
]

def cmd_test(a):
    if a.all:
        say("the full sweep (check-all.sh; ~12-15 min)")
        return subprocess.call(["sh", "check-all.sh"], cwd=ROOT)
    build_fpr()
    build_qosp()
    t0 = time.time()
    fails = []
    ran = 0
    for label, prog, backend, expect in SMOKE:
        if a.legs and not any(k in label or k in prog for k in a.legs):
            continue
        if backend == "qosp":
            qa = build_app(prog)
            r = subprocess.run([str(QOS / "qosp"), "--yes", str(qa)], cwd=WS.out, capture_output=True, timeout=180)
            out = r.stdout.decode("utf-8", "replace")
        else:
            r = subprocess.run(["make", "-s", "bare-metal-run", f"PROG={prog}", f"IMAGE={WS.mk().image(prog)}"] + WS.make_vars(),
                               cwd=ROOT, capture_output=True, timeout=300)
            out = r.stdout.decode("utf-8", "replace")
        ok = expect in out
        ran += 1
        say(f"{'ok  ' if ok else 'FAIL'} {label}")
        if not ok:
            fails.append(label)
    # the multi-client LiveView wire rides its own script
    if not a.legs or any("web" in k or "live" in k for k in a.legs):
        r = subprocess.run(["sh", "tests-host/mvuweb-check.sh"], cwd=QOS, capture_output=True, timeout=300)
        ok = b"ALL LEGS PASS" in r.stdout
        ran += 1
        say(f"{'ok  ' if ok else 'FAIL'} liveview multi-client")
        if not ok:
            fails.append("liveview")
    say(f"smoke: {ran - len(fails)}/{ran} in {time.time() - t0:.0f}s")
    if fails:
        die("failed: " + ", ".join(fails))

def cmd_clean(a):
    if WS.build.exists():
        shutil.rmtree(WS.build)
    for f in list(WS.out.glob("*.qa")) + list(WS.out.glob("*.elf")):
        f.unlink()
    say(f"{rel(WS.out)}/: build/, .qa, .elf removed (qosp.disk and qos-store/ kept: that is the app's state)")
    if not INSTALLED:
        sh(["make", "-s", "clean"], cwd=ROOT, quiet=True, check=False)
        sh(["make", "-s", "clean"], cwd=QOS, quiet=True, check=False)
        say("tree clean")


# ---- install: the tree as a toolchain under a prefix --------------------------
# What `brew install` lays down, and what a checkout can lay down for
# itself (`./qos.py install --prefix ~/.local`):
#
#   PREFIX/libexec/qos-fpr/    the tree -- programs/, apps/, std/, tests/,
#                              the .fpr store, hal/, qos/appside+portable,
#                              qosp[-gl], docs, and toolchain/ (the fprisc
#                              checkout: fpr, core/, std/, sol/) -- plus the
#                              .installed marker that makes qos.py treat
#                              it as shipped (never rebuilt, never written)
#   PREFIX/bin/fpr             -> libexec/qos-fpr/toolchain/fpr  (a symlink:
#                              the binary finds core/ and std/ beside its
#                              REAL path -- compiler/Home.hs)
#   PREFIX/bin/qos             -> libexec/qos-fpr/qos.py
#   PREFIX/bin/sol             exec fpr sol "$@"
#
# Sources ship because the QOS side is compiled per program (a .qa links
# hal/ and qos/appside for the host it runs on, or cross for virt); the
# Haskell is shipped as the binary, with compiler/ beside it for anyone
# who wants to rebuild.  Relative symlinks, so the prefix can move.

INSTALL_TREE = [
    "qos.py", "dependency.mk", "release.toml", "README.md", "docs", "fprisc.lock.json",
    "Makefile", "qos-app.mk", "std", "programs", "tools", "models", "targets",
    "apps", "tests", ".fpr", "fpr.lock", "hal", "loader", "core",
    "qos/Makefile", "qos/native", "qos/appside", "qos/portable", "qos/tests-host", "qos/qosp", "qos/qosp-gl",
]
INSTALL_SKIP = shutil.ignore_patterns("*.o", "*.hi", "*.qa", "*.disk", "*.img", "build", "dist-newstyle",
                                      "qos-store", "__pycache__", ".DS_Store", "*.s", "*.units", "*.elf")


def cmd_install(a):
    t0 = time.time()
    prefix = Path(a.prefix).resolve()
    lib = prefix / "libexec" / "qos-fpr"
    bin_ = prefix / "bin"
    if not INSTALLED:
        build_fpr()
        build_qosp()
        # the GL host wants GLFW; a machine without it still gets fpr + qosp
        if sh(["make", "-s", "portable-gl"], cwd=QOS, quiet=True, check=False) != 0:
            say("qosp-gl: not built (no GLFW dev package found) -- `#: host gl` programs need it")
    if lib.exists():
        shutil.rmtree(lib)
    for item in INSTALL_TREE:
        src = ROOT / item
        if not src.exists():
            continue
        dst = lib / item
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, ignore=INSTALL_SKIP, symlinks=False)
        else:
            shutil.copy2(src, dst)
    # Ship a distinct compiler tree, never a symlink overlay in the QOS tree.
    for item in ("fpr", "Makefile", "compiler", "core", "std", "sol", "tests", "tools", "runtime", "machine", "docs"):
        src, dst = TOOLCHAIN / item, lib / "toolchain" / item
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, ignore=INSTALL_SKIP)
        else:
            shutil.copy2(src, dst)
    ver = read_release()["version"]
    (lib / ".installed").write_text(f"qos-fpr {ver} installed {time.strftime('%Y-%m-%d')} from {ROOT}\n")
    bin_.mkdir(parents=True, exist_ok=True)
    for name, target in (("fpr", lib / "toolchain" / "fpr"), ("qos", lib / "qos.py")):
        link = bin_ / name
        link.unlink(missing_ok=True)
        link.symlink_to(os.path.relpath(target, bin_))
    sol = bin_ / "sol"
    sol.write_text('#!/bin/sh\n# sol -- the HostedBytecode profile is a subcommand of fpr\nexec "$(dirname "$0")/fpr" sol "$@"\n')
    sol.chmod(0o755)
    hosts = [h for h in ("qosp", "qosp-gl") if (lib / "qos" / h).is_file()]
    say(f"installed qos-fpr {ver} -> {lib} ({', '.join(['fpr'] + hosts)}); {bin_}/{{fpr,qos,sol}}")
    say(f"try: cd /tmp && {bin_}/qos new hello && {bin_}/qos run hello/app.fpr")
    say(f"install done in {time.time() - t0:.1f}s")

def main():
    ap = argparse.ArgumentParser(prog="qos.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    ap.add_argument("--fprisc", metavar="DIR", help="the fprisc checkout for this invocation (else $FPRISC_ROOT, fprisc.path, ../fprisc)")

    p = sub.add_parser("fprisc", help="which fprisc checkout this tree uses: DIR remembers it in fprisc.path; --pin records its commit for releases")
    p.add_argument("path", nargs="?", metavar="DIR")
    p.add_argument("--pin", action="store_true", help="write the clean checkout's commit to fprisc.lock.json")
    p.add_argument("--print", action="store_true", help="print the path alone (for scripts)")
    p.set_defaults(f=cmd_fprisc)

    p = sub.add_parser("build", help="bring the toolchain + hosts up to date")
    p.add_argument("what", nargs="?", default="host", choices=["fpr", "host", "native", "all"])
    p.set_defaults(f=cmd_build)

    p = sub.add_parser("run", help="compile + run one program (the pipeline)")
    p.add_argument("prog", help=".fpr or .sol, from anywhere in the tree")
    p.add_argument("--on", choices=["qosp", "virt", "sol"], default="qosp", help="qosp (hosted, default) | virt (bare-metal QEMU) | sol")
    p.add_argument("--port", help="FPR_PORT for the socket tier")
    p.add_argument("--harts", help="hart count")
    p.add_argument("--gfx", action="store_true", help="use the desktop-GL qosp host")
    p.add_argument("--fresh-disk", action="store_true", help="delete qosp.disk first")
    p.add_argument("--expect", help="require this substring in the output")
    p.add_argument("--plugin", action="append", help="build this .fpr as a plugin module and seed it onto a fresh disk (repeatable; overrides the program's `#: plugins` line)")
    p.add_argument("--no-plugins", action="store_true", help="ignore the program's `#: plugins` line")
    p.add_argument("--disk", help="run against this existing QLOG image (FPR_DISK)")
    p.add_argument("--fprd", action="store_true", help="start the host compiler daemon for the run (Sys.compile / CP.plugin)")
    p.set_defaults(f=cmd_run)

    p = sub.add_parser("new", help="scaffold a working app under apps/<name>/")
    p.add_argument("name", help="project name (lowercase start; becomes the app + artifact name)")
    p.add_argument("--template", choices=sorted(TEMPLATES), default="mvu",
                   help="min (pure compute) | service (actor rpc) | mvu (Model+schema+port, default) | notes (MVU + paths + livereload)")
    p.set_defaults(f=cmd_new)

    p = sub.add_parser("pack", help="package one program into dist/<name>/ (qa + disk + optional host bundle)")
    p.add_argument("prog", help=".fpr, from anywhere in the tree")
    p.add_argument("-o", "--out", help="output directory (default dist/<name>/)")
    p.add_argument("--name", help="artifact name (default: `#: name` directive, else the file stem)")
    p.add_argument("--bundle", action="store_true", help="include the qosp host binary + run.sh")
    p.add_argument("--gfx", action="store_true", help="bundle the desktop-GL qosp host")
    p.add_argument("--harts", help="hart count baked into the image build")
    p.add_argument("--plugin", action="append", help="plugin module to seed (repeatable; overrides `#: plugins`)")
    p.add_argument("--no-plugins", action="store_true", help="ignore the program's `#: plugins` line")
    p.set_defaults(f=cmd_pack)

    p = sub.add_parser("dev", help="the sketch loop: run interpreted (sol profile), rerun on save")
    p.add_argument("prog", help=".fpr or .sol, from anywhere in the tree")
    p.set_defaults(f=cmd_dev)

    p = sub.add_parser("serve", help="host a LiveView app on a port")
    p.add_argument("prog")
    p.add_argument("--port", default="8000")
    p.set_defaults(f=cmd_serve)

    p = sub.add_parser("native", help="build + boot QOS Native under QEMU")
    p.add_argument("--apps", nargs="*", default=[], help=".qa files to seed onto a fresh disk image")
    p.add_argument("--smp", type=int, default=2)
    p.add_argument("--mem", default="256M")
    p.add_argument("--smoke", action="store_true", help="scripted boot-to-launcher check instead of a console")
    p.set_defaults(f=cmd_native)

    p = sub.add_parser("disk", help="seed a QLOG disk image (mkdisk)")
    p.add_argument("img")
    p.add_argument("size_mb", type=int)
    p.add_argument("apps", nargs="*")
    p.set_defaults(f=cmd_disk)

    p = sub.add_parser("commit", help="fpr commit into the .fpr store")
    p.add_argument("mod")
    p.add_argument("--major", action="store_true")
    p.set_defaults(f=cmd_commit)

    p = sub.add_parser("lock", help="regenerate fpr.lock from the pins in the tree (--check: verify, no write)")
    p.add_argument("--check", action="store_true", help="fail if any pin lacks a committed version or the lock is stale")
    p.set_defaults(f=cmd_lock)

    p = sub.add_parser("release", help="cut vX.Y.Z: fpr commit the modules, lock, smoke, pack stamped bundles, tag")
    p.add_argument("version", nargs="?", help="X.Y.Z (default: release.toml's version)")
    p.add_argument("--push", action="store_true", help="push the branch and the tag (triggers the GitHub release workflow)")
    p.add_argument("--full", action="store_true", help="run the full sweep (check-all.sh) instead of the smoke set")
    p.add_argument("--skip-tests", action="store_true", help="no tests (CI builds after the sweep already ran)")
    p.add_argument("--no-git", action="store_true", help="build the dist bundles only: no commit, no tag (what CI runs)")
    p.set_defaults(f=cmd_release)

    p = sub.add_parser("test", help="the fast smoke set (--all = check-all)")
    p.add_argument("legs", nargs="*", help="filter by label/prog substring")
    p.add_argument("--all", action="store_true")
    p.set_defaults(f=cmd_test)

    p = sub.add_parser("install", help="lay the tree down as a toolchain under a prefix (what brew runs)")
    p.add_argument("--prefix", required=True, help="e.g. ~/.local or $(brew --prefix)/Cellar/qos-fpr/X.Y.Z")
    p.set_defaults(f=cmd_install)

    p = sub.add_parser("clean")
    p.set_defaults(f=cmd_clean)

    a = ap.parse_args()
    sys.exit(a.f(a) or 0)

if __name__ == "__main__":
    main()
