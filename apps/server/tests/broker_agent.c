/* Deliberately runs only inside the disposable software acceptance sandbox. */
#include <assert.h>
#include <arpa/inet.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/un.h>
#include <unistd.h>
static void read_all(int fd, void *data, size_t n) {
    char *p=data;while(n){ssize_t k=read(fd,p,n);assert(k>0);p+=k;n-=(size_t)k;}
}
static void inherited_fds(void) {
    int errors=0,sockets=0,stdin_closed=0,entries=0,other_fds=0,extra_fds=0;
    for(int fd=0;fd<=2;fd++) {
        struct stat s;errno=0;int result=fstat(fd,&s);int error=errno;
        if(result<0){if(fd==0 && error==EBADF)stdin_closed=1;else errors++;}
        else if(S_ISSOCK(s.st_mode))sockets++;
    }
    DIR *directory=opendir("/proc/self/fd");int enumeration_fd=directory ? dirfd(directory) : -1;
    if(directory) {
        for(;;) {
            if(entries>=4096){errors++;break;}
            errno=0;struct dirent *entry=readdir(directory);
            if(!entry){if(errno)errors++;break;}
            entries++;
            if(!strcmp(entry->d_name,".") || !strcmp(entry->d_name,".."))continue;
            char *end;errno=0;long fd=strtol(entry->d_name,&end,10);
            if(errno || !entry->d_name[0] || *end || fd<0 || fd>INT_MAX){errors++;continue;}
            if(fd==enumeration_fd)continue;
            other_fds++;if(fd>2)extra_fds++;
        }
    }
    int closed=directory ? closedir(directory) : -1;
    printf("{\"event\":\"sandbox_fds\",\"enumeration_fd\":%d,\"entries\":%d,\"other_fds\":%d,"
           "\"extra_fds\":%d,\"stdio_sockets\":%d,\"stdin_closed\":%d,\"errors\":%d,\"close_result\":%d}\n",
           enumeration_fd,entries,other_fds,extra_fds,sockets,stdin_closed,errors,closed);
    assert(fflush(stdout)==0);
    assert(enumeration_fd>=0 && entries<=4096 && errors==0 && sockets==0 && extra_fds==0 && closed==0);
    assert(other_fds==3-stdin_closed);
}
static void probe(const char *name, long number, long result, int error, int expected) {
    printf("{\"event\":\"sandbox_probe\",\"case\":\"%s\",\"syscall\":%ld,\"result\":%ld,\"errno\":%d}\n",
           name,number,result,error);assert(fflush(stdout)==0);
    assert(result<0 && error==expected);
}
static void call(const char *name,const char *request,const char *expected) {
    int fd=socket(AF_UNIX,SOCK_STREAM,0);assert(fd>=0);
    struct sockaddr_un address={.sun_family=AF_UNIX};strcpy(address.sun_path,"/run/actryn-broker/broker.sock");
    assert(connect(fd,(void *)&address,sizeof(address))==0);
    uint32_t length=htonl(strlen(request));assert(write(fd,&length,4)==4);assert(write(fd,request,strlen(request))==(ssize_t)strlen(request));
    read_all(fd,&length,4);length=ntohl(length);assert(length<65536);
    char *reply=calloc(length+1,1);assert(reply);read_all(fd,reply,length);
    /* The host strictly parses the nested typed JSON. Malformed, duplicate-key,
       embedded-NUL or multiline replies fail closed; never a format string. */
    printf("{\"event\":\"broker_probe\",\"case\":\"%s\",\"reply\":%s}\n",name,reply);
    assert(fflush(stdout)==0);assert(strlen(reply)==length && strstr(reply,expected));
    free(reply);close(fd);
}
int main(void) {
    printf("{\"event\":\"sandbox_identity\",\"pid\":%ld,\"tid\":%ld,\"uid\":%lu,\"gid\":%lu}\n",
           (long)getpid(),syscall(SYS_gettid),(unsigned long)getuid(),(unsigned long)getgid());
    assert(fflush(stdout)==0);
    assert(getuid()==65532 && getgid()==65532);
    inherited_fds(); /* Before creating any broker socket; no descriptor content is read. */
    long result;int error;
    errno=0;result=socket(AF_INET,SOCK_STREAM,0);error=errno;probe("socket_inet",SYS_socket,result,error,EPERM);
    errno=0;result=syscall(SYS_bpf,0,NULL,0);error=errno;probe("bpf",SYS_bpf,result,error,EPERM);
    errno=0;result=syscall(SYS_perf_event_open,NULL,0,-1,-1,0);error=errno;probe("perf_event_open",SYS_perf_event_open,result,error,EPERM);
    errno=0;result=syscall(SYS_unshare,0x10000000);error=errno;probe("unshare",SYS_unshare,result,error,EPERM);
    errno=0;result=syscall(SYS_setns,-1,0);error=errno;probe("setns",SYS_setns,result,error,EPERM);
    errno=0;result=syscall(SYS_mount,NULL,NULL,NULL,0,NULL);error=errno;probe("mount",SYS_mount,result,error,EPERM);
    errno=0;result=syscall(SYS_openat,AT_FDCWD,"/run/containerd/containerd.sock",O_RDONLY,0);error=errno;probe("containerd_path",SYS_openat,result,error,ENOENT);
    errno=0;result=syscall(SYS_openat,AT_FDCWD,"/run/credentials/actryn-serverd.service/openai-api-key",O_RDONLY,0);error=errno;probe("credential_path",SYS_openat,result,error,ENOENT);
    errno=0;result=syscall(SYS_openat,AT_FDCWD,"/dev/mem",O_RDONLY,0);error=errno;probe("devmem_path",SYS_openat,result,error,ENOENT);
    errno=0;result=syscall(SYS_openat,AT_FDCWD,"/bin/agent",O_WRONLY,0);error=errno;
    printf("{\"event\":\"sandbox_probe\",\"case\":\"root_readonly\",\"syscall\":%ld,\"result\":%ld,\"errno\":%d}\n",(long)SYS_openat,result,error);
    assert(fflush(stdout)==0);assert(result<0 && (error==EROFS || error==EACCES));
    call("offline_call","{\"op\":\"call\",\"request_key\":\"offline-1\",\"method\":\"model.offline\",\"input\":{\"goal\":\"index forward\",\"observation_id\":\"fixture-obs-1\"}}","\"left_delta_ticks\":10");
    call("offline_result","{\"op\":\"result\",\"request_key\":\"offline-1\"}","\"left_delta_ticks\":10");
    call("forbidden_method","{\"op\":\"call\",\"request_key\":\"denied-1\",\"method\":\"admin.grant\",\"input\":{}}","policy_denied");
    call("cancel_absent","{\"op\":\"cancel\",\"request_key\":\"cancel-first\"}","KEY_CANCELLED_DURABLE");
    call("call_closed","{\"op\":\"call\",\"request_key\":\"cancel-first\",\"method\":\"model.offline\",\"input\":{\"goal\":\"late\",\"observation_id\":\"fixture-obs-1\"}}","closed");
    pid_t child=fork();assert(child>=0);if(child==0){sleep(30);return 0;}
    printf("BROKER_ACCEPTANCE_PASS child=%d\n",child);fflush(stdout);sleep(30);return 0;
}
