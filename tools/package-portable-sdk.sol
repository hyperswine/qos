# package-portable-sdk.sol -- package a verified, clean staged macOS ARM64 SDK
# and generate its Homebrew formula.
#
#   sol tools/package-portable-sdk.sol --sdk PREFIX --version 0.3.0 \
#     --compiler-licenses DIR --output DIR
#
# Run from inside the QOS checkout. A contributor tool: it never publishes,
# rebuilds or reads user disks, and the SDK it packages needs no Python (its
# `qos` is native). Run the installed SDK acceptance before publication. The
# tarball is the release unit: compiler, SDK, hosts and Main are pinned
# together in sdk.json and the inventory.
K = use "sdk/sdk".
J = use "sol/lib/json".
CLI = use "sol/lib/cli".

options = [CLI.Option "sdk" "" CLI.One, CLI.Option "version" "" CLI.One,
           CLI.Option "compiler-licenses" "" CLI.One, CLI.Option "output" "" CLI.One].
opt parsed key = CLI.valueOr "" key parsed.

digits t = Str.len t > 0 and List.all (fn c -> c >= 48 and c <= 57) (Str.codes t).
# MAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH-rcN
validVersion v = case Str.split 45 v of
    [core] -> triple core
  | [core, rc] -> triple core and Str.startsWith "rc" rc and digits (K.drop 2 rc)
  | _ -> False.
triple core = case Str.split 46 core of
    [a, b, c] -> digits a and digits b and digits c
  | _ -> False.

# an object's (key, text) pairs, sorted by key
textPairs : unsafe J.Json -> List (String, String) .
textPairs value = case value of
    J.JObj kvs -> K.sortBy (fn p -> (k, _) = p; k) (List.map (fn p -> (k, v) = p; (k, case v of J.JStr t -> t | _ -> "")) kvs)
  | _ -> [].

inventoryMatches : unsafe String -> J.Json -> Bool .
inventoryMatches sdk recorded = textPairs (K.inventory sdk) == textPairs recorded.

# relative path a, inside dir, with the recorded hash
noticeOk dir pair = case pair of (relative, sha) ->
  path = K.realpath "{dir}/{relative}";
  Str.startsWith "{K.realpath dir}/" path and K.sha256 path == sha.

# release files: no disks, Haskell, Python or Git metadata; C only as the
# private kind = "app" platform inputs
unexpected name = K.suffix name == ".disk" or K.suffix name == ".hs" or K.suffix name == ".py"
  or List.has ".git" (Str.split 47 name)
  or (K.suffix name == ".c" and Str.startsWith "platform/" name == False).

machO path = case Bytes.toList (K.need (Bytes.slice 0 4 (readBytes path))) of
    [207, 250, 237, 254] -> True
  | _ -> False.
readBytes path =
  r = K.need (Stream.openRead path 65536);
  (result, r2) = Stream.foldChunks (fn acc b -> b :: acc) [] r;
  _ = K.need (Stream.closeRead r2);
  Bytes.concat (List.rev (K.need result)).

# the minimum macOS a binary declares (vtool's minos)
minos path = case List.filter (fn l -> Str.startsWith "minos " (Str.trim l)) (K.lines (K.command ["/usr/bin/vtool", "-show-build", path])) of
    l :: _ -> Str.trim (K.drop 6 (Str.trim l))
  | [] -> error "{path}: no minos".
versionKey v = List.map (fn p -> Str.parse p) (Str.split 46 v).
newer : unsafe String -> String -> Bool .
newer a b = compareParts (versionKey a) (versionKey b) > 0.
compareParts : unsafe List Int -> List Int -> Int .
compareParts a b = case (a, b) of
    ([], []) -> 0
  | ([], _) -> 0 - 1
  | (_, []) -> 1
  | (x :: xs, y :: ys) -> if x == y then compareParts xs ys else (if x < y then 0 - 1 else 1).

linked path = List.drop 1 (K.lines (K.command ["/usr/bin/otool", "-L", path])).

package : unsafe String -> String -> String -> String -> String -> Unit .
package root prefix version output licenses =
  _ = K.check "version must be MAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH-rcN" (validVersion version);
  sdk = "{prefix}/libexec/qos-portable";
  meta = K.need (J.parse (K.readText "{sdk}/sdk.json"));
  revision = K.revision root;
  _ = K.check "commit QOS packaging changes before making a release" (K.dirty root == False);
  _ = K.check "stage and packager must use the same QOS revision" (K.text "qosRevision" meta == revision);
  _ = K.check "compiler license inventory is required" (K.isFile "{licenses}/manifest.json");
  notices = textPairs (K.field "notices" (K.need (J.parse (K.readText "{licenses}/manifest.json"))));
  _ = K.check "compiler license inventory mismatch" (List.all (fn p -> noticeOk licenses p) notices);
  _ = K.check "release SDK must be staged from clean committed repositories" (K.truthy "qosDirty" meta == False and K.truthy "fpriscDirty" meta == False);
  _ = K.check "release packaging is currently qualified only for macOS ARM64" (K.text "os" meta == "darwin" and K.text "architecture" meta == "aarch64");
  _ = K.check "staged SDK inventory mismatch" (inventoryMatches sdk (K.need (J.parse (K.readText "{sdk}/files.sha256.json"))));
  _ = K.check "release must include Main profile and both hosts" (K.truthy "profileFiles" meta and K.truthy "runtimeFiles" meta);
  # 0.2.0+: the package exports only `qos`; `fpr` belongs to the FP-RISC formula
  _ = K.check "stage exports bin/fpr; restage with this tree (only bin/qos is exported)" (K.exists "{prefix}/bin/fpr" == False and K.isLink "{prefix}/bin/fpr" == False);
  bad = List.filter unexpected (K.files sdk);
  _ = K.check "unexpected release files: {Str.join ", " bad}" (bad == []);
  # 0.3.0+: `qos` is native and the SDK may ship its own ld.lld
  _ = K.check "stage has no native tools/qos; restage with this tree" (K.isFile "{sdk}/tools/qos" and machO "{sdk}/tools/qos");
  shipsLld = K.isFile "{sdk}/toolchain/ld.lld";
  _ = K.check "toolchain/ld.lld does not match sdk.json"
        (shipsLld == False or K.text "ld.lld" (K.field "toolchainFiles" meta) == K.sha256 "{sdk}/toolchain/ld.lld");
  _ = K.check "toolchain/ld.lld ships without the LLVM license" (shipsLld == False or K.isFile "{sdk}/toolchain/LICENSE-LLVM.txt");
  binaries = ["compiler/fpr", "runtime/qosp", "runtime/qosp-gl", "tools/qos"] + (if shipsLld then ["toolchain/ld.lld"] else []);
  # do not advertise older systems than the binaries actually target
  minimum = List.fold (fn best b -> m = minos "{sdk}/{b}"; if newer m best then m else best) "0" binaries;
  _ = K.check "review formula minimum macOS before packaging binaries for another OS version" (List.take 1 (Str.split 46 minimum) == ["27"]);
  libraries = J.JObj (List.map (fn b -> (b, J.JArr (List.map J.JStr (linked "{sdk}/{b}")))) binaries);
  _ = K.check "output must be a fresh directory" (K.exists output == False);
  _ = K.mkdirs output;
  name = "qos-portable-{version}-macos-arm64";
  scratch = tempDir "qos-release";
  bundle = "{scratch}/{name}";
  _ = K.copyTree prefix bundle;
  # staged acceptance makes the input read-only; only the private copy is writable
  _ = K.writable bundle;
  copied = "{bundle}/libexec/qos-portable";
  released = J.set "nativeLibraries" libraries (J.set "minimumMacOS" (J.JStr minimum) (J.set "release" (J.JStr version) meta));
  _ = K.writeJson "{copied}/sdk.json" released;
  _ = K.copyTree licenses "{copied}/licenses";
  _ = K.copy "{root}/LICENSE" "{copied}/licenses/QOS-LICENSE";
  # the compiler's license is passed through with the staged inputs
  _ = K.check "stage must include the FP-RISC license" (K.isFile "{copied}/compiler/LICENSE");
  _ = K.writeJson "{copied}/files.sha256.json" (K.inventory copied);
  archive = "{output}/{name}.tar.gz";
  _ = K.command ["/usr/bin/tar", "-czf", archive, "-C", scratch, name];
  sha = K.sha256 archive;
  _ = K.writeText "{output}/SHA256SUMS" "{sha}  {name}.tar.gz\n";
  _ = K.writeJson "{output}/release.json" released;
  template = K.readText "{root}/packaging/homebrew/qos-portable.rb.in";
  lldDependency = if shipsLld then "" else "  depends_on \"lld\"\n";
  formula = Str.replace "__LLD_DEPENDENCY__\n" lldDependency
    (Str.replace "__SHA256__" sha (Str.replace "__ARCHIVE__" "{name}.tar.gz" (Str.replace "__VERSION__" version template)));
  _ = K.writeText "{output}/qos-portable.rb" formula;
  _ = print archive;
  print "SHA256 {sha}".

main : unsafe Unit .
main = parsed = K.need (CLI.parse options (args Unit));
  _ = K.check "--sdk, --version, --compiler-licenses and --output are required"
        (opt parsed "sdk" != "" and opt parsed "version" != "" and opt parsed "compiler-licenses" != "" and opt parsed "output" != "");
  root = K.trimEnd (K.command ["/usr/bin/git", "rev-parse", "--show-toplevel"]);
  _ = K.check "run from inside the QOS checkout" (K.isFile "{root}/tools/package-portable-sdk.sol");
  package root (K.realpath (opt parsed "sdk")) (opt parsed "version") (opt parsed "output") (K.realpath (opt parsed "compiler-licenses")).
