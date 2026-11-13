K = use "sdk/sdk".
Config = use "sdk-lld-config".
Link = use "sdk-lld-link".

runTool argv = code = unwrap (Proc.streamNow (ProcessSpec argv "" [] "" 0));
  if code == 0 then Unit else error "{argv} exited {code}".
prefix name = K.trimEnd (K.command ["brew","--prefix",name]).
build directory driver =
  _ = K.mkdirs directory; work = K.realpath directory;
  llvm = prefix "llvm"; zstd = prefix "zstd"; source = "{work}/llvm-project";
  version = K.trimEnd (K.command ["{llvm}/bin/llvm-config","--version"]);
  _ = (if K.exists source then Unit else
    _ = runTool ["git","clone","--depth","1","--filter=blob:none","--sparse","--branch","llvmorg-{version}","https://github.com/llvm/llvm-project.git",source];
    runTool ["git","-C",source,"sparse-checkout","set","lld","cmake","libunwind/include"]);
  cfg = "{work}/llvm-cmake"; out = "{work}/build";
  _ = runTool ["rm","-rf",cfg]; _ = K.mkdirs cfg;
  _ = runTool ["cp","-R","{llvm}/lib/cmake/llvm/.",cfg];
  _ = Config.configure llvm cfg out;
  deployment = Link.deploymentTarget Unit;
  _ = runTool ["cmake","-S","{source}/lld","-B",out,"-G","Ninja","-DLLVM_DIR={cfg}","-DCMAKE_BUILD_TYPE=Release","-DLLVM_INCLUDE_TESTS=OFF","-DCMAKE_C_COMPILER=/usr/bin/clang","-DCMAKE_CXX_COMPILER=/usr/bin/clang++","-DCMAKE_OSX_DEPLOYMENT_TARGET={deployment}","-DLLVM_USE_STATIC_ZSTD=ON","-Dzstd_LIBRARY={zstd}/lib/libzstd.a","-Dzstd_STATIC_LIBRARY={zstd}/lib/libzstd.a"];
  _ = runTool ["ninja","-C",out,"lldELF","lldCommon","lld"];
  Link.link work llvm driver deployment.
> case args Unit of [directory] -> build directory "tools/sdk/ld-elf.cpp"
  | [driver,directory] -> build directory driver
  | _ -> error "usage: sol tools/build-sdk-lld.sol [DRIVER] WORKDIR".
