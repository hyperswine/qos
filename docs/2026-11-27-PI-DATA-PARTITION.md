# Pi 4B: the rest of the SD card becomes /data (27 November)

Kind: delivery record. The installed Pi 4B used 544 MiB of a 58 GB card (boot
32 MiB, root 512 MiB at 83%), because the Buildroot image has a fixed size.

## On the installed Pi (by hand)

- **Partition:** partition 3 was added from sector 1116160 to the end of the card (57.4 GB),
  with a reboot. It was formatted ext4, labelled `data`, using e2fsprogs from an arm64 Debian
  container, since BusyBox makes only ext2.
- **Mount:** it is at `/data` through `/etc/fstab`.
- **State:** `/var/lib/qosp` was copied there (90 files, checksums equal) and replaced by a
  symlink to `/data/qosp`. Main came back after a reboot with `/data/qosp/Main.disk` open.
- **Space:** root went from 83% to 34% used (297 MiB free); `/data` has 53.1 GB free.
- **Backup:** the MBR sector from before the change is
  `.qos/pi4/image-backups/pi4b-before-guishell-20261127/mbr-before-p3.bin`.

## In the image (so a new card does it by itself)

`S05qosp-data`, `post-build.sol` fstab lines and `BR2_PACKAGE_E2FSPROGS=y`; the
behaviour is described in `tools/buildroot/README.md` ("The data partition").
It bind-mounts the state rather than linking it, as the package requires.

**TODO before relying on it: test with a fresh SD card.** No spare card was
available. The README section lists what to check. Only the script's
primitives were exercised on the installed Pi.
