/* tty_raw.c (posix) -- the TERMINAL input tier: fpr_g_inputPoll for
 * images built WITHOUT the GL stack (GFX=1 links gfx_fpr.c's poll
 * instead; the two are never in the same image -- see the Makefile).
 *
 * Source priority (qos_headless_poll, below) mirrors the gfx tier's:
 *
 *   1. FPR_EVDEV set  -> qos_evdev_poll (evdev_raw.c): a kbdsim FIFO,
 *      a pre-baked event file, or a real /dev/input/eventN on Linux.
 *      Deterministic replay and the simulated keyboard keep working
 *      exactly as they do under GFX=1 / qosp.
 *   2. otherwise      -> RAW stdin.  If stdin is a tty it is switched
 *      to non-canonical no-echo mode (VMIN=0/VTIME=0: reads never
 *      block, matching the poll contract) and restored at exit and on
 *      SIGINT/SIGTERM; a pipe works too (tests feed bytes that way).
 *
 *   3. FPR_EVDEV=auto -> every real keyboard, discovered, plus the mouse
 *      (mice_raw.c): what a Pi on its own console wants.
 *
 * Bytes are decoded to LINUX INPUT-EVENT KEYCODES -- the same codes,
 * with the same modifier bias, the evdev tier delivers -- so a program's
 * key map works unchanged over either source.  Terminals only report
 * presses, so every event is (4, code, 1); the press/release distinction
 * is what the evdev tier buys over this one.
 */
/* QOSP_HOST: compiled into the qosp HOST binary (haltab input tier) --
 * everything here is plain posix EXCEPT the fpr_g_inputPoll wrapper at
 * the bottom, which needs the app runtime.  The guard keeps ONE
 * implementation of the decode/raw-mode/winch discipline for both
 * dispatch worlds, per the haltab.c essay. */
#ifndef QOSP_HOST
#include "fpr.h"
#endif
#include <stdint.h>

#include <fcntl.h>
#include <signal.h>
#include <sys/ioctl.h>
#include <stdlib.h>
#include <string.h>
#include <termios.h>
#include <unistd.h>

#include "evdev_raw.h" /* qos_evdev_poll, qos_evdev_sources, qos_mice_poll */

/* ---- raw-mode lifecycle --------------------------------------------- */

static int tty_state; /* 0 untried, 1 raw, -1 not a tty (pipe: still read) */
static struct termios tty_saved;

/* ---- terminal size ---------------------------------------------------
 * Reported through the SAME poll as keys, as kind 5: (5, cols, rows).
 * Dirty at startup (so a program learns its terminal on the first poll)
 * and again on every SIGWINCH; a poll with the flag set reports the
 * size BEFORE any queued key.  Size is read from whichever of stdout/
 * stdin is a tty -- a fully piped run (both redirected) never sees a
 * kind-5 event, so replay-style tests keep their exact event stream,
 * and the FPR_EVDEV tier is untouched (no sizes there either). */
static volatile sig_atomic_t win_dirty = 1;
static void tty_winch(int s) { (void)s; win_dirty = 1; }

static int win_poll(int64_t* kind, int64_t* a, int64_t* c) {
  struct winsize ws;
  int fd;
  if (!win_dirty) return 0;
  win_dirty = 0;
  fd = isatty(1) ? 1 : (isatty(0) ? 0 : -1);
  if (fd < 0 || ioctl(fd, TIOCGWINSZ, &ws)) return 0;
  if (!ws.ws_col || !ws.ws_row) return 0;
  *kind = 5; *a = (int64_t)ws.ws_col; *c = (int64_t)ws.ws_row;
  return 1;
}

static void tty_restore(void) {
  if (tty_state == 1) tcsetattr(0, TCSAFLUSH, &tty_saved);
}
static void tty_sig(int s) {
  tty_restore();
  signal(s, SIG_DFL);
  raise(s);
}
static void tty_init(void) {
  if (tty_state) return;
  signal(SIGWINCH, tty_winch);
  if (!isatty(0)) {
    /* a pipe: VMIN/VTIME don't apply, so an empty read would BLOCK the
     * frame loop -- make it nonblocking (the tty path gets the same
     * never-block contract from VMIN=0/VTIME=0) */
    fcntl(0, F_SETFL, fcntl(0, F_GETFL, 0) | O_NONBLOCK);
    tty_state = -1;
    return;
  }
  if (tcgetattr(0, &tty_saved)) { tty_state = -1; return; }
  struct termios t = tty_saved;
  t.c_lflag &= (tcflag_t)~(ICANON | ECHO); /* ISIG stays: ^C still works */
  t.c_cc[VMIN] = 0;
  t.c_cc[VTIME] = 0;
  if (tcsetattr(0, TCSAFLUSH, &t)) { tty_state = -1; return; }
  atexit(tty_restore);
  signal(SIGINT, tty_sig);
  signal(SIGTERM, tty_sig);
  tty_state = 1;
}

/* ---- byte queue + decode -------------------------------------------- */

static unsigned char q[64]; /* one read's worth; the rest waits in the tty */
static size_t qn;
static int esc_stale; /* an unfinished escape seen last poll */

static void topup(void) {
  if (qn < sizeof q) {
    ssize_t n = read(0, q + qn, sizeof q - qn);
    if (n > 0) qn += (size_t)n;
  }
}
static void shift(size_t k) {
  memmove(q, q + k, qn - k);
  qn -= k;
}

/* The WHOLE keyboard, not a demo's keys: every byte a US-layout terminal
 * sends is named by the Linux input-event code of the key that makes it,
 * with the evdev tier's modifier bias (evdev_raw.c decode_key: shift +1000,
 * ctrl +4000, alt +8000) -- so `H` is 1035 here exactly as it is from a
 * real keyboard, and a program's key map works over either source.  This
 * used to know seventeen keys and silently drop the rest, Enter and Escape
 * included.
 *
 * What a terminal cannot say stays unsaid: releases (every event is a
 * press), and the keys it folds together -- ^H is Backspace, ^I Tab, ^M and
 * ^J Enter; ^C ^Z ^\ are signals (ISIG stays on).  Bytes >= 0x80 (UTF-8
 * text) name no key and are skipped: keycodes are control input, not text. */
#define B_SHIFT 1000
#define B_CTRL 4000
#define B_ALT 8000
static const char* const row_plain[4] = {"1234567890-=", "qwertyuiop[]", "asdfghjkl;'`", "\\zxcvbnm,./"};
static const char* const row_shift[4] = {"!@#$%^&*()_+", "QWERTYUIOP{}", "ASDFGHJKL:\"~", "|ZXCVBNM<>?"};
static const int row_base[4] = {2, 16, 30, 43};

static int key_of_byte(unsigned char b) {
  if (b == ' ') return 57;
  if (b == 0) return 57 + B_CTRL;             /* ^Space */
  if (b == 9) return 15;                      /* Tab */
  if (b == 10 || b == 13) return 28;          /* Enter */
  if (b == 8 || b == 127) return 14;          /* Backspace */
  if (b == 27) return 1;                      /* Escape */
  if (b < 27) return key_of_byte((unsigned char)('a' + b - 1)) + B_CTRL;
  if (b < 32) return key_of_byte((unsigned char)"\\]6-"[b - 28]) + B_CTRL;
  if (b >= 127) return 0;
  for (int r = 0; r < 4; r++) {
    const char* at = strchr(row_plain[r], b);
    if (at) return row_base[r] + (int)(at - row_plain[r]);
    at = strchr(row_shift[r], b);
    if (at) return row_base[r] + (int)(at - row_shift[r]) + B_SHIFT;
  }
  return 0;
}

/* xterm's modifier parameter: 1 + (1 shift | 2 alt | 4 ctrl) */
static int mod_bias(int m) {
  if (m < 2) return 0;
  m -= 1;
  return (m & 1 ? B_SHIFT : 0) + (m & 2 ? B_ALT : 0) + (m & 4 ? B_CTRL : 0);
}

static int key_of_final(unsigned char f) { /* CSI/SS3 letter finals */
  switch (f) {
  case 'A': return 103; case 'B': return 108; case 'C': return 106; case 'D': return 105;
  case 'H': return 102; case 'F': return 107;                     /* Home End */
  case 'P': return 59; case 'Q': return 60; case 'R': return 61; case 'S': return 62; /* F1-F4 */
  case 'Z': return 15 + B_SHIFT;                                  /* back-tab */
  default: return 0;
  }
}
static int key_of_tilde(int n) { /* CSI n ~ */
  static const int f[] = {59, 60, 61, 62, 63, 0, 64, 65, 66, 67, 68, 0, 87, 88}; /* 11..24 */
  switch (n) {
  case 1: case 7: return 102; case 4: case 8: return 107;         /* Home End */
  case 2: return 110; case 3: return 111;                         /* Insert Delete */
  case 5: return 104; case 6: return 109;                         /* PgUp PgDn */
  default: return (n >= 11 && n <= 24) ? f[n - 11] : 0;
  }
}

/* An escape sequence at q[0].  >0: a key (consumed).  0: consumed, no key.
 * -1: incomplete -- wait for the rest. */
static int escape(void) {
  if (qn == 1) return -1;
  if (q[1] == 'O') { /* SS3: application-mode arrows, F1-F4 */
    if (qn < 3) return -1;
    int code = key_of_final(q[2]);
    shift(3);
    return code;
  }
  if (q[1] != '[') { /* ESC + key = Alt+key; ESC ESC = Escape, then the rest */
    if (q[1] == 27) { shift(1); return 1; }
    int code = key_of_byte(q[1]);
    shift(2);
    return code ? code + B_ALT : 0;
  }
  /* CSI: parameter bytes 0x30-0x3f, intermediates 0x20-0x2f, one final */
  size_t i = 2;
  int p[2] = {0, 0}, np = 0, plain = 1;
  for (; i < qn && q[i] >= 0x20 && q[i] <= 0x3f; i++) {
    if (q[i] >= '0' && q[i] <= '9') { if (np < 2) p[np] = p[np] * 10 + (q[i] - '0'); }
    else if (q[i] == ';') np++;
    else plain = 0; /* private markers (`<` mouse reports, `?` replies): not keys */
  }
  if (i >= qn) return -1;
  unsigned char f = q[i];
  shift(i + 1);
  if (!plain) return 0;
  int code = f == '~' ? key_of_tilde(p[0]) : key_of_final(f);
  return code ? code + mod_bias(p[1]) : 0;
}

/* one key per poll, the evdev tier's record discipline */
int qos_tty_poll(int64_t* kind, int64_t* a, int64_t* c) {
  tty_init();
  if (win_poll(kind, a, c)) return 1;
  topup();
  while (qn) {
    int code;
    if (q[0] == 27) {
      code = escape();
      if (code < 0) {
        /* maybe split across reads: give it one poll to complete.  After
         * that a lone ESC is the Escape key, and an unfinished sequence
         * loses its ESC and decodes as the bytes it is. */
        if (!esc_stale) { esc_stale = 1; return 0; }
        esc_stale = 0;
        int lone = qn == 1;
        shift(1);
        if (!lone) continue;
        code = 1;
      }
      esc_stale = 0;
    } else {
      code = key_of_byte(q[0]);
      shift(1);
    }
    if (!code) continue;
    *kind = 4; *a = code; *c = 1;
    return 1;
  }
  return 0;
}

/* ---- the headless tier's ONE source policy ----------------------------
 * (haltab.c's table entry and the app-tier primitive below both ask here.)
 *
 *   FPR_EVDEV=<path>  that source and nothing else: a replay must not be
 *                     contaminated by a live terminal or a moving mouse.
 *   FPR_EVDEV=auto    every real keyboard (press AND release), plus the
 *                     mouse.  The terminal still reports its size, and goes
 *                     raw so the same keystrokes -- which a console also
 *                     delivers to stdin -- are neither echoed nor left for
 *                     the shell.  No keyboard readable: the terminal, below.
 *   unset             the terminal; and the mouse when stdin IS a terminal
 *                     (a piped run keeps its exact event stream). */
int qos_headless_poll(int64_t* kind, int64_t* a, int64_t* c) {
  const char* ev = getenv("FPR_EVDEV");
  if (ev && *ev && strcmp(ev, "auto")) return qos_evdev_poll(kind, a, c);
  if (ev && *ev && qos_evdev_sources()) {
    tty_init();
    if (win_poll(kind, a, c)) return 1;
    if (tty_state == 1) { topup(); qn = 0; }
    if (qos_evdev_poll(kind, a, c)) return 1;
    return qos_mice_poll(kind, a, c);
  }
  if (qos_tty_poll(kind, a, c)) return 1;
  return tty_state == 1 ? qos_mice_poll(kind, a, c) : 0;
}

/* ---- the obligation (app tier only) ---------------------------------- */
#ifndef QOSP_HOST
static V h_inputPoll(V u) {
  (void)u;
  /* uniform triple, gfx_fpr.c's shape: (0, 0, 0) means no event */
  int64_t kind = 0, a = 0, c = 0;
  qos_headless_poll(&kind, &a, &c);
  V* t = (V*)fpr_alloc(32);
  ((hdr_t*)t)->tid = 5; ((hdr_t*)t)->var = 0; /* triple */
  t[1] = TAG((sw)kind); t[2] = TAG((sw)a); t[3] = TAG((sw)c);
  return (V)t;
}
FPR_FN(fpr_g_inputPoll, h_inputPoll, 1);
#endif /* !QOSP_HOST */