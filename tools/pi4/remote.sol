# Shared by the Pi drivers (check, main-soak, soak, hdmi-readback): public-key
# SSH and SCP to root@HOST from the Mac. Sol does not run on the Pi; every
# device step is a POSIX shell command sent over SSH.
J = use "sol/lib/json".
need r = case r of Ok x -> x | Err why -> error "{why}".
options = ["-o","BatchMode=yes","-o","ConnectTimeout=5","-o","ServerAliveInterval=15"].
# one shell word, single-quoted
q s = "'{Str.replace "'" "'\\''" s}'".
words xs = Str.join " " (List.map q xs).
# the command's stdout; a nonzero exit or the deadline (seconds) is an error
ssh host seconds command =
  ProcessResult code out err = need (Proc.runNow (ProcessSpec (List.append (List.append ["ssh"] options) ["root@{host}",command]) "" [] "" (seconds * 1000)));
  if code == 0 then out else error "ssh {host} exited {code}: {err}{Str.slice command 0 300}".
# exit code and output, for checks that expect failure
sshStatus host seconds command =
  ProcessResult code out err = need (Proc.runNow (ProcessSpec (List.append (List.append ["ssh"] options) ["root@{host}",command]) "" [] "" (seconds * 1000)));
  (code, out).
copyTo host from to =
  ProcessResult code _ err = need (Proc.runNow (ProcessSpec (List.append (List.append ["scp","-q"] options) [from,"root@{host}:{to}"]) "" [] "" 600000));
  if code == 0 then Unit else error "scp to {host}:{to} failed: {err}".
copyFrom host from to =
  ProcessResult code _ err = need (Proc.runNow (ProcessSpec (List.append (List.append ["scp","-q"] options) ["root@{host}:{from}",to]) "" [] "" 600000));
  if code == 0 then Unit else error "scp from {host}:{from} failed: {err}".
local argv =
  ProcessResult code out err = need (Proc.runNow (ProcessSpec argv "" [] "" 600000));
  if code == 0 then Str.trim out else error "{argv}: {err}".
stamp u = local ["date","-u","+%Y%m%dT%H%M%SZ"].
write path text = writePath path text.
field key value = need (J.get key value).
number key value = need (J.num (field key value)).
flag key value = need (J.bool (field key value)).
# the evdev record for one key press and release, as printf octal escapes:
# struct input_event {i64 sec; i64 usec; u16 type; u16 code; i32 value}
octal n = "\\{n / 64}{(n / 8) % 8}{n % 8}".
le n width = List.append (List.map (fn p -> (n / p) % 256) (List.take width [1,256,65536,16777216]))
  (if width > 4 then List.map (fn i -> 0) (List.range 1 (width - 4)) else []).
event kind code value = Str.join "" (List.map octal (List.concat [le 0 16, le kind 2, le code 2, le value 4])).
keyPress code = "{event 1 code 1}{event 1 code 0}".
readLocal path = readPath path.
