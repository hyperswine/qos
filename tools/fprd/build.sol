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
  ghc = ["ghc","-O1","-threaded","-v0","-outputdir",objects,"-o",target,source];
  _ = (if fprisc != "" and B.exists "-f" "{fprisc}/dist-newstyle/cache/plan.json"
    then B.inDirectory fprisc [] (List.append ["cabal","exec","-v0","--"] ghc) else B.command ghc);
  print "built {target}".
> case args Unit of
    [output] -> build output (B.setting "FPRISC_ROOT" "")
  | [output,fprisc] -> build output (B.query ["realpath",fprisc])
  | _ -> error "usage: sol tools/fprd/build.sol OUTPUT [FPRISC_ROOT]".
