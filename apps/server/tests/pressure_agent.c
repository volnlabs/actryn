/* Test-only bounded approved-call workload, imported as a reviewed OCI fixture. */
#define _POSIX_C_SOURCE 200809L
#include <arpa/inet.h>
#include <assert.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static const char *directory = "/run/actryn-broker";
static long long now_ms(void) {
    struct timespec value; assert(clock_gettime(CLOCK_MONOTONIC, &value) == 0);
    return (long long)value.tv_sec * 1000 + value.tv_nsec / 1000000;
}
static int exact_read(int fd, char *p, size_t size, long long until) {
    while (size) {
        long long left = until - now_ms(); assert(left > 0);
        struct timeval timeout = {.tv_sec = left / 1000, .tv_usec = (left % 1000) * 1000};
        assert(setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) == 0);
        errno = 0;
        ssize_t n = read(fd, p, size);
        if (n <= 0) return 0;
        p += n; size -= (size_t)n;
    }
    return 1;
}
static void emit(const char *line) {
    size_t length = strlen(line);
    assert(length < 4096 && write(STDOUT_FILENO, line, length) == (ssize_t)length);
}
static void request(const char *key, int index, int cancel, int uncertain_allowed) {
    long long until = now_ms() + 2000;
    char body[512], frame[516], reply[3072], line[4096];
    int n = cancel ? snprintf(body, sizeof(body), "{\"op\":\"cancel\",\"request_key\":\"%s\"}", key)
        : snprintf(body, sizeof(body), "{\"op\":\"call\",\"request_key\":\"%s\",\"method\":\"diagnostic.echo\",\"input\":{\"index\":%d}}", key, index);
    assert(n > 0 && n < (int)sizeof(body));
    int fd = socket(AF_UNIX, SOCK_STREAM, 0); assert(fd >= 0);
    struct timeval timeout = {.tv_sec = 2};
    assert(setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) == 0);
    assert(setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)) == 0);
    struct sockaddr_un address = {.sun_family = AF_UNIX};
    assert(snprintf(address.sun_path, sizeof(address.sun_path), "%s/%s", directory,
                    cancel ? "closure.sock" : "broker.sock") < (int)sizeof(address.sun_path));
    assert(connect(fd, (void *)&address, sizeof(address)) == 0);
    uint32_t size = htonl((uint32_t)n);
    memcpy(frame, &size, 4); memcpy(frame + 4, body, (size_t)n);
    /* Exactly one request write. Partial/failed sends fail, never retry. */
    assert(write(fd, frame, (size_t)n + 4) == n + 4);
    if (!exact_read(fd, (char *)&size, 4, until)) {
        assert(uncertain_allowed && (errno == 0 || errno == ECONNRESET));
        snprintf(line, sizeof(line), "{\"event\":\"pressure_call\",\"key\":\"%s\",\"writes\":1,\"unknown\":\"eof_after_send\"}\n", key);
    } else {
        size = ntohl(size); assert(size > 0 && size < sizeof(reply));
        assert(exact_read(fd, reply, size, until)); reply[size] = 0;
        n = snprintf(line, sizeof(line), "{\"event\":\"%s\",\"key\":\"%s\",\"writes\":1,\"reply\":%s}\n",
                     cancel ? "pressure_cancel" : "pressure_call", key, reply);
        assert(n > 0 && n < (int)sizeof(line));
    }
    close(fd); emit(line);
}
int main(int argc, char **argv) {
#ifdef ACTRYN_PRESSURE_HOST_TEST
    assert(argc == 2); directory = argv[1];
#else
    (void)argc; (void)argv;
    assert(getuid() == 65532 && getgid() == 65532);
#endif
    signal(SIGPIPE, SIG_IGN);
    long long until = now_ms() + 15000;
    char key[32];
    for (int n = 0; n < 4; n++) {
        snprintf(key, sizeof(key), "base-%d", n); request(key, n, 0, 0);
    }
    int gate[2]; assert(pipe(gate) == 0);
    pid_t children[8];
    for (int n = 0; n < 8; n++) {
        children[n] = fork(); assert(children[n] >= 0);
        if (!children[n]) {
            close(gate[1]); char byte; assert(read(gate[0], &byte, 1) == 1); close(gate[0]);
            snprintf(key, sizeof(key), "burst-%d", n); request(key, n, 0, 1); _exit(0);
        }
    }
    close(gate[0]); assert(write(gate[1], "12345678", 8) == 8); close(gate[1]);
    request("base-0", 0, 1, 0);
    for (int n = 0; n < 8; n++) {
        int status; pid_t result;
        while ((result = waitpid(children[n], &status, WNOHANG)) == 0) {
            if (now_ms() >= until) {
                for (int child = n; child < 8; child++) kill(children[child], SIGKILL);
                assert(!"bounded child completion expired");
            }
            struct timespec delay = {.tv_nsec = 1000000}; assert(nanosleep(&delay, NULL) == 0);
        }
        assert(result == children[n]);
        assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);
    }
    emit("{\"event\":\"pressure_ready\",\"calls\":12,\"cancels\":1}\n");
#ifndef ACTRYN_PRESSURE_HOST_TEST
    sleep(60);
#endif
    return 0;
}
