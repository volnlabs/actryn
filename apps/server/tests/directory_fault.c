/* Fixed test-only launcher resource-directory fault. Never a production hook. */
#define _GNU_SOURCE
#include <fcntl.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

#ifndef ACTRYN_A08_HOST_TEST
#define CONTROL_DIR "/run/actryn/a08-pressure"
#define BROKER_PREFIX "/run/actryn/brokers/"
#endif
static uid_t owner(void) {
#ifdef ACTRYN_A08_HOST_TEST
    return getuid();
#else
    return 0;
#endif
}
static int hex_id(const char *s) {
    if (strlen(s) != 32) return 0;
    for (int n = 0; n < 32; n++)
        if (!((s[n] >= '0' && s[n] <= '9') || (s[n] >= 'a' && s[n] <= 'f'))) return 0;
    return 1;
}
static uint64_t now_ns(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) return 0;
    return (uint64_t)t.tv_sec * 1000000000 + (uint64_t)t.tv_nsec;
}
static int safe_file(int fd, off_t bound) {
    struct stat s;
    return fd >= 0 && fstat(fd, &s) == 0 && S_ISREG(s.st_mode) && s.st_uid == owner()
        && (s.st_mode & 0777) == 0600 && s.st_nlink == 1 && s.st_size <= bound;
}
static int control_directory(void) {
    struct stat s;
#ifndef ACTRYN_A08_HOST_TEST
    const char *parents[] = {"/run", "/run/actryn"};
    for (unsigned n = 0; n < sizeof(parents)/sizeof(parents[0]); n++)
        if (lstat(parents[n], &s) || !S_ISDIR(s.st_mode) || s.st_uid || (s.st_mode & 022)) return -1;
#endif
    int fd = open(CONTROL_DIR, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (fd >= 0 && fstat(fd, &s) == 0 && s.st_uid == owner() && (s.st_mode & 0777) == 0700) return fd;
    if (fd >= 0) close(fd);
    return -1;
}
static int event(int dir, char kind, int error, const char *path) {
    int fd = openat(dir, "events", O_RDWR | O_CREAT | O_APPEND | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK, 0600);
    int ok = 0;
    if (safe_file(fd, 8192) && flock(fd, LOCK_EX | LOCK_NB) == 0) {
        char data[8193], line[256];
        ssize_t size = pread(fd, data, 8193, 0);
        unsigned lines = 0;
        if (size >= 0 && size <= 8192) {
            for (ssize_t n = 0; n < size; n++) lines += data[n] == '\n';
            int length = snprintf(line, sizeof(line), "%llu %ld %c %d %s\n",
                                  (unsigned long long)now_ns(), (long)getpid(), kind, error, path);
            if (lines < 64 && length > 0 && length < (int)sizeof(line) && size + length <= 8192)
                ok = write(fd, line, (size_t)length) == length;
        }
    }
    if (fd >= 0) close(fd);
    return ok;
}
static int inject(const char *path, char wanted) {
    if (geteuid() != owner() || strncmp(path, BROKER_PREFIX, strlen(BROKER_PREFIX))) return 0;
    const char *identity = path + strlen(BROKER_PREFIX);
    if (!hex_id(identity)) return 0;
    int dir = control_directory(); if (dir < 0) return 0;
    int fd = openat(dir, "control", O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    char bytes[161], active[33], target[33], mode, extra;
    unsigned version; unsigned long long start, end; int consumed = 0, result = 0;
    ssize_t n = safe_file(fd, 160) ? read(fd, bytes, 160) : -1;
    if (fd >= 0) close(fd);
    if (n <= 0 || n >= 160) goto done;
    bytes[n] = 0;
    if (sscanf(bytes, "%u %c %llu %llu %32s %32s%c%n", &version, &mode, &start,
               &end, active, target, &extra, &consumed) != 7 || consumed != n || extra != '\n'
        || version != 1 || mode != wanted || !hex_id(active) || !hex_id(target)
        || !strcmp(active, target) || !strcmp(identity, active)) goto done;
    uint64_t now = now_ns();
    if (end <= start || end - start > 10000000000ULL || now < start || now >= end) goto done;
    if (mode == 'A') {
        if (strcmp(target, "00000000000000000000000000000000")) goto done;
        fd = openat(dir, "latched", O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
        if (fd < 0) goto done;
        char line[34]; snprintf(line, sizeof(line), "%s\n", identity);
        int ok = safe_file(fd, 0) && write(fd, line, 33) == 33; close(fd);
        if (ok && event(dir, mode, ENOSPC, path)) result = ENOSPC;
    } else if (mode == 'R' && !strcmp(identity, target) && event(dir, mode, EBUSY, path)) {
        result = EBUSY;
    }
done:
    close(dir); return result;
}
int mkdir(const char *path, mode_t mode) {
    int error = inject(path, 'A');
    if (error) { errno = error; return -1; }
    return (int)syscall(SYS_mkdirat, AT_FDCWD, path, mode);
}
int rmdir(const char *path) {
    int error = inject(path, 'R');
    if (error) { errno = error; return -1; }
    return (int)syscall(SYS_unlinkat, AT_FDCWD, path, AT_REMOVEDIR);
}
