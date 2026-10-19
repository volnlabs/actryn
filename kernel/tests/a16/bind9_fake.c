/* SPDX-License-Identifier: GPL-2.0-only */
/* Host-only fault peer: no sockets, authority device or workload main run. */
#define main original_workload_main
#include "bind9-workload.c"
#undef main
static int calls=-1,reply_error;
static unsigned expected_role;
static const char *mode;
static void note(const char *value)
{ size_t n=strlen(value); assert(write(calls,value,n)==(ssize_t)n); }
int __wrap_socket(int domain,int type,int protocol)
{
 assert(domain==AF_UNIX && type==(SOCK_SEQPACKET|SOCK_CLOEXEC) && !protocol);
 note("socket\n"); return 200;
}
int __wrap_connect(int fd,const struct sockaddr *address,socklen_t length)
{
 const struct sockaddr_un *a=(const struct sockaddr_un *)address;
 assert(fd==200 && length==sizeof(*a) && a->sun_family==AF_UNIX && !strcmp(a->sun_path,A16_SOCKET));
 note("connect\n"); return 0;
}
ssize_t __wrap_send(int fd,const void *buffer,size_t length,int flags)
{
 const struct a16_command *c=buffer;
 assert(fd==200 && length==sizeof(*c) && flags==MSG_NOSIGNAL);
 assert(c->action==A16_BIND && !c->reserved && c->request.version==1 &&
        c->request.opcode==ACTRYN_BIND && c->request.role==expected_role);
 note("send\n"); return (ssize_t)length;
}
int __wrap_poll(struct pollfd *fds,nfds_t count,int timeout)
{
 assert(count==1 && fds[0].fd==200 && fds[0].events==POLLIN && timeout==2000);
 fds[0].revents=POLLIN; note("poll\n"); return 1;
}
ssize_t __wrap_recv(int fd,void *buffer,size_t length,int flags)
{
 struct a16_reply r={.error=reply_error};
 assert(fd==200 && length==sizeof(r) && flags==MSG_TRUNC);
 if(!strcmp(mode,"reserved")) r.reserved=1;
 memcpy(buffer,&r,sizeof(r)); note("recv\n");
 return (ssize_t)sizeof(r)-(!strcmp(mode,"short")?1:0);
}
int main(int argc,char **argv)
{
 struct rlimit core={0,0}; int fd;
 assert(argc==8 && !setrlimit(RLIMIT_CORE,&core));
 mode=argv[1];reply_error=(int)strtol(argv[2],NULL,10);expected_role=(unsigned)strtoul(argv[3],NULL,10);
 userspace=true;trial=(unsigned)strtoul(argv[5],NULL,10);
 journal=open(argv[6],O_WRONLY|O_CREAT|O_EXCL|O_APPEND,0600);assert(journal>=0);
 calls=open(argv[7],O_WRONLY|O_CREAT|O_EXCL,0600);assert(calls>=0);
#if BIND9_DERIVED
 fd=bind_role(expected_role,argv[4]);
#else
 fd=bind_role(expected_role);
#endif
 assert(fd==200);close(journal);close(calls);return 0;
}
