# Input on QOS Portable

One primitive, `inputPoll : Unit -> (kind, a, c)`, answers `(0, 0, 0)` when
nothing is pending and otherwise one event:

| kind | a | c | source |
|---|---|---|---|
| 1 | byte | 0 | a raw stdin byte (GL tier only) |
| 2 | dx | dy | relative mouse motion, PS/2 sense: **+y is up** |
| 3 | buttons | 0 | the button mask after a change (1 left, 2 right, 4 middle) |
| 4 | keycode | value | a key: Linux input-event code, value 0 release / 1 press / 2 repeat |
| 5 | cols | rows | the terminal's size, at start and on every resize |

A keycode carries its modifiers as a bias: shift +1000, ctrl +4000, alt +8000.
`h` is 35 and `H` is 1035 from every source, because there is one modifier
machine (`hal/unix/evdev_raw.c`) and the terminal decoder speaks its codes.

## Where events come from

The implementation is the host's HAL (`hal/unix/`): `evdev_raw.c` (keyboards),
`mice_raw.c` (pointers), `tty_raw.c` (terminals, and the headless tier's source
policy, `qos_headless_poll`), `gfx.c` (a GLFW window).

**`qosp`, no window.** Chosen by `FPR_EVDEV`:

| `FPR_EVDEV` | keys | mouse | size |
|---|---|---|---|
| unset | the terminal (stdin, switched to raw mode and restored at exit) | `/dev/input/mice`, when stdin is a terminal | yes |
| `auto` | every real keyboard, discovered in `/dev/input/event*` | `/dev/input/mice` | yes |
| a path | that device node, FIFO or recorded event file, **and nothing else** | no | no |

An explicit path is a replay source, so nothing live may join it. `auto` is what
a Pi on its own console wants: press *and* release, every keyboard plugged in.
The console also delivers those keystrokes to stdin, so under `auto` the
terminal is still put in raw mode and its bytes are discarded: nothing is
echoed and nothing is left for the shell. With no readable keyboard, `auto`
falls back to the terminal.

**`qosp-gl`, a window.** GLFW's keys are translated to evdev codes and pass
through the same modifier machine; discovered keyboards and `/dev/input/mice`
are read as well.

Reading `/dev/input` needs the `input` group (`sudo usermod -aG input $USER`,
then log in again). Every open is logged once, to stderr and `/logs/host`:
`[input] keyboard: /dev/input/event1 (...)`, `[input] mouse: /dev/input/mice`,
or the reason there is none.

## What a terminal cannot say

Every terminal event is a press: there are no releases. Some keys are the same
byte and arrive as the plainer one: `^H` is Backspace, `^I` Tab, `^M` and `^J`
Enter; `^C ^Z ^\` stay signals. Bytes at or above 0x80 (UTF-8 text) name no key
and are skipped, as are mouse reports (`ESC [ <`): keycodes are control input.
There is no text-input event and no terminal mouse yet. Decoded: the whole US
layout with shift, `^A`..`^_`, Alt+key (`ESC` key), arrows, Home/End,
Insert/Delete, PgUp/PgDn, F1-F12, back-tab, and xterm's modifier parameter
(`ESC [ 1 ; 5 C` is ctrl-right, 4106).

## Testing it on arm64 Linux (the Pi's shape) from a Mac

`tools/arm64-vm/` runs Ubuntu 24.04 arm64 under QEMU (the hypervisor on Apple
Silicon, so at native speed), terminal only, with a USB keyboard and mouse the
guest sees as `/dev/input/event*`. Keys are pressed from outside the guest,
through QMP (`inject.py key h shift-h`, `rel 30 -10`, `btn left`).

```
tools/arm64-vm/vm.sh fetch        # ~230 MB Ubuntu cloud image, sha256-checked
tools/arm64-vm/vm.sh create && tools/arm64-vm/vm.sh up
tools/arm64-vm/vm.sh provision    # toolchain from apt
tools/arm64-vm/vm.sh sync
tools/arm64-vm/vm.sh ssh 'cd fprisc && make fpr && cd ../qos && ./qos.py build'
tools/arm64-vm/input-check.sh     # terminal, FPR_EVDEV=<node>, FPR_EVDEV=auto
tools/arm64-vm/vm.sh ssh 'cd qos && bash tools/gfx-gl-check.sh'   # GL window under Xvfb
```

`tests/inputcap.fpr` prints every event for eight seconds; it is the quickest
way to see what a real Pi captures.
