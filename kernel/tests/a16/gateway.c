/* SPDX-License-Identifier: GPL-2.0-only */
#define _GNU_SOURCE
#include "protocol.h"
#include "common.h"
#include <signal.h>
#include <poll.h>
#include <stdlib.h>
#include <sys/epoll.h>
#include <sys/file.h>
#include <sys/ioctl.h>
#include <sys/random.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/timerfd.h>
#include <sys/un.h>
#include <termios.h>
#define CLIENTS 8
struct client { int fd; unsigned role; uint64_t generation; bool pending; struct a16_reply reply; };
struct gateway {
 struct a16_engine engine; struct client clients[CLIENTS];
 int epoll,uart,listener,timer,ownerfd; pid_t ownerpid; uid_t owneruid; gid_t ownergid;
 uint64_t generation;
};
static bool permitted(const struct gateway *g,const struct client *c,const struct ucred *peer)
{
 if(peer->uid!=geteuid()) return false;
 if(c->role==ACTRYN_ADMIN || c->role==ACTRYN_EVENTS || !c->role) return true;
 return c->generation==g->generation && peer->pid==g->ownerpid && peer->uid==g->owneruid && peer->gid==g->ownergid;
}
static int receive_command(int fd,struct a16_command *command,struct ucred *peer)
{
 char control[CMSG_SPACE(sizeof(struct ucred))]; struct cmsghdr *c; bool found=false;
 struct iovec io={.iov_base=command,.iov_len=sizeof(*command)};
 struct msghdr msg={.msg_iov=&io,.msg_iovlen=1,.msg_control=control,.msg_controllen=sizeof(control)};
 ssize_t n=recvmsg(fd,&msg,MSG_DONTWAIT|MSG_CMSG_CLOEXEC);
 if(n<0) return errno==EAGAIN?-EAGAIN:-errno;
 if(!n) return -ECONNRESET;
 for(c=CMSG_FIRSTHDR(&msg);c;c=CMSG_NXTHDR(&msg,c)) {
  if(c->cmsg_level==SOL_SOCKET && c->cmsg_type==SCM_CREDENTIALS && c->cmsg_len==CMSG_LEN(sizeof(*peer))) {
   memcpy(peer,CMSG_DATA(c),sizeof(*peer)); found=true;
  } else if(c->cmsg_level==SOL_SOCKET && c->cmsg_type==SCM_RIGHTS) {
   size_t count=(c->cmsg_len-CMSG_LEN(0))/sizeof(int); int *fds=(int *)CMSG_DATA(c);
   for(size_t i=0;i<count;i++) close(fds[i]);
   found=false; msg.msg_flags|=MSG_CTRUNC;
  } else msg.msg_flags|=MSG_CTRUNC;
 }
 if(n!=(ssize_t)sizeof(*command) || msg.msg_flags&(MSG_TRUNC|MSG_CTRUNC)) return -EPROTO;
 return found?0:-EPERM;
}
static int register_owner(struct gateway *g,struct client *c,const struct ucred *peer)
{
 int fd;
 if(g->engine.status.state!=ACTRYN_INHIBITED && g->engine.status.state!=ACTRYN_FAULT_LATCHED) return -EBUSY;
 if(g->engine.owner && g->ownerpid!=peer->pid) return -EBUSY;
 if(g->generation==UINT64_MAX) return -EOVERFLOW;
 fd=(int)syscall(SYS_pidfd_open,peer->pid,0); if(fd<0) return -errno;
 if(g->ownerfd>=0) { epoll_ctl(g->epoll,EPOLL_CTL_DEL,g->ownerfd,NULL); close(g->ownerfd); }
 g->ownerfd=fd; g->ownerpid=peer->pid; g->owneruid=peer->uid; g->ownergid=peer->gid;
 g->engine.owner=true; c->generation=++g->generation;
 return 0;
}
static void dispatch(struct gateway *g,struct client *c,const struct a16_command *cmd,const struct ucred *peer)
{
 struct actryn_request r=cmd->request,z; unsigned char nonce[16]; int rc=0;
 memset(&c->reply,0,sizeof(c->reply));
 if(cmd->reserved || !permitted(g,c,peer)) rc=-EPERM;
 else if(cmd->action==A16_BIND) {
  z=r; z.version=z.opcode=z.role=0;
  if(c->role || r.version!=1 || r.opcode!=ACTRYN_BIND || r.role<1 || r.role>4 ||
     memcmp(&z,&(struct actryn_request){0},sizeof(z))) rc=-EINVAL;
  else if(r.role==ACTRYN_RUNTIME) rc=register_owner(g,c,peer);
  else if(r.role==ACTRYN_ACQUISITION && (!g->engine.owner || peer->pid!=g->ownerpid ||
    peer->uid!=g->owneruid || peer->gid!=g->ownergid)) rc=-EPERM;
  if(!rc) { c->role=r.role; c->generation=g->generation; }
 } else if(!c->role) rc=-EPERM;
 else if(cmd->action==A16_REQUEST) {
  if((r.opcode==ACTRYN_HANDSHAKE || r.opcode==ACTRYN_RECOVER) && getrandom(nonce,sizeof(nonce),0)!=sizeof(nonce)) rc=-EIO;
  else rc=a16_request(&g->engine,c->role,&r,nonce);
 } else if(memcmp(&r,&(struct actryn_request){0},sizeof(r))) rc=-EINVAL;
 else if(cmd->action==A16_STATUS) {}
 else if(cmd->action==A16_EVENT && c->role==ACTRYN_EVENTS) rc=a16_event(&g->engine,&c->reply.data.event);
 else rc=-EPERM;
 c->reply.error=rc;
 if(cmd->action==A16_BIND || cmd->action==A16_REQUEST) c->reply.data.request=r;
 else if(cmd->action==A16_STATUS) c->reply.data.status=a16_status(&g->engine);
 c->pending=true;
}
#ifndef A16_GATEWAY_TEST
static volatile sig_atomic_t stopping;
static void stop_signal(int signo) { (void)signo; stopping=1; }
static void interest(struct gateway *g,int fd,uint32_t mask)
{ struct epoll_event v={.events=mask,.data.fd=fd}; if(epoll_ctl(g->epoll,EPOLL_CTL_MOD,fd,&v)) assert(!epoll_ctl(g->epoll,EPOLL_CTL_ADD,fd,&v)); }
static ptrdiff_t uart_write(void *opaque,const unsigned char *p,size_t n)
{
 struct gateway *g=opaque; ssize_t result=write(g->uart,p,n);
 if(result<0 && (errno==EAGAIN || errno==EINTR)) return 0;
 return result<0?-errno:result;
}
static void drop_client(struct gateway *g,struct client *c)
{
 if(c->role==ACTRYN_RUNTIME && c->generation==g->generation) a16_owner_lost(&g->engine);
 epoll_ctl(g->epoll,EPOLL_CTL_DEL,c->fd,NULL); close(c->fd); *c=(struct client){.fd=-1};
}
int main(int argc,char **argv)
{
 struct gateway g={.ownerfd=-1}; struct sockaddr_un addr={.sun_family=AF_UNIX};
 struct itimerspec timer={.it_interval={.tv_nsec=10000000},.it_value={.tv_nsec=10000000}};
 struct termios term; struct stat st; unsigned i;
 (void)argv; assert(argc==1); a16_guard(1); umask(077); a16_init(&g.engine);
 g.uart=open("/dev/ttyAMA1",O_RDWR|O_NOCTTY|O_NONBLOCK|O_CLOEXEC); assert(g.uart>=0);
 assert(!fstat(g.uart,&st) && S_ISCHR(st.st_mode) && st.st_uid==0);
 assert(!fchmod(g.uart,0600)); assert(!flock(g.uart,LOCK_EX|LOCK_NB)); assert(!ioctl(g.uart,TIOCEXCL));
 assert(!tcgetattr(g.uart,&term)); cfmakeraw(&term); assert(!cfsetispeed(&term,B115200));
 assert(!cfsetospeed(&term,B115200)); term.c_cflag|=CLOCAL|CREAD; term.c_cflag&=~CRTSCTS;
 assert(!tcsetattr(g.uart,TCSANOW,&term));
 g.epoll=epoll_create1(EPOLL_CLOEXEC); assert(g.epoll>=0);
 g.listener=socket(AF_UNIX,SOCK_SEQPACKET|SOCK_NONBLOCK|SOCK_CLOEXEC,0); assert(g.listener>=0);
 strcpy(addr.sun_path,A16_SOCKET); /* Existing socket is an error, never blindly unlinked. */
 assert(!bind(g.listener,(struct sockaddr *)&addr,sizeof(addr))); assert(!listen(g.listener,CLIENTS));
 g.timer=timerfd_create(CLOCK_BOOTTIME,TFD_NONBLOCK|TFD_CLOEXEC); assert(g.timer>=0);
 assert(!timerfd_settime(g.timer,0,&timer,NULL));
 interest(&g,g.listener,EPOLLIN); interest(&g,g.timer,EPOLLIN); interest(&g,g.uart,EPOLLIN);
 for(i=0;i<CLIENTS;i++) g.clients[i].fd=-1;
 signal(SIGTERM,stop_signal); signal(SIGINT,stop_signal); signal(SIGPIPE,SIG_IGN); a16_deny_exec();
 while(!stopping) {
  struct epoll_event ready[16];
  int n=epoll_wait(g.epoll,ready,16,g.engine.rx_count?0:100); bool uart_ready=false;
  if(n<0) { assert(errno==EINTR); continue; }
  a16_time(&g.engine,a16_now());
  /* Owner death and local control connections precede another UART write. */
  for(int j=0;j<n;j++) if(ready[j].data.fd==g.ownerfd) {
   a16_owner_lost(&g.engine); epoll_ctl(g.epoll,EPOLL_CTL_DEL,g.ownerfd,NULL);
   close(g.ownerfd); g.ownerfd=-1;
  }
  for(int j=0;j<n;j++) {
   int fd=ready[j].data.fd;
   if(fd==g.timer) { uint64_t ticks; (void)read(fd,&ticks,sizeof(ticks)); }
   else if(fd==g.listener) {
    int accepted=accept4(fd,NULL,NULL,SOCK_NONBLOCK|SOCK_CLOEXEC),one=1;
    if(accepted<0) { assert(errno==EAGAIN || errno==EINTR); continue; }
    for(i=0;i<CLIENTS && g.clients[i].fd>=0;i++) {}
    if(i==CLIENTS) close(accepted);
    else { int bytes=4096;
     assert(!setsockopt(accepted,SOL_SOCKET,SO_PASSCRED,&one,sizeof(one)));
     assert(!setsockopt(accepted,SOL_SOCKET,SO_RCVBUF,&bytes,sizeof(bytes)));
     assert(!setsockopt(accepted,SOL_SOCKET,SO_SNDBUF,&bytes,sizeof(bytes)));
     g.clients[i]=(struct client){.fd=accepted}; interest(&g,accepted,EPOLLIN); }
   } else if(fd==g.uart) uart_ready=true;
  }
  for(unsigned pass=0;pass<2;pass++) for(i=0;i<CLIENTS;i++) {
   struct client *c=&g.clients[i]; struct a16_command cmd; struct ucred peer; int rc;
   if(c->fd<0 || (c->role==ACTRYN_ADMIN)!=(pass==0)) continue;
   if(!c->pending) {
    rc=receive_command(c->fd,&cmd,&peer);
    if(rc && rc!=-EAGAIN) { drop_client(&g,c); continue; }
    if(!rc) { a16_time(&g.engine,a16_now()); dispatch(&g,c,&cmd,&peer);
     if(g.ownerfd>=0) interest(&g,g.ownerfd,EPOLLIN); }
   }
   if(c->pending) {
    ssize_t sent=send(c->fd,&c->reply,sizeof(c->reply),MSG_DONTWAIT|MSG_NOSIGNAL);
    if(sent==(ssize_t)sizeof(c->reply)) c->pending=false;
    else if(sent>=0 || (errno!=EAGAIN && errno!=EINTR)) { drop_client(&g,c); continue; }
   }
   interest(&g,c->fd,c->pending?EPOLLOUT:EPOLLIN);
  }
  if(uart_ready) {
   unsigned char bytes[512]; ssize_t got=read(g.uart,bytes,sizeof(bytes));
   if(got>0) { a16_time(&g.engine,a16_now()); a16_receive(&g.engine,bytes,(size_t)got); }
   else if(!got || (errno!=EAGAIN && errno!=EINTR)) { a16_owner_lost(&g.engine); stopping=1; }
  }
  if(g.ownerfd>=0) {
   struct pollfd owner={.fd=g.ownerfd,.events=POLLIN}; int result=poll(&owner,1,0);
   if(result<0 && errno!=EINTR) { a16_owner_lost(&g.engine); stopping=1; }
   if(result>0 && owner.revents) {
    a16_owner_lost(&g.engine); epoll_ctl(g.epoll,EPOLL_CTL_DEL,g.ownerfd,NULL);
    close(g.ownerfd); g.ownerfd=-1;
   }
  }
  a16_time(&g.engine,a16_now()); a16_tick(&g.engine,uart_write,&g);
  interest(&g,g.uart,EPOLLIN|((g.engine.tx_busy && g.engine.now>=g.engine.resync_after)?EPOLLOUT:0));
 }
 a16_owner_lost(&g.engine); close(g.uart); close(g.listener); close(g.timer); close(g.epoll);
 if(g.ownerfd>=0) close(g.ownerfd);
 for(i=0;i<CLIENTS;i++) if(g.clients[i].fd>=0) close(g.clients[i].fd);
 assert(!unlink(A16_SOCKET)); return 0;
}
#endif
