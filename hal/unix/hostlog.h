/* hostlog.h -- the unified log plane.
 *
 * Every host-side diagnostic used to be a bare fprintf(stderr, ...):
 * under systemd that means journald, invisible to the QOS-side UI --
 * DRM probe results, evdev EACCES, plugin load ranges, mprotect
 * boundaries all vanished from /logs.  qos_hostlog is the one exit:
 * it ALWAYS mirrors to stderr (journald keeps its record), and once
 * the app registers its ring writer (fpr_logput behind the ABI-v4
 * set_log_sink entry) every line ALSO lands in the app's sev-3 (host)
 * ring, browsable as /logs/host.  Lines emitted before registration
 * park in a small pending ring and replay in order at registration,
 * so boot diagnostics are not lost to the UI either.
 *
 * Who calls what:
 *   host code (qosp, gfx.c, evdev_raw.c, ...)  -> qos_hostlog(fmt, ...)
 *   haltab.c fills hal->set_log_sink            = qos_hostlog_set_sink
 *   appside/entry.c registers                   sink = fpr_logput(3,..)
 *   a co-compiled posix image (one address space, no table) may call
 *   qos_hostlog_set_sink directly at init with the same wrapper.
 *
 * THE LAW STILL HOLDS: never call this from an allocation site or a
 * fault handler -- the sink takes the app's log/console locks and
 * byte-loops the UART.  The grow trace and the SIGSEGV report stay on
 * bare stderr for exactly that reason (see the comments at those
 * sites). */
#ifndef QOS_HOSTLOG_H
#define QOS_HOSTLOG_H

#include <stdint.h>

void qos_hostlog(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void qos_hostlog_set_sink(void (*sink)(const char *line, uint64_t n));
/* the console byte (fd 1) with a BOUNDED wait: fd 1 is never made
 * nonblocking (it may be a terminal other processes share), so a full pipe
 * would otherwise hold the calling hart for as long as nobody reads.  A
 * byte waits at most QOS_CONSOLE_WAIT_MS once; while the console stays
 * unwritable later bytes are dropped at once and counted, and the count is
 * reported when writing resumes -- on stderr only: this runs under the app's
 * console lock, so it must never reach the sink. */
void qos_console_putc(char c);

#endif /* QOS_HOSTLOG_H */
