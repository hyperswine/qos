/* qa.h -- host-side reader for the .qa archive (docs/QA-FORMAT.md, QAR2).
 *
 * The C analogue of System.qa's FPRISC-side parser: same QAR2 byte
 * layout, same minimal-TOML manifest subset, same launch rules
 * (required permissions are compulsory; optional denials just aren't
 * granted).  Unknown sections are ignored by design.  qa_load also
 * verifies the LOAD section's sha256 against the IMAGE bytes -- a
 * corrupt archive is refused before a single byte is copied. */
#ifndef QOS_QA_H
#define QOS_QA_H

#include <stdint.h>

/* a permission's url and mode are owned strings of whatever length the
 * manifest gave: a capability path cut to fit a buffer would be a
 * DIFFERENT, possibly broader, grant */
typedef struct {
  char *url;
  char *mode; /* read / write / readwrite */
  int required;  /* 1 = [permissions.required], 0 = optional */
  int granted;   /* filled by the permission gate */
} qa_perm_t;

typedef struct {
  /* raw archive (owned by the caller; views below point into it) */
  unsigned char *bytes;
  uint64_t len;
  /* sections */
  const unsigned char *manifest;
  uint64_t manifest_len;
  const unsigned char *load; /* the six-number loader contract (text) */
  uint64_t load_len;
  const unsigned char *img;  /* the flat memory image */
  uint64_t img_len;
  /* parsed manifest fields */
  char name[64];
  char id[64];
  char load_mode[16]; /* "process" is the only mode qosp runs */
  char abi[24];       /* "<QOS_ABI_VERSION>.<codegenRev>" or empty (pre-stamp) */
  char shell[72];     /* plugin matched-set stamp: the LOAD sha of the shell
                       * image it linked against; empty = pre-stamp */
  qa_perm_t *perms; /* grows by doubling: a manifest may ask for any number */
  int nperms, perms_cap;
} qa_t;

/* parse an in-memory archive (the syscall tag-4 path: the caller hands
 * the .qa BYTES it read off the disk).  Takes its own copy -- the
 * caller's buffer owes nothing after the call.  0 ok, -1 + stderr. */
int qa_parse(const unsigned char *bytes, uint64_t len, qa_t *out);
void qa_free(qa_t *qa);


#endif
