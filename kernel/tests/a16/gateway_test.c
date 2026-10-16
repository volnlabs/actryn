/* SPDX-License-Identifier: GPL-2.0-only */
#define A16_GATEWAY_TEST
#include "gateway.c"
#include <poll.h>
#include <sys/wait.h>
static void transfer(int fd,int passed)
{
 char byte=1,control[CMSG_SPACE(sizeof(int))]={0}; struct iovec io={.iov_base=&byte,.iov_len=1};
 struct msghdr m={.msg_iov=&io,.msg_iovlen=1,.msg_control=control,.msg_controllen=sizeof(control)};
 struct cmsghdr *c=CMSG_FIRSTHDR(&m); c->cmsg_level=SOL_SOCKET; c->cmsg_type=SCM_RIGHTS; c->cmsg_len=CMSG_LEN(sizeof(int));
 memcpy(CMSG_DATA(c),&passed,sizeof(passed)); assert(sendmsg(fd,&m,0)==1);
}
static int transferred(int fd)
{
 char byte,control[CMSG_SPACE(sizeof(int))]; int out; struct iovec io={.iov_base=&byte,.iov_len=1};
 struct msghdr m={.msg_iov=&io,.msg_iovlen=1,.msg_control=control,.msg_controllen=sizeof(control)};
 assert(recvmsg(fd,&m,0)==1); memcpy(&out,CMSG_DATA(CMSG_FIRSTHDR(&m)),sizeof(out)); return out;
}
int main(void)
{
 struct gateway g={.ownerfd=-1}; struct client c={.fd=-1}; int pair[2],pass[2],one=1,w;
 struct a16_command command={.action=A16_BIND,.request={.version=1,.opcode=ACTRYN_BIND,.role=ACTRYN_RUNTIME}};
 struct ucred peer={.pid=getpid(),.uid=geteuid(),.gid=getegid()}; pid_t child;
 g.epoll=epoll_create1(EPOLL_CLOEXEC); assert(g.epoll>=0); a16_init(&g.engine);
 dispatch(&g,&c,&command,&peer); assert(!c.reply.error && g.ownerfd>=0 && g.engine.owner);
 assert(!socketpair(AF_UNIX,SOCK_SEQPACKET,0,pair));
 assert(!setsockopt(pair[0],SOL_SOCKET,SO_PASSCRED,&one,sizeof(one)));
 assert(!socketpair(AF_UNIX,SOCK_SEQPACKET,0,pass)); child=fork(); assert(child>=0);
 if(!child) {
  int fd; close(pair[0]); close(pair[1]); close(pass[0]); fd=transferred(pass[1]);
  command.action=A16_STATUS; memset(&command.request,0,sizeof(command.request));
  assert(send(fd,&command,sizeof(command),0)==sizeof(command)); close(fd); _exit(0);
 }
 close(pass[1]); transfer(pass[0],pair[1]); close(pass[0]); close(pair[1]);
 assert(waitpid(child,&w,0)==child && WIFEXITED(w) && WEXITSTATUS(w)==0);
 assert(!receive_command(pair[0],&command,&peer)); assert(peer.pid==child);
 assert(!permitted(&g,&c,&peer)); dispatch(&g,&c,&command,&peer); assert(c.reply.error==-EPERM);
 close(pair[0]); close(g.ownerfd); g.ownerfd=-1; g.engine.owner=false;
 /* A retained client descriptor cannot keep its registered process alive. */
 assert(!socketpair(AF_UNIX,SOCK_SEQPACKET,0,pair)); child=fork(); assert(child>=0);
 if(!child) { char byte; close(pair[0]); assert(read(pair[1],&byte,1)==1); _exit(0); }
 close(pair[1]); peer=(struct ucred){.pid=child,.uid=geteuid(),.gid=getegid()};
 assert(!register_owner(&g,&c,&peer)); assert(write(pair[0],"Q",1)==1);
 { struct pollfd p={.fd=g.ownerfd,.events=POLLIN}; assert(poll(&p,1,2000)==1 && (p.revents&POLLIN)); }
 assert(waitpid(child,&w,0)==child); a16_owner_lost(&g.engine);
 assert(!g.engine.owner && g.engine.status.reason==ACTRYN_OWNER_LOST);
 close(pair[0]); close(g.ownerfd); close(g.epoll);
 puts("PASS actual SCM_RIGHTS credentials and pidfd owner death with retained connection"); return 0;
}
