# Build the native compiler daemon, qos-fprd (tools/fprd/QosFprd.hs).
#   sol tools/fprd/build.sol OUTPUT [FPRISC_ROOT]
# It needs only GHC's boot packages plus network, which every FP-RISC build
# already has: a checkout built with cabal lends its package environment
# (cabal exec in FPRISC_ROOT); elsewhere (the Debian builder, with
# libghc-network-dev) the global package database serves.
B = use "sol/lib/build".
build output fprisc =
  here = B.query ["pwd","-P"];
  source = "{here}/tools/fprd/QosFprd.hs";
  _ = (if B.exists "-f" source then Unit else error "run from the qos checkout (no {source})");
  dir = B.query ["dirname",output];
  _ = B.command ["mkdir","-p",dir];
  target = "{B.query ["realpath",dir]}/{B.query ["basename",output]}";
  objects = "{target}.objects";
  _ = B.command ["mkdir","-p",objects];
  # On Linux the SDK starts bin/qos-fprd directly (no wrapper sets
  # LD_LIBRARY_PATH): find the libraries the packager copies beside it.
  rpath = (if B.query ["uname","-s"] == "Linux" then ["-optl-Wl,-rpath,$ORIGIN/../lib"] else []);
  ghc = List.append ["ghc","-O1","-threaded","-rtsopts","-v0","-outputdir",objects,"-o",target] (List.append rpath [source]);
  # a cabal plan whose store is gone (another container) fails: fall back
  borrowed = fprisc != "" and B.exists "-f" "{fprisc}/dist-newstyle/cache/plan.json"
    and Proc.streamNow (ProcessSpec (List.append ["cabal","exec","-v0","--"] ghc) fprisc [] "" 0) == Ok 0;
  _ = (if borrowed then Unit else B.command ghc);
  print "built {target}".
> case args Unit of
    [output] -> build output (B.setting "FPRISC_ROOT" "")
  | [output,fprisc] -> build output (B.query ["realpath",fprisc])
  | _ -> error "usage: sol tools/fprd/build.sol OUTPUT [FPRISC_ROOT]".
