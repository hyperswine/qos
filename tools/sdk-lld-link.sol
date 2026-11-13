K = use "sdk/sdk".
unused = ["lldCOFF","lldMachO","lldMinGW","lldWasm","LibDriver","WindowsDriver","WindowsManifest","libxml2"].
library word = (Str.endsWith ".a" word or Str.endsWith ".tbd" word or Str.startsWith "-l" word)
  and List.any (fn name -> Str.contains name word) unused == False.
deploymentTarget u =
  version = K.trimEnd (K.command ["sw_vers","-productVersion"]);
  major = (case Str.split 46 version of first :: _ -> first | [] -> error "missing macOS version");
  "{major}.0".
link work llvm source deployment =
  build = "{work}/build"; path = "{work}/ld.lld"; obj = "{build}/ld-elf.o";
  # Ask Ninja for just the final link edge (all prerequisite compilations can exceed the output limit).
  commands = K.lines (K.command ["ninja","-C",build,"-t","commands","-s","bin/lld"]);
  words = (case List.rev commands of last :: _ -> Str.words last | [] -> error "missing Ninja link command");
  libs = List.map (fn w -> if Str.startsWith "lib/" w then "{build}/{w}" else w) (List.filter library words);
  _ = K.check "missing ELF linker archive in Ninja link command" (List.any (Str.endsWith "liblldELF.a") libs);
  minOS = "-mmacosx-version-min={deployment}";
  _ = K.command ["/usr/bin/clang++","-std=c++17","-O2","-DNDEBUG","-fno-rtti",minOS,"-I{work}/llvm-project/lld/include","-I{build}/include","-I{llvm}/include","-c",source,"-o",obj];
  _ = K.command (["/usr/bin/clang++","-O2",minOS,"-Wl,-dead_strip","-Wl,-dead_strip_dylibs","-Wl,-no_warn_duplicate_libraries",obj] + libs + ["-o",path]);
  _ = K.command ["strip","-x",path];
  deps = List.drop 1 (K.lines (K.command ["otool","-L",path]));
  _ = K.check "{path} links libraries outside the system" (List.all (fn dep -> Str.startsWith "/usr/lib/" (Str.trim dep)) deps);
  _ = print (K.trimEnd (K.command [path,"--version"])); print path.
