#!/usr/bin/env sol
H = use "../post-build".
privateMode root kind mode name =
  path = "{root}/{name}";
  if not (H.exists kind path) then Unit else
    if H.exists "-L" path then error "Pi provisioning path is a symlink: {name}" else H.command ["chmod",mode,path].
keepArg token =
  port = (Str.split 44 token) ! 0;
  digits = Str.slice port 11 (Str.len port);
  graphical = Str.startsWith "console=tty" port and digits != "" and List.all (fn c -> c >= 48 and c <= 57) (Str.codes digits);
  not (graphical or token == "quiet" or token == "logo.nologo" or
    List.any (fn prefix -> Str.startsWith prefix token) ["loglevel=","vt.global_cursor_default=","consoleblank="]).
splash root =
  if not (H.exists "-x" "{root}/usr/bin/qosp-splash" and H.exists "-x" "{root}/etc/init.d/S12qosp-splash")
  then error "Pi splash selected but not installed; rebuild qosp before making the image" else
    cmdline = H.required "BINARIES_DIR" + "/rpi-firmware/cmdline.txt";
    words = Str.words (Str.replace "\n" " " (Str.replace "\t" " " (H.readText cmdline)));
    flags = ["quiet","loglevel=3","logo.nologo","vt.global_cursor_default=0","consoleblank=0"];
    _ = H.rewrite cmdline (Str.join " " (List.append (List.filter keepArg words) flags) + "\n");
    _ = H.command ["mkdir","-p","{root}/etc/default"];
    defaults = "{root}/etc/default/qosp";
    _ = H.command ["touch",defaults];
    old = List.filter (fn line -> not (Str.endsWith "# QOSP_BOOT_SPLASH" line)) (H.rows (H.readText defaults));
    H.rewrite defaults (H.linesText old + "export FPR_BOOT_SPLASH=1 # QOSP_BOOT_SPLASH\n").
configure root =
  _ = List.map (privateMode root "-f" "0600") ["etc/wpa_supplicant.conf","etc/ssh/sshd_config","root/.ssh/authorized_keys"];
  _ = List.map (privateMode root "-d" "0700") ["root","root/.ssh"];
  path = H.setting "BR2_CONFIG";
  config = if path == "" or not (H.exists "-f" path) then [] else H.rows (H.readText path);
  table = "{root}/etc/inittab";
  _ = (if List.has "BR2_PACKAGE_QOSP_AUTOSTART=y" config then
    retained = List.filter (fn line -> not (Str.startsWith "tty1::" line and Str.endsWith "# HDMI console" line)) (H.rows (H.readText table));
    H.rewrite table (H.withConsole retained "tty2" "QOSP_RECOVERY_CONSOLE")
    else Unit);
  if List.has "BR2_PACKAGE_QOSP_BOOT_SPLASH=y" config then splash root else Unit.
> case args Unit of target :: _ -> configure target | _ -> error "expected Buildroot target directory".
