/* SPDX-License-Identifier: Apache-2.0 */
/* Test-process-only SQLite sync fault. Never load into a service or guest. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static atomic_int consumed;

static void marker(const char *root, const char *name, const char *value)
{
    char path[PATH_MAX];
    int n = snprintf(path, sizeof(path), "%s/%s", root, name);
    if (n < 0 || n >= (int)sizeof(path)) _exit(120);
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (fd < 0 || write(fd, value, strlen(value)) != (ssize_t)strlen(value)) _exit(121);
    if (close(fd)) _exit(122);
}

static int sync_call(int fd, const char *symbol)
{
    int (*real_sync)(int) = dlsym(RTLD_NEXT, symbol);
    if (!real_sync) _exit(123);
    const char *root = getenv("ACTRYN_SYNC_ROOT");
    const char *mode = getenv("ACTRYN_SYNC_MODE");
    if (!root || root[0] != '/' || !mode) return real_sync(fd);
    char proc[64], actual[PATH_MAX], expected[PATH_MAX], journal[PATH_MAX], armed[PATH_MAX];
    snprintf(proc, sizeof(proc), "/proc/self/fd/%d", fd);
    ssize_t n = readlink(proc, actual, sizeof(actual) - 1);
    if (n < 0) return real_sync(fd);
    actual[n] = 0;
    if (snprintf(expected, sizeof(expected), "%s/intent.sqlite", root) >= (int)sizeof(expected) ||
        snprintf(journal, sizeof(journal), "%s/intent.sqlite-journal", root) >= (int)sizeof(journal) ||
        snprintf(armed, sizeof(armed), "%s/armed", root) >= (int)sizeof(armed)) _exit(124);
    if ((strcmp(actual, expected) && strcmp(actual, journal)) || access(armed, F_OK))
        return real_sync(fd);
    if (strcmp(mode, "stall") && strcmp(mode, "eio")) _exit(125);
    int zero = 0;
    if (!atomic_compare_exchange_strong(&consumed, &zero, 1)) return real_sync(fd);

    char record[PATH_MAX + 64], release[PATH_MAX];
    snprintf(record, sizeof(record), "%s\n%s\n", symbol, actual);
    marker(root, "sync-entered", record);
    if (snprintf(release, sizeof(release), "%s/release", root) >= (int)sizeof(release)) _exit(126);
    struct timespec start, now, delay = {.tv_nsec = 5000000};
    if (clock_gettime(CLOCK_MONOTONIC, &start)) _exit(127);
    while (access(release, F_OK)) {
        if (clock_gettime(CLOCK_MONOTONIC, &now) || now.tv_sec - start.tv_sec >= 8) _exit(128);
        nanosleep(&delay, NULL);
    }
    if (!strcmp(mode, "eio")) {
        marker(root, "sync-returned", "-1 EIO\n");
        errno = EIO;
        return -1;
    }
    int result = real_sync(fd), saved_errno = errno;
    snprintf(record, sizeof(record), "%d\n", result);
    marker(root, "sync-returned", record);
    errno = saved_errno;
    return result;
}

int fsync(int fd) { return sync_call(fd, "fsync"); }
int fdatasync(int fd) { return sync_call(fd, "fdatasync"); }
