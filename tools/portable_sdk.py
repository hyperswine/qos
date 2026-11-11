#!/usr/bin/env python3
"""Installed QOS Portable SDK: scaffold, desktop plugin and standalone app builder.

Python >=3.11, Clang and lld are runtime dependencies. No make, C frontend
runtime build, GHC, Cabal or source checkout is used by this builder.
`kind = "desktop"` builds a plugin Main hosts; `kind = "app"` (qos.toml v2)
builds a process image `runtime/qosp-gl` or `runtime/qosp` runs directly,
linked from the SDK's private platform files (docs/2026-11-01-SDK-PROCESS-APPS.md).
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib

# Installed SDK helpers never create bytecode beside package-owned modules.
sys.dont_write_bytecode = True
from qos_archive import valid_id

SESSION = "qos.app-session/6"
API = "qos.desktop/2"
ROOT = Path(__file__).resolve().parent.parent

# qos.toml v2 (`manifest = 2`). v1 files have no `manifest` key and keep
# their exact v1 rules, so they build byte-identically to SDK 0.2.0.
MANIFEST_V2 = {"app": ({"id", "name", "version", "kind"}, set()),
               "build": ({"entry", "target"}, {"optimize", "compiler-memory-mb"}),
               "run": (set(), {"display", "disk-mb", "port"}),
               "sdk": ({"version"}, set()),
               "platform": (set(), {"override", "c-sources"})}
# `checks-only` keeps every type, safety and linearity check and turns off
# the optional optimisations a very large program may not afford.
OPTIMIZE = {"full": (), "checks-only": ("SPEC", "INLINE", "REUSE", "VEC_PEEK", "VEC_FUSE", "RECEIVE_TURNS")}
DISPLAYS = {"gl": "qosp-gl", "none": "qosp"}
SDK_VERSION = re.compile(r"(=?)(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*))?")

def sdk_version(text):
    match = SDK_VERSION.fullmatch(text)
    if match and all(int(n) <= 4611686018427387903 for n in match.group(2, 3, 4)):
        return match
    return None

# kind = "app": the platform units, in link order, and the build settings
# they are compiled with. Both are part of the platform cache key.
PLATFORM_UNITS = ("appside/entry.c", "appside/hal.c", "appside/support.c",
                  "runtime/runtime.c", "runtime/i32.c", "runtime/actors.c", "runtime/bits.c",
                  "runtime/vec.c", "runtime/sstr.c", "runtime/mod.c", "runtime/buddy.c",
                  "loader/qaimg.c", "portable/sha256.c", "machine/unix/ctx_a64.S")
PLATFORM_LINKER_SCRIPT = "appside/link-qosapp-a64.ld"
# macOS reserves 0x180000000-0x7000000000 in every process, so Darwin hosts
# and their apps sit at 1 TiB (qos-app.mk, qos_abi.h).
ARENA_BASE = "0x10000000000ul" if sys.platform == "darwin" else "0x400000000ul"
APP_CFLAGS = ("-O2", "-ffreestanding", "-nostdlib", "-fno-stack-protector", "-fno-asynchronous-unwind-tables",
              "-fno-pic", "-ffixed-x18", "-ffixed-x27", "-ffixed-x28", "-DFPR_POSIX", "-DFPR_QOSAPP",
              f"-DQOS_ARENA_BASE={ARENA_BASE}", "-DFPR_NHARTS=8", "-DFPR_SLAB_SZ=262144", "-DFPR_STACK_SZ=1048560")
MOVED_DELTA = "0x10000000"  # the 256 MiB displaced link that checks RELOC
# Platform files another file #includes instead of compiling them itself:
# overriding one recompiles its includer.
PLATFORM_INCLUDED_BY = {"hal/net_actor_bridge.c": "appside/hal.c"}


def fail(message):
    raise ValueError(message)


def scaffold(destination):
    destination = Path(destination)
    name = destination.name
    if not valid_id(name):
        fail("app ID: use 1-64 ASCII letters, digits, underscores, dots or hyphens; start with a letter, digit or underscore; no '..'")
    if destination.exists():
        fail(f"{destination} already exists")
    destination.mkdir(parents=True)
    (destination / "assets").mkdir()
    (destination / "assets/.gitkeep").touch()
    (destination / "main.fpr").write_text((ROOT / "tools/desktop-counter.fpr").read_text())
    (destination / ".gitignore").write_text("/build/\n")
    title = name.replace("-", " ").replace("_", " ").title()
    (destination / "qos.toml").write_text(
        f'[app]\nid = {json.dumps(name)}\nname = {json.dumps(title)}\n'
        'version = "0.1.0"\nkind = "desktop"\n\n'
        '[build]\nentry = "main.fpr"\ntarget = "qos-portable"\n')
    print(f"Created {destination}; cd there and run qos build")


def find_root(path):
    path = Path(path).resolve()
    if path.is_file():
        path = path.parent
    # Project discovery is explicit and bounded to ancestors, like other build tools.
    while not (path / "qos.toml").is_file():
        if path.parent == path:
            fail("no qos.toml in this directory or its parents; use qos new NAME")
        path = path.parent
    return path


def project(path):
    """(root, app, entry) of a desktop or app project (both manifest formats)."""
    found = load(path)
    return found["root"], found["app"], found["entry"]


def load(path):
    path = find_root(path)
    data = tomllib.loads((path / "qos.toml").read_text())
    if "manifest" in data:
        return load_v2(path, data)
    if set(data) != {"app", "build"}:
        fail("qos.toml v1 requires only [app] and [build]")
    app, build = data["app"], data["build"]
    if not isinstance(app, dict) or not isinstance(build, dict):
        fail("[app] and [build] must be TOML tables")
    if set(app) != {"id", "name", "version", "kind"} or set(build) != {"entry", "target"}:
        fail("qos.toml v1 requires app.id/name/version/kind and build.entry/target; unknown keys are refused")
    identity(app)
    if app["kind"] != "desktop" or build["target"] != "qos-portable":
        fail("SDK v2 supports kind=desktop and target=qos-portable only")
    return dict(root=path, manifest=1, app=app, build=build, run={}, sdk={}, platform={}, entry=entry_file(path, build))


def identity(app):
    if not valid_id(app["id"]):
        fail("invalid app.id (archive ID rules; maximum 64 ASCII bytes)")
    for field in ("name", "version"):
        if not isinstance(app[field], str) or not app[field] or any(ord(c) < 32 or c in '"\\' for c in app[field]):
            fail(f"app.{field} must be a nonempty single-line string")


def entry_file(path, build):
    if not isinstance(build["entry"], str) or Path(build["entry"]).is_absolute():
        fail("build.entry must be a relative .fpr file inside the project")
    entry = (path / build["entry"]).resolve()
    if not entry.is_relative_to(path) or not entry.is_file() or entry.suffix != ".fpr":
        fail("build.entry must be an existing .fpr file inside the project")
    # Assets have no public runtime lookup contract yet: refuse, never silently omit.
    if (path / "assets").exists() and any(p.is_file() and p.name != ".gitkeep" for p in (path / "assets").rglob("*")):
        fail("asset packaging is not supported by desktop SDK v2")
    return entry


def positive(table, key, low, high=None):
    value = table.get(key)
    if value is None:
        return None
    if type(value) is not int or value < low or (high is not None and value > high):
        bound = f"from {low} to {high}" if high is not None else f"of at least {low}"
        fail(f"{key} must be an integer {bound}")
    return value


def load_v2(path, data):
    if data["manifest"] != 2 or type(data["manifest"]) is not int:
        fail("this SDK reads qos.toml manifest = 2 (or v1, which has no manifest key)")
    tables = {k: v for k, v in data.items() if k != "manifest"}
    unknown = set(tables) - set(MANIFEST_V2)
    if unknown or not {"app", "build"} <= set(tables):
        fail("qos.toml v2 has [app] and [build], and optionally [run] and [sdk]; unknown tables are refused: "
             + ", ".join(sorted(unknown)) if unknown else "qos.toml v2 requires [app] and [build]")
    for name, table in tables.items():
        if not isinstance(table, dict):
            fail(f"[{name}] must be a TOML table")
        required, optional = MANIFEST_V2[name]
        missing, extra = required - set(table), set(table) - required - optional
        if missing or extra:
            fail(f"[{name}] needs {', '.join(sorted(required)) or 'no keys'}"
                 + (f" and may set {', '.join(sorted(optional))}" if optional else "")
                 + f"; {'missing ' + ', '.join(sorted(missing)) if missing else 'unknown ' + ', '.join(sorted(extra))}")
    app, build, run, pin = tables["app"], tables["build"], tables.get("run", {}), tables.get("sdk", {})
    platform = tables.get("platform", {})
    identity(app)
    if not isinstance(app["kind"], str) or app["kind"] not in ("desktop", "app"):
        fail('app.kind must be "desktop" (a Main plugin) or "app" (a standalone process image)')
    if build["target"] != "qos-portable":
        fail('build.target must be "qos-portable"')
    if not isinstance(build.get("optimize", "full"), str) or build.get("optimize", "full") not in OPTIMIZE:
        fail(f"build.optimize must be one of: {', '.join(OPTIMIZE)}")
    positive(build, "compiler-memory-mb", 1)  # GHC's own heap limit reports a value too small to compile with
    if run and app["kind"] != "app":
        fail('[run] applies to kind = "app"; a desktop app runs inside Main (qos run DISK)')
    if not isinstance(run.get("display", "gl"), str) or run.get("display", "gl") not in DISPLAYS:
        fail(f"run.display must be one of: {', '.join(DISPLAYS)}")
    positive(run, "disk-mb", 1)
    positive(run, "port", 0, 65535)  # a TCP port; 0 lets the host pick a free one
    if pin and (not isinstance(pin["version"], str) or not sdk_version(pin["version"])):
        fail('sdk.version must be "X.Y.Z" (that release or a later compatible one) or "=X.Y.Z" (exactly)')
    if platform and app["kind"] != "app":
        fail('[platform] applies to kind = "app"; a desktop app links no platform files')
    override = platform.get("override", {})
    if not isinstance(override, dict) or not all(isinstance(v, str) for v in override.values()):
        fail('[platform.override] maps SDK platform file names to project files, e.g. "appside/hal.c" = "native/hal.c"')
    sources = platform.get("c-sources", [])
    if not isinstance(sources, list) or not all(isinstance(v, str) for v in sources):
        fail('platform.c-sources must be a list of project files, e.g. ["native/sensor.c"]')
    if len(set(sources)) != len(sources) or set(sources) & set(override.values()):
        fail("each platform file is listed once: no repeated c-sources, and no file is both an override and a c-source")
    for value in [*override.values(), *sources]:
        project_file(path, value)
    return dict(root=path, manifest=2, app=app, build=build, run=run, sdk=pin, platform=platform,
                entry=entry_file(path, build))


def project_file(root, value):
    """A file the project names in [platform]: relative, inside the project, existing."""
    if Path(value).is_absolute():
        fail(f"[platform] {value!r} must be relative to the project")
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        fail(f"[platform] {value!r} must be an existing file inside the project")
    if path.suffix not in (".c", ".S"):
        fail(f"[platform] {value!r} must be a .c or .S file")
    return path


def platform_choices(root, platform, files):
    """Explicit overrides and added sources, checked against the SDK's inventory.

    Only names in the inventory can be replaced; headers are the ABI and the
    linker script is the layout the host loads, so neither can. A file that
    merely sits in the project never takes part: only listed files do.
    """
    overridable = sorted(n for n in files if Path(n).suffix in (".c", ".S"))
    overrides = {}
    for name, value in sorted(platform.get("override", {}).items()):
        if name not in files:
            fail(f"[platform.override] {name!r} is not an SDK platform file; these can be overridden: {', '.join(overridable)}")
        if name.endswith(".h"):
            fail(f"[platform.override] {name} is part of the SDK's ABI and cannot be overridden; a program that needs a different ABI needs a different SDK")
        if name not in overridable:
            fail(f"[platform.override] {name} is the image layout the host loads and cannot be overridden")
        source = project_file(root, value)
        if source.suffix != Path(name).suffix:
            fail(f"[platform.override] {name} must be replaced by a {Path(name).suffix} file, not {value!r}")
        overrides[name] = (value, source)
    headers = sorted({Path(n).name for n in files if n.endswith(".h")})
    added = []
    for value in platform.get("c-sources", []):
        source = project_file(root, value)
        # A quoted #include looks beside the source first, so a project copy
        # of an ABI header there would silently replace the SDK's.
        for header in headers:
            if (source.parent / header).exists():
                fail(f"{(source.parent / header).relative_to(root)} would replace the SDK's {header} for {value}; rename or move it")
        added.append((value, source))
    return overrides, added


def platform_record(overrides, added):
    """[[platformOverrides]] tables for the archive manifest (after its top-level keys)."""
    rows = [dict(kind="override", file=name, source=value, sha256=digest(source)) for name, (value, source) in overrides.items()]
    rows += [dict(kind="added", source=value, sha256=digest(source)) for value, source in added]
    return rows


def check_sdk_version(pin, meta):
    if not pin:
        return
    match = sdk_version(pin["version"])
    if not match:
        fail("invalid SDK version pin")
    exact, *parts = match.groups()
    wanted, wanted_tag = tuple(map(int, parts[:3])), parts[3] or ""
    release = meta.get("release")
    if not release:
        print(f"qos: this is a development SDK with no release number; sdk.version = {pin['version']!r} is not checked")
        return
    have = sdk_version(release)
    if not have or have[1]:
        fail(f"SDK release {release!r} is not X.Y.Z")
    actual, actual_tag = tuple(map(int, have.groups()[1:4])), have[5] or ""
    def series(v):
        return v[:2] if v[0] == 0 else v[:1]
    def tag_key(tag):
        return (1,) if not tag else (0, tuple((0, int(p)) if p.isdigit() else (1, p) for p in tag.split(".")))
    if exact and (actual, actual_tag) != (wanted, wanted_tag):
        fail(f"qos.toml pins SDK {pin['version']}; this is QOS Portable {release}")
    if not exact and (series(actual) != series(wanted) or (actual_tag and not wanted_tag)
                      or (actual, tag_key(actual_tag)) < (wanted, tag_key(wanted_tag))):
        fail(f"qos.toml needs SDK {pin['version']} or a later compatible release; this is QOS Portable {release}")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def platform_digest(files):
    """One hash over the platform inventory: what an app image is linked from."""
    return hashlib.sha256("".join(f"{sha}  {name}\n" for name, sha in sorted(files.items())).encode()).hexdigest()


def native():
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "aarch64", "qa64", "a64", "aarch64-none-elf"
    if machine in ("x86_64", "amd64"):
        return "x86_64", "qx64", "x64", "x86_64-none-elf"
    fail(f"desktop SDK v2 does not support {machine}")


def environment(sdk):
    # Do not inherit checkout/module overrides from a contributor's shell.
    env = {k: v for k, v in os.environ.items() if not k.startswith("FPR_") and k != "FPRISC_ROOT"}
    env.update(FPR_HOME=str(sdk / "modules"), FPR_PATH=str(sdk / "compiler"),
               FPR_FOREIGN=str(sdk / "modules/core/foreign.fpr"), LC_ALL="C.UTF-8",
               PYTHONDONTWRITEBYTECODE="1")
    return env


def run(args, env, log, verbose=False, cwd=None):
    command = shlex.join(map(str, args))
    log.write("+ " + command + "\n")
    result = subprocess.run(list(map(str, args)), env=env, capture_output=True, text=True, cwd=cwd)
    output = result.stdout + result.stderr
    log.write(output)
    log.flush()
    if verbose:
        print("+ " + command)
        print(output, end="")
    if result.returncode:
        if not verbose:
            print("\n".join(output.splitlines()[-60:]), file=sys.stderr)
        fail(f"{Path(args[0]).name} failed; see {log.name}")


def build(where, compiler=None, verbose=False):
    sdk = ROOT
    meta = json.loads((sdk / "sdk.json").read_text())
    arch, target, imports_arch, triple = native()
    if (meta.get("format"), meta.get("desktopApi"), meta.get("desktopSession"), meta.get("os"), meta.get("architecture")) != (
            1, API, SESSION, sys.platform, arch):
        fail("incompatible SDK: install a matching native QOS Portable SDK")
    fpr = (sdk / "compiler/fpr").resolve()
    if compiler and Path(compiler).resolve() != fpr:
        fail("the selected fpr and SDK differ; build with this SDK's `qos build`")
    if digest(fpr) != meta["compilerSha256"]:
        fail("SDK compiler changed; install a matching release set")
    found = load(where)
    root, app, entry = found["root"], found["app"], found["entry"]
    check_sdk_version(found["sdk"], meta)
    if app["kind"] == "app":
        return build_app(sdk, meta, fpr, found, verbose)
    # Reject quote/control characters rather than interpolate invalid FPR strings.
    if any(c in str(entry) for c in ('"', '\\', '\n', '\r')):
        fail("project path cannot contain quotes, backslashes or newlines")
    out = root / "build"
    if out.is_symlink():
        fail("build/ cannot be a symlink")
    out.mkdir(exist_ok=True)
    env = environment(sdk)
    if found["manifest"] == 2:
        compiler_settings(env, found["build"])
    clang = shutil.which("clang")
    linker = shutil.which("ld.lld")
    if not clang or not linker:
        fail("install Clang and lld and add their bin directories to PATH")
    # Unique intermediate directory; no SDK writes, no stale output publication.
    with tempfile.TemporaryDirectory(prefix=".desktop-", dir=out) as td, (out / "qos-build.log").open("w") as log:
        def command(args):
            run(args, env, log, verbose)

        work = Path(td)
        adapter, asm = work / "entry.fpr", work / "app.s"
        adapter.write_text((sdk / "tools/desktop-adapter.fpr.in").read_text().replace("__ENTRY__", entry.with_suffix("").as_posix()))
        command([fpr, "compile", f"--target={target}", "--plugin", f"--prelude={sdk / 'compiler/core/prelude.fpr'}", adapter, asm])
        units = Path(str(asm) + ".units").read_text().splitlines()
        objects = []
        for i, source in enumerate([str(asm)] + units):
            obj = work / f"unit-{i}.o"
            command([clang, f"--target={triple}", "-c", source, "-o", obj])
            objects.append(obj)
        common = [linker, "-T", sdk / "support/link-qosplug.ld", "--emit-relocs", "--no-relax"]
        first, image, moved = (work / x for x in ("first.elf", "image.elf", "moved.elf"))
        command(common + ["--defsym=PLUG_BASE=0", "--unresolved-symbols=ignore-all", *objects, "-o", first])
        stub = work / "imports.s"
        command([sys.executable, sdk / "tools/mkimports.py", "--arch", imports_arch, first, "-o", stub])
        stub_obj = work / "imports.o"
        command([clang, f"--target={triple}", "-c", stub, "-o", stub_obj])
        for base, dest in (("0", image), ("0x10000000", moved)):
            command(common + [f"--defsym=PLUG_BASE={base}", *objects, stub_obj, "-o", dest])
        revision = Path(str(asm) + ".abirev").read_text().strip()
        if meta.get("abi") != f'{meta["portableAbi"]}.{revision}':
            fail("SDK compiler/profile ABI mismatch; reinstall a matching SDK")
        fields = dict(name=app["name"], id=app["id"], version=app["version"], entry="fpr_modtab", loadMode="plugin",
                      abi=f'{meta["portableAbi"]}.{revision}', architecture=arch, desktopSession=SESSION, desktopApi=API)
        manifest = work / "manifest.toml"
        manifest.write_text("".join(f"{k} = {json.dumps(v, ensure_ascii=False)}\n" for k, v in fields.items()))
        archive = work / "app.qa"
        command([sys.executable, sdk / "tools/mkqa.py", manifest, image, "-o", archive,
             "--relocatable", "--imports", "--check-moved", moved, "--delta", "0x10000000"])
        destination = out / f'{app["id"]}.qa'
        archive.replace(destination)
    print(f"Built {destination}")
    return destination


def compiler_settings(env, build):
    """qos.toml v2 [build] settings; the compiler's environment is never the interface."""
    env.pop("GHCRTS", None)
    for name in OPTIMIZE[build.get("optimize", "full")]:
        env[f"FPR_NO_{name}"] = "1"
    if build.get("compiler-memory-mb"):
        env["GHCRTS"] = f'-M{build["compiler-memory-mb"]}M -A32M'


def cache_home():
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "qos-portable"


def platform_inputs(sdk, meta):
    """Verified platform inventory; a changed or missing file is refused by name."""
    files = meta.get("platformFiles")
    if not isinstance(files, dict) or meta.get("platformSha256") != platform_digest(files):
        fail('this SDK has no kind = "app" platform files; install QOS Portable 0.3.0 or later')
    for name in (*PLATFORM_UNITS, PLATFORM_LINKER_SCRIPT):
        if name not in files:
            fail(f"SDK platform inventory lacks {name}; reinstall a matching SDK")
    for name, expected in sorted(files.items()):
        path = sdk / "platform" / name
        if not path.is_file() or digest(path) != expected:
            fail(f"SDK platform file {name} changed; reinstall a matching SDK")
    return files


def app_flags(triple, platform):
    return [f"--target={triple}", *APP_CFLAGS,
            f"-I{platform / 'runtime'}", f"-I{platform / 'appside'}", f"-I{platform / 'hal'}"]


def platform_objects(sdk, meta, clang, triple, env, log, verbose):
    """Platform C compiled once per SDK hash, Clang and settings, into the user's cache."""
    version = subprocess.run([clang, "--version"], capture_output=True, text=True, check=True).stdout
    platform = sdk / "platform"
    flags = app_flags(triple, platform)
    identity = dict(platform=meta["platformSha256"], sdk=str(sdk), clang=version, flags=flags, units=PLATFORM_UNITS)
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    home = cache_home() / "platform"
    done = home / key
    objects = [done / (unit.replace("/", "-") + ".o") for unit in PLATFORM_UNITS]
    if (done / "identity.json").is_file() and all(o.is_file() for o in objects):
        return objects
    home.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".build-", dir=home))
    try:
        for unit, obj in zip(PLATFORM_UNITS, objects):
            run([clang, *flags, "-c", platform / unit, "-o", work / obj.name], env, log, verbose)
        (work / "identity.json").write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n")
        try:
            work.rename(done)
        except OSError:
            # Another build published the same key first; its objects are equivalent.
            if not (done / "identity.json").is_file():
                raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"Compiled SDK platform objects into {done}")
    return objects


def project_platform(sdk, work, cached, overrides, added, clang, triple, command):
    """Replace overridden platform objects and append added sources.

    An override is compiled from an overlay of the SDK's platform folder, in
    the SDK file's own place, so it sees exactly the SDK's headers and
    relative includes. Added sources compile where they are, against the
    SDK's include paths.
    """
    overlay = work / "platform"
    # Plain copies: the installed SDK is read-only and the overlay must not be.
    for path in (sdk / "platform").rglob("*"):
        if path.is_file():
            name = path.relative_to(sdk / "platform").as_posix()
            (overlay / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(overrides[name][1] if name in overrides else path, overlay / name)
    rebuild = {PLATFORM_INCLUDED_BY.get(name, name) for name in overrides}
    objects = list(cached)
    for i, unit in enumerate(PLATFORM_UNITS):
        if unit in rebuild:
            objects[i] = work / ("override-" + unit.replace("/", "-") + ".o")
            command([clang, *app_flags(triple, overlay), "-c", overlay / unit, "-o", objects[i]])
    for i, (_value, source) in enumerate(added):
        obj = work / f"added-{i}-{source.stem}.o"
        command([clang, *app_flags(triple, sdk / "platform"), "-c", source, "-o", obj])
        objects.append(obj)
    return objects


def build_app(sdk, meta, fpr, found, verbose):
    """kind = "app": one process image, every input from this SDK revision."""
    root, app, entry = found["root"], found["app"], found["entry"]
    arch, target, _imports_arch, triple = native()
    if arch != "aarch64":
        fail('kind = "app" needs an AArch64 host; this SDK\'s platform files are AArch64')
    files = platform_inputs(sdk, meta)
    overrides, added = platform_choices(root, found["platform"], files)
    for name, (value, source) in overrides.items():
        print(f"qos: platform override: {name} replaced by {value} (sha256 {digest(source)[:16]})")
    for value, source in added:
        print(f"qos: platform source added: {value} (sha256 {digest(source)[:16]})")
    out = root / "build"
    if out.is_symlink():
        fail("build/ cannot be a symlink")
    out.mkdir(exist_ok=True)
    env = environment(sdk)
    # An app may use the onboard programs' modules (mods/...), as Main does.
    env["FPR_PATH"] = f"{sdk / 'compiler'}:{sdk / 'modules/programs'}"
    compiler_settings(env, found["build"])
    clang = shutil.which("clang")
    linker = shutil.which("ld.lld")
    if not clang or not linker:
        fail("install Clang and lld and add their bin directories to PATH")
    with tempfile.TemporaryDirectory(prefix=".app-", dir=out) as td, (out / "qos-build.log").open("w") as log:
        def command(args, cwd=None):
            run(args, env, log, verbose, cwd)

        work = Path(td)
        asm = work / "app.s"
        # Relative imports (../models/...) resolve from the project, as with fpr.
        command([fpr, "compile", f"--target={target}", f"--prelude={sdk / 'compiler/core/prelude.fpr'}", entry, asm], cwd=root)
        revision = Path(str(asm) + ".abirev").read_text().strip()
        abi = f'{meta["portableAbi"]}.{revision}'
        if meta.get("abi") != abi:
            fail("SDK compiler/profile ABI mismatch; reinstall a matching SDK")
        program = []
        for i, source in enumerate([str(asm)] + Path(str(asm) + ".units").read_text().splitlines()):
            obj = work / f"unit-{i}.o"
            command([clang, f"--target={triple}", "-c", source, "-o", obj])
            program.append(obj)
        platform = platform_objects(sdk, meta, clang, triple, env, log, verbose)
        if overrides or added:
            platform = project_platform(sdk, work, platform, overrides, added, clang, triple, command)
        common = [linker, "-T", sdk / "platform" / PLATFORM_LINKER_SCRIPT, "--emit-relocs",
                  "--defsym=_heap_start=_proc_image_end", "--defsym=_heap_end=_proc_image_end"]
        first, image, moved = (work / x for x in ("first.elf", "image.elf", "moved.elf"))
        # Two links: the first learns the runtime's symbols, the export table
        # plugins import from by name is generated, and the real link has it.
        command(common + ["--defsym=QOS_SLOT_BASE=0", "--unresolved-symbols=ignore-all", *program, *platform, "-o", first])
        exports = work / "exports.s"
        command([sys.executable, sdk / "tools/mkexports.py", first, "-o", exports])
        exports_obj = work / "exports.o"
        command([clang, f"--target={triple}", "-c", exports, "-o", exports_obj])
        for base, dest in (("0", image), (MOVED_DELTA, moved)):
            command(common + [f"--defsym=QOS_SLOT_BASE={base}", *program, *platform, exports_obj, "-o", dest])
        # The archive records what built it, so a build can be repeated.
        fields = dict(name=app["name"], id=app["id"], version=app["version"], entry="n/a", loadMode="process",
                      abi=abi, architecture=arch, sdkPlatformSha256=meta["platformSha256"],
                      sdkCompilerSha256=meta["compilerSha256"], optimize=found["build"].get("optimize", "full"))
        if meta.get("release"):
            fields["sdkRelease"] = meta["release"]
        if found["build"].get("compiler-memory-mb"):
            fields["compilerMemoryMb"] = found["build"]["compiler-memory-mb"]
        manifest = work / "manifest.toml"
        text = "".join(f"{k} = {json.dumps(v, ensure_ascii=False)}\n" for k, v in fields.items())
        # Tables go last: hosts read the top-level keys and skip tables they do not know.
        for row in platform_record(overrides, added):
            text += "\n[[platformOverrides]]\n" + "".join(f"{k} = {json.dumps(v, ensure_ascii=False)}\n" for k, v in row.items())
        manifest.write_text(text)
        archive = work / "app.qa"
        command([sys.executable, sdk / "tools/mkqa.py", manifest, image, "-o", archive,
                 "--relocatable", "--check-moved", moved, "--delta", MOVED_DELTA])
        destination = out / f'{app["id"]}.qa'
        archive.replace(destination)
    print(f"Built {destination}")
    return destination


def archive_manifest(path):
    raw = path.read_bytes()
    header, _, payload = raw.partition(b"\n\n")
    lines = header.decode("ascii", "replace").splitlines()
    if not lines or lines[0] != "QAR2":
        fail(f"{path} is not a QOS app archive; rebuild with qos build")
    for line in lines[1:]:
        name, offset, size = line.split()
        if name == "MANIFEST":
            return tomllib.loads(payload[int(offset):int(offset) + int(size)].decode("utf-8"))
    fail(f"{path} has no manifest; rebuild with qos build")


def run_app(where, disk=None, trace=False):
    """Start a kind = "app" image on its own disk; the host replaces this process."""
    sdk = ROOT
    meta = json.loads((sdk / "sdk.json").read_text())
    found = load(where)
    root, app, settings = found["root"], found["app"], found["run"]
    if app["kind"] != "app":
        fail('qos run PROJECT runs kind = "app"; a desktop app runs inside Main: qos run DISK')
    archive = root / "build" / f'{app["id"]}.qa'
    if not archive.is_file():
        fail(f"{archive} does not exist; run qos build first")
    built = archive_manifest(archive)
    if (built.get("id"), built.get("loadMode"), built.get("abi")) != (app["id"], "process", meta.get("abi")):
        fail(f"{archive} was not built by this SDK for this project; run qos build")
    for row in built.get("platformOverrides", []):
        if row.get("kind") == "override":
            print(f"qos: this image replaces the SDK's {row.get('file')} with {row.get('source')}")
        else:
            print(f"qos: this image adds {row.get('source')} to the SDK's platform files")
    host = sdk / "runtime" / DISPLAYS[settings.get("display", "gl")]
    expected = meta.get("runtimeFiles", {}).get(host.name)
    if not expected or not host.is_file() or digest(host) != expected:
        fail(f"matching prebuilt host {host.name} missing or changed; reinstall SDK")
    disk = Path(disk) if disk else root / "data" / f'{app["id"]}.disk'
    if not disk.exists():
        disk.parent.mkdir(parents=True, exist_ok=True)
        size = settings.get("disk-mb", 32)
        fd = os.open(disk, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            os.ftruncate(fd, size << 20)  # sparse and unformatted, as the host makes one
        finally:
            os.close(fd)
        print(f"Created {disk} ({size} MiB)")
    disk = disk.resolve()
    fd = os.open(disk, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        fail(f"{disk} is in use by another QOS process")
    # The host takes over this locked open file (hal/unix/blk_raw.c), so
    # nothing can open the disk between this check and the launch.
    os.set_inheritable(fd, True)
    env = dict(os.environ, FPR_DISK=str(disk), FPR_DISK_LOCK_FD=str(fd), FPR_PORT=str(settings.get("port", 0)))
    sys.stdout.flush()
    os.execve(host, [str(host), "--yes", *(["--trace"] if trace else []), str(archive)], env)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", action="store_true", help="show installed release and API versions")
    sub = ap.add_subparsers(dest="command")
    p = sub.add_parser("new")
    p.add_argument("destination")
    p = sub.add_parser("build")
    p.add_argument("project", nargs="?", default=".")
    p.add_argument("--compiler")
    p.add_argument("-v", "--verbose", action="store_true")
    p = sub.add_parser("disk")
    disks = p.add_subparsers(dest="disk_command", required=True)
    p = disks.add_parser("create")
    p.add_argument("destination")
    p.add_argument("--profile", choices=["main"], default="main")
    p.add_argument("--size", type=int, default=32, help="disk size in MiB")
    p = sub.add_parser("install")
    p.add_argument("archive", nargs="?")
    p.add_argument("destination", nargs="?")
    p.add_argument("--prefix", help=argparse.SUPPRESS)
    p = sub.add_parser("run", help="run a kind = \"app\" project (default: this directory), or Main on DISK")
    p.add_argument("target", nargs="?", metavar="PROJECT|DISK")
    p.add_argument("--disk", help='kind = "app": use this disk instead of data/ID.disk')
    p.add_argument("--trace", action="store_true", help='kind = "app": pass --trace to the host')
    args = ap.parse_args()
    if args.version:
        meta = json.loads((ROOT / "sdk.json").read_text())
        print(f"QOS Portable {meta.get('release', 'development')} ({API}, {SESSION})")
        return
    if not args.command:
        ap.error("choose a command (see --help)")
    try:
        if args.command == "run" and (args.target is None or Path(args.target).is_dir()):
            run_app(args.target or ".", args.disk, args.trace)
        elif args.command == "run" and (args.disk or args.trace):
            fail("--disk and --trace apply to qos run PROJECT (kind = \"app\")")
        elif args.command == "new":
            scaffold(args.destination)
        elif args.command == "build":
            build(args.project, args.compiler, args.verbose)
        else:
            import desktop_install
            if args.command == "disk":
                desktop_install.create(ROOT, args.destination, args.size)
            elif args.command == "install":
                if args.prefix is not None:
                    fail("toolchain installation moved to qos toolchain install --prefix (contributor CLI)")
                if not args.archive or not args.destination:
                    fail("usage: qos install APP.qa DISK")
                desktop_install.install(ROOT, args.archive, args.destination)
            elif args.command == "run":
                sys.exit(desktop_install.run(ROOT, args.target))
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"qos: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
