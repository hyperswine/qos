# qos-fpr.rb -- the Homebrew formula (macOS and Linux).
#
# Lives in a tap (hyperswine/homebrew-tap: Formula/qos-fpr.rb); this copy
# is the source of truth the tap is updated from on each release.  The
# formula does ONE thing after the dependencies: `./qos.py install
# --prefix`, which is also what a checkout runs for itself -- so the
# layout brew ships is the layout install-check.sh tests.
#
#   brew tap hyperswine/tap && brew install qos-fpr
#   brew install --build-from-source ./packaging/homebrew/qos-fpr.rb
#
# What lands: bin/fpr (the compiler + the sol VM), bin/sol (fpr sol),
# bin/qos (qos.py), and libexec/qos-fpr/ with the std, the HAL, the
# QOS host sources and the prebuilt qosp[-gl] -- see docs/2026-09-10-INSTALL.md.
class QosFpr < Formula
  desc "FP-RISC: the compiler, the Sol VM, and QOS Portable, as one toolchain"
  homepage "https://github.com/hyperswine/qos-fpr"
  url "https://github.com/hyperswine/qos-fpr/archive/refs/tags/v1.1.0.tar.gz"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000" # brew fetch --build-from-source fills this in
  license "MIT"
  head "https://github.com/hyperswine/qos-fpr.git", branch: "main"

  # the Haskell half is built here and shipped as a binary (bottles make
  # it prebuilt for users); the QOS half ships as source + qosp because a
  # .qa is compiled and linked per program on the machine that runs it
  depends_on "cabal-install" => :build
  depends_on "ghc" => :build
  depends_on "pkgconf" => :build
  depends_on "glfw"           # qosp-gl, the desktop-GL host (`#: host gl` programs)
  depends_on "python@3.12"    # qos.py (tomllib: 3.11+)

  on_macos do
    depends_on "llvm"         # `qos run` links a .qa with clang --target=aarch64-none-elf + lld
  end

  on_linux do
    depends_on "alsa-lib"     # the sound tier; WAV dump without it
    depends_on "mesa"         # vecgpu.c links EGL/GL into fpr
  end

  def install
    # the compiler's Hackage deps: megaparsec, network, utf8-string, mtl
    system "cabal", "v2-update"
    # builds fpr (cabal), qosp, and qosp-gl where GLFW is found, then lays
    # the tree down under libexec/qos-fpr with the .installed marker and
    # bin/{fpr,qos,sol}: fpr and qos are symlinks into libexec, which is
    # how fpr finds its prelude and std (compiler/Home.hs)
    system "python3.12", "./qos.py", "install", "--prefix", prefix
    rewrite_shebang detected_python_shebang, libexec/"qos-fpr/qos.py"
  end

  def caveats
    <<~EOS
      Every run writes to the directory you invoke from (.qos/ and dist/),
      never to the installed tree.  Start a project with:
        qos new myapp && qos run myapp/app.fpr
      Cross-compiling for QEMU virt (`qos run --on virt`) and QOS Native
      (`qos native`) additionally need riscv64-elf-gcc and qemu:
        brew install riscv64-elf-gcc riscv64-elf-binutils qemu
    EOS
  end

  test do
    # sol: the installed lib resolves under the toolchain's home
    (testpath/"s.sol").write "B = use \"sol/lib/base\".\n> print \"sol: {B.max0 7}{B.boolInt True}\".\n"
    assert_match "sol: 71", shell_output("#{bin}/sol s.sol")
    # fpr: compiles with the prelude beside the binary, no flag
    (testpath/"f.fpr").write "main = print \"fpr: {List.len (1 :: 2 :: Nil)}\".\n"
    system bin/"fpr", "compile", "--profile=qos-portable", "f.fpr", "f.s"
    assert_predicate testpath/"f.s", :exist?
    # qos: a project of its own, run through qosp, its .qa in ./.qos
    system bin/"qos", "new", "hello", "--template", "min"
    assert_match "hello: ok", shell_output("#{bin}/qos run hello/app.fpr")
    assert_predicate testpath/".qos/app.qa", :exist?
  end
end
