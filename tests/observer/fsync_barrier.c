/* Test-only LD_PRELOAD fixture. Never installed or used by production units. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

static atomic_int intercepted;

static void marker(const char *directory, const char *name)
{
	char path[PATH_MAX];
	if (snprintf(path, sizeof(path), "%s/%s", directory, name) >= (int)sizeof(path))
		_exit(120);
	int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
	if (fd < 0 || write(fd, "1", 1) != 1 || close(fd) != 0)
		_exit(121);
}

int fsync(int fd)
{
	const char *target = getenv("ACTRYN_TEST_SYNC_TARGET");
	const char *directory = getenv("ACTRYN_TEST_SYNC_CONTROL");
	char descriptor[64], path[PATH_MAX], suffix[40], release[PATH_MAX];
	if (!target || !directory || strlen(target) != 32)
		return (int)syscall(SYS_fsync, fd);
	snprintf(descriptor, sizeof(descriptor), "/proc/self/fd/%d", fd);
	ssize_t size = readlink(descriptor, path, sizeof(path) - 1);
	if (size < 0)
		return (int)syscall(SYS_fsync, fd);
	path[size] = '\0';
	snprintf(suffix, sizeof(suffix), "/%s.jsonl", target);
	size_t wanted = strlen(suffix);
	if ((size_t)size < wanted || strcmp(path + size - wanted, suffix) != 0 ||
	    atomic_exchange(&intercepted, 1))
		return (int)syscall(SYS_fsync, fd);
	if (snprintf(release, sizeof(release), "%s/release", directory) >= (int)sizeof(release))
		_exit(122);
	marker(directory, "entered");
	struct timespec started, now;
	clock_gettime(CLOCK_MONOTONIC, &started);
	for (;;) {
		int gate = open(release, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
		if (gate >= 0) {
			char result = 0;
			ssize_t read_bytes = read(gate, &result, 1);
			close(gate);
			if (read_bytes == 1) {
				marker(directory, "released");
				if (result == 'E') {
					errno = EIO;
					return -1;
				}
				if (result == 'S')
					return (int)syscall(SYS_fsync, fd);
				_exit(123);
			}
		}
		clock_gettime(CLOCK_MONOTONIC, &now);
		if (now.tv_sec - started.tv_sec >= 15) {
			marker(directory, "expired");
			errno = ETIMEDOUT;
			return -1;
		}
		struct timespec pause = {.tv_sec = 0, .tv_nsec = 1000000};
		nanosleep(&pause, NULL);
	}
}
