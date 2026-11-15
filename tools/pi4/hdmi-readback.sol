# Read back what the Pi's HDMI output shows, without touching the display.
#   sol tools/pi4/hdmi-readback.sol --host HOST --tool REMOTE_KMS_READBACK --output FILE.ppm [--card /dev/dri/card1]
# kms-readback (tools/pi4/kms-readback.c) maps the framebuffer of the active
# KMS CRTC read-only (no master, modeset or pixel write) and writes a PPM.
# The capture must be a 24-bit PPM of the expected size that is not one flat
# colour; the file is kept for comparison with earlier captures.
unsafe program.
R = use "remote".
CLI = use "sol/lib/cli".
options = List.map (fn k -> CLI.Option k "" CLI.One) ["host","tool","output","card","size"].
capture parsed =
  host = CLI.valueOr "" "host" parsed; tool = CLI.valueOr "" "tool" parsed; output = CLI.valueOr "" "output" parsed;
  _ = (if host == "" or tool == "" or output == "" then error "usage: sol tools/pi4/hdmi-readback.sol --host HOST --tool PATH --output FILE.ppm" else Unit);
  card = CLI.valueOr "/dev/dri/card1" "card" parsed;
  remote = "/tmp/hdmi-readback-{R.stamp Unit}.ppm";
  _ = R.ssh host 30 "{R.q tool} {R.q card} {R.q remote}";
  header = R.ssh host 10 "head -c 15 {R.q remote} | head -2 | tr '\\n' ' '";
  colours = parseInt (Str.trim (R.ssh host 60 "tail -c +16 {R.q remote} | od -An -tx1 -v -w3 | sort -u | head -3 | wc -l"));
  _ = R.copyFrom host remote output;
  _ = R.ssh host 10 "rm -f {R.q remote}";
  expected = CLI.valueOr "" "size" parsed;
  _ = (if Str.startsWith "P6 " header then Unit else error "not a binary PPM: {header}");
  _ = (if expected == "" or Str.contains expected header then Unit else error "capture is {header}, expected {expected}");
  _ = (if colours > 1 then Unit else error "the capture is one flat colour");
  print "hdmi readback: {header}, more than one colour, saved {output}".
> capture (R.need (CLI.parse options (args Unit))).
