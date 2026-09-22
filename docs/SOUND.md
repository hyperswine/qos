# Sound: the procedural synth tier (qosp v7)

QOS Portable plays sound the way it draws: from integers the program
builds, through one table-dispatched call, with the host owning the
device.  No samples, no asset files.

    sndPlay (wave, f0, f1, ms, vol, delay)   -> voice slot, -1 = dropped

| field | meaning                                                   |
|-------|-----------------------------------------------------------|
| wave  | 0 sine, 1 square, 2 triangle, 3 noise, 4 saw              |
| f0 f1 | start and end frequency in Hz, swept linearly over `ms`   |
| ms    | duration                                                  |
| vol   | 0..1000, milli full-scale                                 |
| delay | ms before the tone starts (a riff = several calls, offset)|

Every voice carries a 2 ms attack and a linear release over its last
40%; 24 voices mix additively through a soft clip at 44.1 kHz mono.
The mixer is one background thread in the host (`hal/unix/snd_raw.c`),
started by the first call, so a program that never makes a sound never
touches audio.

## Backends

Picked by `qos/Makefile` at build time:

* **ALSA** on Linux when `libasound2-dev` is installed (`pkg-config
  alsa`); without it the build still succeeds and the host is silent.
* **AudioQueue** on macOS (AudioToolbox), pull-driven: the queue's
  callback runs the mixer.
* **The dump**, always: `FPR_SND_DUMP=<path>` writes the mix as a WAV
  while it plays, wall-clock paced when no device is open.  That is how
  a headless run under Xvfb proves what it sounded like
  (`qos/tests-host/terra2-check.sh` asserts the length, the number of
  distinct bursts and the share of silence).

The host logs which it got, once: `[snd] ALSA default device`,
`[snd] no ALSA device (silent)`, `[snd] dumping the mix to ...`.

## The chain

`fpr` types `sndPlay` (Infer.hs); the app-side shim
(`qos/appside/hal.c`, `h_sndPlay`) reads the 6-tuple and calls the
table's `snd_play`, the v7 slot appended to `qos_hal_t`
(`qos/appside/qos_abi.h`).  `QOS_ABI_VERSION` is 7: an app built after
this refuses a pre-v7 host at the gate, as every ABI addition does.

## The music channel (v9)

    sndMusic path vol     -> 1 playing, 0 off, -1 not found / not decodable

One MP3, decoded by the host as it plays (hal/unix/minimp3.h, public
domain, vendored), channels averaged to mono, resampled to 44.1 kHz,
faded in over a second and looped under the effects at vol/1000.  An
empty path or vol 0 stops it.  The path resolves as given, then under
`FPR_ASSETS`, then beside the .qa -- so a bundle carries the track next
to the program: a `#: music <file>` directive names it, `qos.py run`
points FPR_ASSETS at its directory and `qos.py pack` copies it into the
bundle.  `FPR_SND_MUSIC=0` mutes the channel, which is how the scripted
game's WAV assertions (bursts over silence) still hold; `tests/music.fpr`
plays three seconds of the track into a dump the check reads back, so the
decoder is proven on its own.  Terra II starts
models/music/Skyward_Little_World.mp3 with the game and M toggles it.

## Cues as data: mods/sfx.fpr

A riff is a list of tones; `Sfx.play riff` plays one, `Sfx.playAll`
a frame's worth.  The module carries the vocabulary a card game needs:
`cursor`, `pick`, `cancel`, `refuse`, `toggle` (the UI); `call`,
`attack`, `hit`, `kill`, `hqHit`, `shot`, `charge`, `ambush`,
`intercept`, `move` (the table); `rifle` (four cracks), `cannon` (a boom with a deep sine under it),
`yourTurn`, `enemyTurn`, `turnOver` (the clock); `open`, `close`,
`victory`, `defeat` (the frame).  Terra II
queues cues on its model (`cue m Sfx.hit`) and the tick plays them,
the same way its transcript is printed -- so a replayed game sounds
the same every run.
