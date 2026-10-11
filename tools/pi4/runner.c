/* Bounded isolated hardware test, with wait4 CPU/RSS and thermal samples.
 * runner deadline-seconds stop-seconds log command [args...]
 * stop=0 runs to completion; otherwise request SIGTERM at stop-seconds.
 * Its JSON is evidence, not a pass oracle (the caller checks the log/status).
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static double now(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec + t.tv_nsec / 1e9;
}
static long read_number(const char *path) {
  FILE *f = fopen(path, "r");
  long n = -1;
  if (f) { if (fscanf(f, "%ld", &n) != 1) n = -1; fclose(f); }
  return n;
}
int main(int argc, char **argv) {
  if (argc < 5) return 2;
  double limit = strtod(argv[1], NULL), stop = strtod(argv[2], NULL);
  if (limit <= 0 || stop < 0 || stop >= limit) return 2;
  int log = open(argv[3], O_WRONLY | O_CREAT | O_TRUNC, 0600);
  if (log < 0) { perror("log"); return 2; }
  double start = now(), term_at = 0;
  pid_t pid = fork();
  if (pid < 0) { perror("fork"); return 2; }
  if (pid == 0) {
    if (setsid() < 0) _exit(126);
    int null = open("/dev/null", O_RDONLY);
    dup2(null, STDIN_FILENO);
    dup2(log, STDOUT_FILENO); dup2(log, STDERR_FILENO);
    close(log); close(null);
    execvp(argv[4], argv + 4);
    perror("execvp"); _exit(127);
  }
  close(log);
  int status = 0, timed_out = 0, requested_stop = 0, killed = 0;
  long peak_temp = -1, min_freq = -1, max_freq = -1;
  struct rusage usage = {0};
  for (;;) {
    pid_t done = wait4(pid, &status, WNOHANG, &usage);
    if (done == pid) break;
    if (done < 0 && errno != EINTR) { perror("wait4"); return 2; }
    double elapsed = now() - start;
    long temp = read_number("/sys/class/thermal/thermal_zone0/temp");
    long freq = read_number("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq");
    if (temp > peak_temp) peak_temp = temp;
    if (freq >= 0 && (min_freq < 0 || freq < min_freq)) min_freq = freq;
    if (freq > max_freq) max_freq = freq;
    if (!term_at && (elapsed >= limit || (stop > 0 && elapsed >= stop))) {
      timed_out = elapsed >= limit;
      requested_stop = !timed_out;
      kill(-pid, SIGTERM); term_at = now();
    }
    if (term_at && !killed && now() - term_at >= 3) {
      kill(-pid, SIGKILL); killed = 1;
    }
    struct timespec pause = {0, 20000000};
    nanosleep(&pause, NULL);
  }
  /* No child of this isolated test may outlive the test. */
  kill(-pid, SIGKILL);
  double elapsed = now() - start;
  printf("{\"exit\":%d,\"signal\":%d,\"seconds\":%.6f,"
         "\"user_seconds\":%.6f,\"system_seconds\":%.6f,"
         "\"max_rss_kib\":%ld,\"peak_temp_millic\":%ld,"
         "\"min_cpu_khz\":%ld,\"max_cpu_khz\":%ld,"
         "\"timeout\":%s,\"stop_requested\":%s,\"killed\":%s}\n",
         WIFEXITED(status) ? WEXITSTATUS(status) : -1,
         WIFSIGNALED(status) ? WTERMSIG(status) : 0, elapsed,
         usage.ru_utime.tv_sec + usage.ru_utime.tv_usec / 1e6,
         usage.ru_stime.tv_sec + usage.ru_stime.tv_usec / 1e6,
         usage.ru_maxrss, peak_temp, min_freq, max_freq,
         timed_out ? "true" : "false", requested_stop ? "true" : "false",
         killed ? "true" : "false");
  return 0;
}
