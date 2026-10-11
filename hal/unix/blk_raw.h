/* blk_raw.h -- the hosted disk tier: one host FILE as an array of
 * 4 KiB pages.  hal/virt/blk.c's contract verbatim: the disk is pages,
 * read and written whole, policy-free -- no log, no records, no index,
 * no files.  Every one of those is POLICY and lives in FPRISC
 * (mods/qlog.fpr, diskfs.fpr); this tier will happily read or
 * overwrite any page, and that the filesystem above only ever APPENDS
 * is the filesystem's discipline, not the driver's.
 *
 * Raw-core discipline (net_raw/gfx_raw/evdev_raw): plain C, no V
 * values, one implementation callable from a HAL table entry (qosp)
 * or any future dispatch alike. */
#ifndef QOS_BLK_RAW_H
#define QOS_BLK_RAW_H

#include <stdint.h>

#define QOS_BLK_PAGE 4096u

/* Open the backing file, creating it if absent: $FPR_DISK names the
 * path (default "qosp.disk" in the working directory); a fresh file
 * is created zero-filled at $FPR_DISK_MB MiB (default 8 -- the same
 * size native-run seeds disk.img at).  A zero page 0 is simply an
 * unformatted superblock, which qlog.fpr's `ensure` formats on first
 * touch: creation is the HAL's job, formatting is the filesystem's,
 * the same split a blank virtio disk has on virt.
 * Idempotent; failure is not fatal here -- it surfaces as 0 pages,
 * the honest no-disk state system.fpr already degrades on. */
void qos_blkraw_setup(void);

int64_t qos_blkraw_pages(void); /* capacity in 4 KiB pages; 0 = no disk */

/* read page -> exactly QOS_BLK_PAGE bytes into dst; 0, or -1 when the
 * page is out of range / no disk / IO error */
int64_t qos_blkraw_read(uint64_t page, char *dst);

/* write src (len <= QOS_BLK_PAGE, zero-padded to a whole page) to
 * page; returns len accepted, or -1 out of range / oversize / error */
int64_t qos_blkraw_write(uint64_t page, const char *src, uint64_t len);

/* Flush data/file metadata and the backing file's directory entry.  This
 * synchronous mechanism returns 0 on success, -1 on an unavailable disk or
 * any host sync error.  Actor callers submit QOS_BLK_FLUSH below instead. */
int64_t qos_blkraw_flush(void);

enum { QOS_BLK_READ = 0, QOS_BLK_WRITE = 1, QOS_BLK_FLUSH = 2 };

/* Worker-owned buffers; release abandons a pending job safely. At most 64
 * queued+running jobs are admitted, including abandoned jobs. All jobs use
 * one FIFO worker.  A FLUSH (page=0, src=NULL, len=0) completes after every
 * previously admitted read/write and before any later job.  Its result is
 * 0 or -1; dst is ignored.  Completion only says what the host fsync calls
 * guarantee, not that arbitrary hardware has been power-loss qualified. */
void *qos_blkraw_submit(uint64_t page, const char *src, uint64_t len, int operation);
int qos_blkraw_done(void *job);
int64_t qos_blkraw_result(void *job, char *dst);
void qos_blkraw_release(void *job);

#endif /* QOS_BLK_RAW_H */
