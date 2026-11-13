/* A packed host launcher with no shell or interpreter dependency. */
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
int main(int argc, char **argv) {
    char path[PATH_MAX];
    if (!realpath(argv[0], path)) { perror("bundle path"); return 1; }
    char *slash = strrchr(path, '/');
    if (!slash) return 1;
    *slash = 0;
    if (chdir(path)) { perror("bundle directory"); return 1; }
    if (BUNDLE_DISK[0] && !getenv("FPR_DISK") && setenv("FPR_DISK", BUNDLE_DISK, 1)) {
        perror("bundle disk"); return 1;
    }
    char **args = calloc((size_t)argc + 3, sizeof(*args));
    if (!args) { perror("bundle arguments"); return 1; }
    args[0] = "./" BUNDLE_HOST; args[1] = "--yes"; args[2] = BUNDLE_APP;
    for (int i = 1; i < argc; ++i) args[i + 2] = argv[i];
    execv(args[0], args);
    perror("bundle host"); free(args); return 1;
}
