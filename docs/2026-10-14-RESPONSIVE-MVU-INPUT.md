# Responsive recursive MVU and input - 2026-10-14

Main now boots at the display's surface size. Its viewport, keyboard focus,
hover, pointer capture, wheel remainder and cached panes belong to the shell
model. The four onboard apps own the same facts in their child models.
Updates and views use ordinary named functions and explicit messages; no
application hooks or callback registry were added. The existing MApp/Sys.loop
turn adapters and platform graphics/input mechanisms remain.

## Geometry and composition

`programs/mods/shelllayout.fpr` computes a layout from the logical surface
size. Rendering and hit testing consume that same geometry. A tile grid uses
one to four columns and one to three rows, with capacity/page count derived
from the viewport. Selection survives resizing and its page is recomputed. Geometry uses the
same rounded component sizes as the renderer, including at fractional scales.
Text and spacing scale from 1.0 to 1.5; smaller surfaces reduce columns and
margins. The functional geometry set covers 320x480, 640x480, 960x600,
1024x600, 1280x720 and 1920x1080. Very small surfaces are clipped; they are not
claimed as a useful user interface. The coordinate transport supports up to
8192x8192 logical pixels.

`scrolltext.fpr` has viewport-aware wrapping, visible-row limits, offsets,
thumbs and drawing. Pane models retain their raw successful text so resize
can rewrap it without another service read. Scroll offsets are clamped;
paragraph-level anchoring across reflow is not implemented. `appview.fpr`
provides a pure child layout shared by app view and input handling. Clock,
Logs, Browser and Disk use readable proportional text and cached scene data.
Disk's view identifies its data as storage statistics. The built-in Clock
also caches time outside rendering; no shell view now performs service I/O.

The app wire is `qos.app-session/2`: Resize, Pointer, Wheel, Focus and Cancel
are data messages. The session owner remembers the latest child viewport
before launch, forwards later changes, and retains it across Close/reopen.
Main and all four onboard archives must be rebuilt together. Existing writable
disks need their archive records updated explicitly; rebuilding Main alone
cannot update old app records.

## Focus and input policy in FP-RISC

- Arrows navigate by the current grid's column count. Home/End select the
  first/last tile; Page Up/Down change pages. Tab and Shift-Tab move keyboard
  focus between tile/content and footer controls. Enter/Space activate the
  focused control. Pagination controls retain focus after activation.
- Hover does not steal keyboard selection. A primary press captures its hit
  target; release activates only over the same target. Resize, focus loss,
  input cancellation and keyboard navigation revoke pending activation.
  Held buttons and repeated launch keys cannot repeatedly launch a tile. Home performs navigation
  and cleanup; only an explicit P request writes a snapshot.
- Apps receive pointer facts inside their content area and during an owned
  drag. Browser resolves a row only on a matching release. Dragging a list or
  pane scrolls cached rows and cancels row activation. Scrollbar drag uses the
  same rectangle and metrics as the displayed thumb.
- Fractional wheel values accumulate in the model. A small trackpad delta is
  retained until it makes a whole row. Wheel/key input follows content focus;
  Refresh/Retry and Home remain explicit controls. App read deadlines, session
  generations, bounded Close and storage-drain behavior remain in force.
- Losing focus clears capture/buttons and informs the child app. Keys and
  pointer actions are ignored until focus returns. Shared Graphics sessions
  learn gain/loss once through their polling capability, including when the
  session is no longer focused. F1 cycles on press, not on release or repeat.

`shellinput.fpr` is a pure adapter into the existing MVU event vocabulary.
Pointer coordinates use a fixed stride, so queued positions are not decoded
with a different width after resize. This avoids changing the pinned SDK's
public MVU wire. Raw input is consumed by one persistent adapter actor using
`Sys.loop` rather than allocating an actor per event.

## Platform mechanisms and boundaries

The desktop host reports logical window size and focus facts, resizes its
existing offscreen attachments, and clears obsolete native input on focus
loss. Native keys use one decoder in arrival order; ASCII character events do
not enqueue a second activation. A Retina window presents the logical surface
through the existing framebuffer blit. Actual monitor hotplug/DRM mode changes
are not implemented by this slice.

The Unix pointer tier prefers evdev relative pointers/wheels and absolute
single-contact touch, including primary slot zero on type-B devices. Reports
are assembled through SYN_REPORT, with partial bytes retained per device.
Coordinates are normalized at the driver boundary and mapped to the current
viewport in FP-RISC. SYN_DROPPED or a device read failure cancels capture.
Secondary touch contacts cannot activate the primary pointer. This is not
multi-touch or pinch recognition. Input-device rediscovery after hotplug is a
follow-up; legacy `/dev/input/mice` remains a fallback when evdev sources are
unavailable.

`FPR_POINTER_EVDEV` selects an explicit pointer stream, including deterministic
replay. An explicit `FPR_EVDEV` keyboard replay disables live pointer discovery
and native-window input unless a pointer stream is also supplied. Viewport
changes remain available. Replay acceptance does not prove delivery from a
physical touchscreen or every mouse model.

## Validation

The standard GUI and Pi checks include `tests/shelllayout.fpr` plus the existing
app-session, pane and lifecycle checks. Native input checks are
`qos/tests-host/pointer-check.sh` and `gfx-input-check.sh`. The GUI runner also
boots real GL at the Pi-panel size, 720p and 1080p and exercises primary touch
replay, cancelled taps, child views and keyboard focus.

### Executed acceptance, 2026-10-14

Built from QOS base `b6031f5ce396870fd7f83f17339d345d09d4073e` with the
unchanged, clean FP-RISC SDK pin
`aee3e962c8c3f2d6d4967a35e035856258de5ce6`.

- The complete host GUI runner passed: layout, app-session and app-job
  contracts with one/four workers; native pointer report decoding; actual GL
  resize, framebuffer completeness, focus and modifier ordering; two Main
  boots, all four app sessions, reopen/Close, scrolling, refusal and recovery.
  Graphics death and a live render deadline still drain storage before exit.
  Real GL viewport runs passed at 1024x600, 1280x720 and 1920x1080, including
  primary touch replay, cancelled taps and keyboard focus. Captured child
  panes and home grids were visually inspected.
- Shared graphics/focus and graphics-memory contracts passed with one/four
  workers on the host and physical Pi. The memory contract draws 100,000
  frames and checks retained memory below 2 MiB. App-session, app-job and
  layout contracts also passed on the physical Pi with one/four workers.
- Isolated physical Pi Main runs passed at the three sizes below, each with
  pointer replay/cancellation, repeated Files/Logs/Browser navigation, normal
  quit and a separate 30-second SIGTERM boot. Every exit was zero, without
  timeout or kill escalation. The 1024x600 run uses `programs/main.fpr`.
  The other two use `tests/layoutpi.fpr`, which calls the same normal shell
  with a private screenshot tag. Their GPU captures were inspected.

| Viewport | Navigation cycles | Main run seconds | Sampled RSS first/last KiB |
| --- | ---: | ---: | ---: |
| 1024x600 | 4 | 87.34 | 54868 / 61876 |
| 1280x720 | 3 | 73.95 | 56368 / 60896 |
| 1920x1080 | 3 | 72.30 | 58080 / 64204 |

These Pi runs use EGL/V3D offscreen surfaces on the physical board. They do
not replace the installed GUI or prove physical display scanout or touchscreen
delivery. Its boot ID, PID 279 and restart count zero remained unchanged.
CPU frequency stayed at 600 MHz. These are short acceptance runs, not a
memory plateau or frame/input latency baseline. CPU policy, longer residency
profiling and frame/input timing are the next slice.

Artifact SHA-256:

| Artifact | SHA-256 |
| --- | --- |
| Matching production-flags Pi host | `2931ed9c24ea24b596318466eb1fc84b49d51a0c11c226e4d9b0c99321beda01` |
| Normal Main archive | `675a5efb1c41d802bd06d58ffe86753516348aeb16cd78a685a32284f201d6f8` |
| Private-tag viewport archive | `6a3c779eb4522578e8d4134a177637d5a79bd87635f8e340c8ad465ca05ccb1f` |
| Matching four-app seed | `ae89a15a2e4521cc6dd8dd1836f6d6f569697f4f6241d845403aced18e0db525` |

Local evidence is retained under `.qos/validation/gui-layout-20261014/`,
including host screenshots/logs, Pi metadata and screenshots, native source
hashes and matching host build logs. No installed Pi files were replaced.
