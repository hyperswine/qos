/* sd_spi.h -- a BLOCK class driver for an SD card on Simple-Risc's SPI port
 * (Simple-Risc boards/tangnano20k/c/sd.c), as used by the Spectre images.
 *
 * The volume is a window of the card: `pages` 4 KiB pages starting at sector
 * `lba0` (8 sectors a page). An image declares one sd_spi_t, a setup function
 * that calls sd_spi_setup on it, and a device table entry:
 *
 *   static sd_spi_t disk = {.lba0 = 131072, .pages = 64};
 *   static void disk_setup(void) { sd_spi_setup(&disk); }
 *   {"blk", {T_DEVICE, 0, 0}, disk_setup, NULL,
 *    .cls = FPR_DEV_BLOCK, .ops = &sd_spi_ops, .state = &disk}
 */
#ifndef QOS_SD_SPI_H
#define QOS_SD_SPI_H
#include "sd.h"
#include "block.h"

typedef struct {
  uint32_t lba0;      /* first sector of the volume */
  uint32_t pages;     /* pages in the volume */
  uint8_t format;     /* zero the whole window at setup */
  uint8_t read_only;  /* refuse writes */
  uint8_t ready;
  sd_card_t card;
} sd_spi_t;

extern const qos_block_ops sd_spi_ops;
void sd_spi_setup(sd_spi_t *s);
#endif
