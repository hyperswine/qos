# Each child commits its staged files before the following tool opens them.
package tools sdk compiler arch served kind glibc qr fr qd fd output scratch limit roots =
  tool name argv = List.append ["{sdk}/bin/sol","{tools}/compiler-sdk-{name}.sol"] argv;
  run name argv = case Proc.streamNow (ProcessSpec (tool name argv) "" [] "" 0) of
      Ok 0 -> Unit | failed -> error "SDK {name} failed: {failed}";
  # served is "native" when the SDK carries bin/qos-fprd
  _ = run "libs" (List.append ["{sdk}/lib"] roots);
  _ = run "strip" [sdk];
  _ = run "metadata" [sdk,compiler,arch,served,kind,glibc,qr,fr,qd,fd];
  run "archive" [sdk,output,scratch,limit].
> case args Unit of tools :: sdk :: compiler :: arch :: served :: kind :: glibc :: qr :: fr :: qd :: fd :: output :: scratch :: limit :: roots ->
    package tools sdk compiler arch served kind glibc qr fr qd fd output scratch limit roots
  | _ -> error "expected SDK packaging inputs and ELF roots".
