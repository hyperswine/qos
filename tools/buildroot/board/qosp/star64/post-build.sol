#!/usr/bin/env sol
H = use "../post-build".
publicKey line = case Str.words (Str.replace "\t" " " (Str.trim line)) of
    [] -> 0
  | kind :: rest -> if Str.startsWith "#" kind then 0 else
      if rest != [] and List.any (fn pre -> Str.startsWith pre kind) ["ssh-","ecdsa-","sk-"] then 1
      else error "STAR64: expected OpenSSH public keys without options".
configure target =
  table = "{target}/etc/inittab";
  retained = List.filter (fn line -> not (Str.endsWith "# STAR64_HDMI_LOGIN" line)) (H.rows (H.readText table));
  active = H.exists "-x" "{target}/etc/init.d/S99qosp";
  _ = (if active and List.any (fn line -> Str.startsWith "tty1::" line and Str.contains "getty" line) retained
       then error "STAR64: move the custom tty1 getty before enabling QOSP autostart" else Unit);
  _ = H.rewrite table (H.withConsole retained (if active then "tty2" else "tty1") "STAR64_HDMI_LOGIN");
  source = H.setting "QOSP_STAR64_AUTHORIZED_KEYS";
  ssh = "{target}/root/.ssh";
  _ = (if source == "" then H.command ["rm","-f","{ssh}/authorized_keys"] else
    if not (H.exists "-s" source) then error "STAR64: expected a nonempty public key file" else
      ProcessResult code path err = unwrap (Proc.runNow (ProcessSpec ["realpath",source] "" [] "" 0));
      if code != 0 then error "cannot resolve the public key file: {err}" else
        keys = List.map publicKey (H.rows (H.readText (substr path 0 (Str.len path - 1))));
        if not (List.has 1 keys) then error "STAR64: expected OpenSSH public keys" else
          _ = H.command ["install","-d","-m","0700",ssh];
          H.command ["install","-m","0600",source,"{ssh}/authorized_keys"]);
  images = H.required "BINARIES_DIR";
  host = H.required "HOST_DIR";
  board = H.required "BR2_EXTERNAL_QOSP_PATH" + "/board/qosp/star64";
  _ = H.command ["{host}/bin/spl_tool","-c","-f","{images}/u-boot-spl.bin"];
  its = "star64-uboot-fit-image.its";
  _ = H.command ["cp","{board}/{its}",images];
  H.run images ["{host}/bin/mkimage","-f",its,"-A","riscv","-O","u-boot","-T","firmware","opensbi_uboot_payload.img"].
> case args Unit of target :: _ -> configure target | [] -> configure (H.required "TARGET_DIR").
