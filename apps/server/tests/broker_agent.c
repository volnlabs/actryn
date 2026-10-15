/* Deliberately runs only inside the disposable software acceptance sandbox. */
#include <assert.h>
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <sys/un.h>
#include <unistd.h>
static void read_all(int fd, void *data, size_t n) {
    char *p=data;while(n){ssize_t k=read(fd,p,n);assert(k>0);p+=k;n-=(size_t)k;}
}
static void call(const char *request,const char *expected) {
    int fd=socket(AF_UNIX,SOCK_STREAM,0);assert(fd>=0);
    struct sockaddr_un address={.sun_family=AF_UNIX};strcpy(address.sun_path,"/run/actryn-broker/broker.sock");
    assert(connect(fd,(void *)&address,sizeof(address))==0);
    uint32_t length=htonl(strlen(request));assert(write(fd,&length,4)==4);assert(write(fd,request,strlen(request))==(ssize_t)strlen(request));
    read_all(fd,&length,4);length=ntohl(length);assert(length<65536);
    char *reply=calloc(length+1,1);assert(reply);read_all(fd,reply,length);assert(strstr(reply,expected));
    printf("BROKER %s\n",reply);fflush(stdout);free(reply);close(fd);
}
int main(void) {
    assert(getuid()==65532 && getgid()==65532);
    errno=0;assert(socket(AF_INET,SOCK_STREAM,0)<0);assert(errno==EPERM);
    errno=0;assert(syscall(SYS_bpf,0,NULL,0)<0);assert(errno==EPERM);
    errno=0;assert(syscall(SYS_perf_event_open,NULL,0,-1,-1,0)<0);assert(errno==EPERM);
    errno=0;assert(syscall(SYS_unshare,0x10000000)<0);assert(errno==EPERM);
    errno=0;assert(syscall(SYS_mount,NULL,NULL,NULL,0,NULL)<0);assert(errno==EPERM);
    assert(open("/run/containerd/containerd.sock",O_RDONLY)<0 && errno==ENOENT);
    assert(open("/run/credentials/actryn-serverd.service/openai-api-key",O_RDONLY)<0 && errno==ENOENT);
    assert(open("/dev/mem",O_RDONLY)<0 && errno==ENOENT);
    assert(open("/bin/agent",O_WRONLY)<0 && (errno==EROFS || errno==EACCES));
    call("{\"op\":\"call\",\"request_key\":\"offline-1\",\"method\":\"model.offline\",\"input\":{\"goal\":\"index forward\",\"observation_id\":\"fixture-obs-1\"}}","\"left_delta_ticks\":10");
    call("{\"op\":\"result\",\"request_key\":\"offline-1\"}","\"left_delta_ticks\":10");
    call("{\"op\":\"call\",\"request_key\":\"denied-1\",\"method\":\"admin.grant\",\"input\":{}}","policy_denied");
    call("{\"op\":\"cancel\",\"request_key\":\"cancel-first\"}","KEY_CANCELLED_DURABLE");
    call("{\"op\":\"call\",\"request_key\":\"cancel-first\",\"method\":\"model.offline\",\"input\":{\"goal\":\"late\",\"observation_id\":\"fixture-obs-1\"}}","closed");
    pid_t child=fork();assert(child>=0);if(child==0){sleep(30);return 0;}
    printf("BROKER_ACCEPTANCE_PASS child=%d\n",child);fflush(stdout);sleep(30);return 0;
}
