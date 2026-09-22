# Terra II music

Terra II uses **Skyward, Little World** (`Skyward_Little_World.mp3`), an original
NeoMusic instrumental: 144 BPM, D major / B minor, approximately 95 seconds.
It is synthesized from Haskell notes, patches, and percussion without samples.

The reproducible score lives in the sibling repository:
`HaskPlayground/app/terra-bgm/Main.hs`. That directory also contains `master.py`
and full arrangement/rebuild notes. From HaskPlayground:

```sh
stack run terra-bgm -- --check
stack run terra-bgm -- /tmp/skyward-raw.wav
python3 app/terra-bgm/master.py /tmp/skyward-raw.wav ../qos/models/music/Skyward_Little_World.mp3
```

The game directive and `musicFile` in `programs/terra2.fpr` select the track.
`tests/music.fpr` and the Terra II host check use the same asset. `qos.py run`
resolves it through FPR_ASSETS, and packaging copies the declared music asset.
The existing volume setting and M toggle are unchanged.

The MP3 is stereo 44.1 kHz / 192 kb/s, mastered around -15 LUFS; QOS folds it to
mono. It has a resolved fading ending for repetition, not a seamless loop.
`Sunrise_Over_The_Spire.mp3` is preserved as the previous soundtrack.
