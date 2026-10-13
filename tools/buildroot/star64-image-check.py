#!/usr/bin/env python3
"""Validate the assembled STAR64 GPT image against its component files."""
import argparse
import hashlib
from pathlib import Path
import re
import struct
import uuid
import zlib


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def digest(stream, size):
    result = hashlib.sha256()
    while size:
        block = stream.read(min(size, 1024 * 1024))
        require(block, "unexpected end of image")
        result.update(block)
        size -= len(block)
    return result.hexdigest()


def check_firmware(images):
    spl = (images / "u-boot-spl.bin").read_bytes()
    wrapped = (images / "u-boot-spl.bin.normal.out").read_bytes()
    require(len(wrapped) == len(spl) + 1024, "incorrect SPL ROM header size")
    version, size, offset, crc = struct.unpack_from("<IIII", wrapped, 0x284)
    require(version == 0x01010101 and size == len(spl) and offset == 1024,
            "incorrect SPL ROM header fields")
    require(wrapped[1024:] == spl and crc == zlib.crc32(spl), "SPL ROM CRC mismatch")
    print("PASS SPL ROM header and CRC")

    uboot = (images / "u-boot.bin").read_bytes()
    payload = (images / "fw_payload.bin").read_bytes()
    require(payload[0x200000:0x200000 + len(uboot)] == uboot,
            "OpenSBI payload does not place U-Boot at 0x40200000")
    fields = dict(re.findall(rb"(?:^|\x00)([a-zA-Z0-9_]+)=([^\x00]*)", uboot))
    targets = fields.get(b"boot_targets", b"").split()
    require(targets and targets[0] == b"mmc1" and b"bootcmd_mmc1" in fields,
            "U-Boot does not scan STAR64 SD (MMC 1) first; Linux QEMU boot bypasses this defect")
    require(fields.get(b"bootcmd") == b"run distro_bootcmd",
            "U-Boot still uses the vendor FAT/uEnv boot path")
    print("PASS OpenSBI/U-Boot payload offset and automatic SD boot environment")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", type=Path)
    args = parser.parse_args()
    check_firmware(args.images)
    image = args.images / "sdcard.img"
    with image.open("rb") as stream:
        def header(lba):
            stream.seek(lba * 512)
            raw = bytearray(stream.read(512))
            require(raw[:8] == b"EFI PART", "missing GPT signature")
            length, crc = struct.unpack_from("<II", raw, 12)
            require(92 <= length <= 512, "invalid GPT header size")
            struct.pack_into("<I", raw, 16, 0)
            require(zlib.crc32(raw[:length]) == crc, "GPT header CRC mismatch")
            current, other = struct.unpack_from("<QQ", raw, 24)
            require(current == lba, "incorrect GPT header location")
            entries_lba, count, entry_size, entries_crc = struct.unpack_from("<QIII", raw, 72)
            require(count <= 4096 and entry_size == 128, "unexpected GPT entry layout")
            stream.seek(entries_lba * 512)
            entries = stream.read(count * entry_size)
            require(zlib.crc32(entries) == entries_crc, "GPT partition table CRC mismatch")
            return other, entries

        backup_lba, entries = header(1)
        require((backup_lba + 1) * 512 == image.stat().st_size, "GPT backup is not at image end")
        primary_lba, backup_entries = header(backup_lba)
        require(primary_lba == 1 and entries == backup_entries, "GPT copies differ")
        parts = [entries[i:i + 128] for i in range(0, len(entries), 128)
                 if entries[i:i + 16] != bytes(16)]
        require(len(parts) == 3, "expected SPL, U-Boot, and rootfs partitions")
        names = ["u-boot-spl.bin.normal.out", "opensbi_uboot_payload.img", "rootfs.ext4"]
        types = ["2e54b353-1271-4842-806f-e436d6af6985",
                 "5b193300-fc78-40cd-8002-e86c45580b47",
                 "0fc63daf-8483-4772-8e79-3d69d8477de4"]
        last_end = 33 * 512
        for index, (entry, name, expected_type) in enumerate(zip(parts, names, types)):
            require(str(uuid.UUID(bytes_le=entry[:16])) == expected_type, f"wrong partition type: {name}")
            first, last = struct.unpack_from("<QQ", entry, 32)
            offset, capacity = first * 512, (last - first + 1) * 512
            require(offset >= last_end and last < backup_lba, "overlapping or out-of-range partition")
            last_end = (last + 1) * 512
            if index < 2:
                require(offset == (2 if index == 0 else 4) * 1024 * 1024, "incorrect firmware offset")
            component = args.images / name
            size = component.stat().st_size
            require(size <= capacity, f"partition too small: {name}")
            stream.seek(offset)
            actual = digest(stream, size)
            with component.open("rb") as source:
                require(actual == digest(source, size), f"embedded component mismatch: {name}")
            if index == 2:
                require(str(uuid.UUID(bytes_le=entry[16:32])) == "2c28917b-0a33-4d61-a825-f3e9e7bcb805", "wrong root PARTUUID")
                stream.seek(offset + 1024 + 56)
                require(stream.read(2) == b"\x53\xef", "missing ext4 superblock")
                stream.seek(offset + 1024 + 92)
                compat, incompat = struct.unpack("<II", stream.read(8))
                require(not (compat & 0x1000), "ext4 orphan_file is incompatible with the vendor kernel")
                require(not (incompat & (0x80 | 0x2000)), "ext4 64bit/metadata_csum_seed is incompatible with the vendor boot path")
            print(f"PASS {name}: offset={offset} bytes={size} sha256={actual}")
        stream.seek(0)
        print(f"PASS GPT primary/backup; sdcard.img sha256={digest(stream, image.stat().st_size)}")


if __name__ == "__main__":
    main()
