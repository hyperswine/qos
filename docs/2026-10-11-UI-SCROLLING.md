# Files and Logs vertical panes, 2026-10-11

Main's Files and Logs shortcuts passed an entire newline-delimited listing
or joined log snapshot to one proportional `Lbl`. Scene2d's label is a single
line: newline bytes became fallback glyphs and the natural width pushed the
card past the display. The shortcut also ignored navigation keys.

Both shortcuts now use `scrolltext.fpr`: newline splitting (including CRLF
and blank lines), word wrapping using the renderer's font advances, hard
wrapping for long unbroken URLs, and a fixed nine-row viewport. Only visible
rows become text entities; the pane is clipped and the surrounding card has
an explicit width. A scrollbar and visible line range describe the position.

Up/Down scrolls one row, Page Up/Down scrolls nine, Home/End reaches the
first/last page, and clicking the scrollbar chooses a position. Reopening
resets the offset. Desktop wheel events are handled; the existing Pi raw
mouse backend emits movement/clicks, so keyboard or scrollbar navigation is
available there. Logs remains a live normal-severity ring, newest first.
This changes the Main shortcuts; the separately installed Browser/Logs/Disk
plugins retain their existing appkit layouts and archive ABI.

## Validation and deployment

- Local macOS wrapping and shell-control fixtures passed. Checks include
  explicit line breaks, blank/empty content, proportional widths, long
  tokens, bounded row windows, scrolling limits, paging, wheel dispatch
  and scrollbar clicks.
- The real GL runner passed two boots in the ARM64 Linux VM. Screenshot
  assertions check text in separate vertical row bands, Files page-down,
  Files Home returning to identical pixels, and Logs End changing the view.
  Existing onboard Clock/Browser, refused archives and graceful exits also
  passed. Files/Logs captures were visually inspected.
- Both fixtures passed on the physical Pi with four workers and the installed
  Portable host. An isolated V3D/EGL run over a copy of Main's disk passed
  Files/Logs navigation and screenshot checks, then drained storage and
  exited 0 without timeout or forced kill (558 frames, 22.0 seconds).
  Physical GPU captures were visually inspected.

The new Main archive was installed after the production service stopped
with `shutdown complete`. The normal service restarted with the real Logitech
keyboard and DRM scanout at 1024x600, rendering the centered 960x600 canvas.
The installed archive SHA-256 is
`4612ba31494c0a41d907dc99ce96723889039fdaa601f91e2dafaebcdbf4091b`.
The Portable host, onboard plugin archives and durable Main disk were retained.
The disk hash remained
`62c67b5f7e685a91d1469194834d90a522df3ef883e04e9b83da7de450220d81`.

The installed archive then passed Files page-down/Home and Logs End checks
through injected, SYN_REPORT-framed events on the detected keyboard's actual
`/dev/input/event2`, with normal DRM scanout. Files' top and bottom pixels
matched the isolated GPU captures; Home restored identical top pixels.
The final production state was PID 14840, zero automatic restarts, with
Files left open. This verifies the normal input path using injection, rather
than claiming a person physically pressed the keys. The first injection
attempt omitted SYN_REPORT framing and produced no screenshot; the corrected
attempt passed without restarting QOS.

Rollback copies are `/var/lib/qosp/deployment-ui-scroll-20261011/app.qa.before`
and `Main.disk.before`. Roll back the archive with the service stopped;
restoring the disk is a separate action that would discard subsequent state.
Raw private build/test/deployment evidence is under
`.qos/pi4/validation/ui-scroll/` on the Mac and `ui-scroll-v1/` in the build VM.

These checks establish layout, navigation and plugin compatibility for the
tested screens. They do not establish interactive memory endurance or add
scrolling to every plugin.
