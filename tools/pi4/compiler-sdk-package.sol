# Each child commits its staged files before the following tool opens them.
package tools sdk compiler arch py kind glibc qr fr qd fd stdlib extensions output scratch limit roots =
  tool name argv = List.append ["{sdk}/bin/sol","{tools}/compiler-sdk-{name}.sol"] argv;
  run name argv = case Proc.streamNow (ProcessSpec (tool name argv) "" [] "" 0) of
      Ok 0 -> Unit | failed -> error "SDK {name} failed: {failed}";
  # py is "native" when the SDK carries bin/qos-fprd; nothing of Python is packaged
  _ = run "libs" (List.append ["{sdk}/lib",extensions,"{sdk}/python/lib/python/lib-dynload"] roots);
  _ = run "strip" [sdk];
  _ = run "metadata" [sdk,compiler,arch,py,kind,glibc,qr,fr,qd,fd];
  run "archive" [sdk,output,scratch,limit].
> case args Unit of tools :: sdk :: compiler :: arch :: py :: kind :: glibc :: qr :: fr :: qd :: fd :: stdlib :: extensions :: output :: scratch :: limit :: roots ->
    package tools sdk compiler arch py kind glibc qr fr qd fd stdlib extensions output scratch limit roots
  | _ -> error "expected SDK packaging inputs and ELF roots".
