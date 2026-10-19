/* TEST ONLY. Never execute on the host. One fixed, credential-free OCI workload. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/sysmacros.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static long probe(const char *path) {
    long fd = syscall(SYS_openat, AT_FDCWD, path, O_RDONLY | O_CLOEXEC, 0);
    if (fd < 0) return -errno;
    close((int)fd);
    return fd;
}
static int device_probe(void) {
    struct stat s;
    if (lstat("/dev/actryn-denied-full", &s) || !S_ISCHR(s.st_mode) ||
        major(s.st_rdev) != 1 || minor(s.st_rdev) != 7 ||
        (s.st_mode & 07777) != 0666 || s.st_uid != 0 || s.st_gid != 0 || s.st_nlink != 1)
        return 101;
    /* Exactly these three openat calls in this child, including the unrelated error. */
    long allowed = probe("/dev/null");
    long absent = probe("/dev/actryn-intentionally-absent");
    long forbidden = probe("/dev/actryn-denied-full");
    printf("{\"event\":\"device_probe\",\"results\":[%ld,%ld,%ld],"
           "\"major\":1,\"minor\":7,\"mode\":438}\n", allowed, absent, forbidden);
    if (fflush(stdout)) return 102;
    return allowed >= 0 && absent == -ENOENT && forbidden == -EPERM ? 0 : 103;
}
static int64_t monotonic_ns(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) return -1;
    return (int64_t)t.tv_sec * 1000000000 + t.tv_nsec;
}
int main(void) {
    if (getuid() != 65532 || getgid() != 65532) return 100;
    pid_t child = fork();
    if (child < 0) return 104;
    if (child == 0) _exit(device_probe());
    int status;
    if (waitpid(child, &status, 0) != child || !WIFEXITED(status) || WEXITSTATUS(status)) return 105;
    const size_t bytes = 512U * 1024U * 1024U;
    if (sysconf(_SC_PAGESIZE) != 4096) return 106;
    puts("{\"event\":\"memory_begin\",\"bytes\":536870912,\"page_bytes\":4096}");
    if (fflush(stdout)) return 107;
    volatile unsigned char *p = mmap(NULL, bytes, PROT_READ | PROT_WRITE,
                                    MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED) return 108;
    int64_t start = monotonic_ns();
    if (start < 0) return 109;
    for (size_t offset = 0; offset < bytes; offset += 4096) {
        p[offset] = 0x5a;
        if (offset % (1024U * 1024U) == 0) {
            int64_t now = monotonic_ns();
            if (now < start || now - start >= 10000000000LL) return 110;
        }
    }
    /* Reaching this is failure, never a synthetic successful OOM report. */
    munmap((void *)p, bytes);
    return 111;
}
