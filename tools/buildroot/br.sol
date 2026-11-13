envOr key fallback = case unwrap (Env.get key) of
    EnvText value -> if value == "" then fallback else value
  | EnvMissing -> fallback.
toolStatus argv = unwrap (Proc.streamNow (ProcessSpec argv "" [] "" 0)).
checked argv = code = toolStatus argv; if code == 0 then Unit else error "{argv} exited {code}".
regular path = ProcessResult code _ _ = unwrap (Proc.runNow (ProcessSpec ["test","-f",path] "" [] "" 0)); code == 0.
image external board goals =
  home = envOr "HOME" "";
  config = (case board of "qemu" -> "qosp_qemu_aarch64_defconfig" | "rpi4" -> "qosp_rpi4_defconfig"
    | "star64" -> "qosp_star64_defconfig" | _ -> error "usage: sol tools/buildroot/br.sol EXTERNAL_DIR qemu|rpi4|star64 [make arguments]");
  defaultTree = (if board == "star64" then "{home}/buildroot-2026.08" else "{home}/buildroot");
  tree = envOr "BUILDROOT" defaultTree;
  _ = (if regular "{tree}/Makefile" then Unit else error "no Buildroot at {tree} (see tools/buildroot/README.md)");
  _ = (if board == "star64" then
    if toolStatus ["grep","-qx","config BR2_PACKAGE_MESA3D_GALLIUM_DRIVER_SOFTPIPE","{tree}/package/mesa3d/Config.in"] == 0 then Unit else error "star64 needs Buildroot 2026.08"
    else Unit);
  cache = envOr "QOSP_BR_O" "{home}/.cache/qosp-br"; out = "{cache}/{board}";
  _ = checked ["mkdir","-p",out];
  makeArgs = ["make","-C",tree,"O={out}","BR2_EXTERNAL={external}"];
  _ = (if regular "{out}/.config" then Unit else checked (makeArgs + [config]));
  _ = checked (makeArgs + goals);
  _ = print "br.sol: {board} images in {out}/images";
  ProcessResult exists _ _ = unwrap (Proc.runNow (ProcessSpec ["test","-d","{out}/images"] "" [] "" 0));
  if exists == 0 then _ = toolStatus ["ls","-la","{out}/images"]; Unit else Unit.
> case args Unit of external :: board :: goals -> image external board goals
  | _ -> error "usage: sol tools/buildroot/br.sol EXTERNAL_DIR qemu|rpi4|star64 [make arguments]".
