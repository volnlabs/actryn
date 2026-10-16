// SPDX-License-Identifier: GPL-2.0-only
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <sys/utsname.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include "../include/uapi/linux/actryn_authority.h"
#define MS 1000000ULL
struct handles { int admin, runtime, events, acquisition; };
static unsigned long long observation;
static struct actryn_request last_observation,last_health;
static struct actryn_event recent_events[16];
static unsigned int recent_event_count;
static unsigned long long now(void)
{ struct timespec t; assert(!clock_gettime(CLOCK_BOOTTIME,&t)); return t.tv_sec*1000000000ULL+t.tv_nsec; }
static void pause_ms(long ms)
{ struct timespec t={.tv_sec=ms/1000,.tv_nsec=(ms%1000)*1000000}; while(nanosleep(&t,&t)) assert(errno==EINTR); }
static struct actryn_request req(unsigned int opcode)
{ struct actryn_request r={.version=1,.opcode=opcode}; return r; }
static struct actryn_status status(int fd)
{ struct actryn_status s; assert(!ioctl(fd,ACTRYN_IOCTL_STATUS,&s)); return s; }
static void submit(int fd,struct actryn_request *r)
{ if(ioctl(fd,ACTRYN_IOCTL_REQUEST,r)) { fprintf(stderr,"opcode %u: %s\n",r->opcode,strerror(errno)); abort(); } }
static int bind_role(unsigned int role)
{ struct actryn_request r=req(ACTRYN_BIND); int fd=open(ACTRYN_DEVICE,O_RDWR|O_NONBLOCK); assert(fd>=0); r.role=role; submit(fd,&r); return fd; }
static void deny_exec(void)
{
 struct sock_filter code[]={
  BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,nr)),
  BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,__NR_execve,2,0),
  BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,__NR_execveat,1,0),
  BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW),
  BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ERRNO|EPERM),
 };
 struct sock_fprog p={.len=sizeof(code)/sizeof(code[0]),.filter=code};
 assert(!prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0)); assert(!prctl(PR_SET_SECCOMP,SECCOMP_MODE_FILTER,&p));
}
static void guard_guest(void)
{
 struct utsname u; char compatible[512]={0}; int fd; ssize_t n; size_t at=0; bool qemu=false;
 assert(!uname(&u)); assert(!strcmp(u.machine,"aarch64"));
 assert(!strcmp(u.release,"6.12.111+deb13-arm64")); assert(geteuid()==0);
 fd=open("/proc/device-tree/compatible",O_RDONLY); assert(fd>=0);
 n=read(fd,compatible,sizeof(compatible)-1); assert(n>0); close(fd);
 while(at<(size_t)n) { if(!strcmp(compatible+at,"linux,dummy-virt")) qemu=true; at+=strlen(compatible+at)+1; }
 assert(qemu);
}
static void drain(int fd)
{
 struct actryn_event e;
 while(read(fd,&e,sizeof(e))==(ssize_t)sizeof(e))
  recent_events[recent_event_count++%16]=e;
 assert(errno==EAGAIN);
}
static void diagnostic(const char *stage,struct actryn_status s,unsigned long long test_deadline)
{
 unsigned int i,first=recent_event_count>16?recent_event_count-16:0;
 fprintf(stderr,"%s: state=%u operation_state=%u reason=%u flags=%u lost=%u now=%llu grant_deadline=%llu test_deadline=%llu boot=%llu session=%llu grant=%llu operation=%llu stream=%llu transaction=%llu controller_ns=%llu\n",
  stage,s.state,s.operation_state,s.reason,s.flags,s.events_lost,(unsigned long long)s.now_ns,
  (unsigned long long)s.deadline_ns,test_deadline,(unsigned long long)s.controller_boot,
  (unsigned long long)s.controller_session,(unsigned long long)s.grant,(unsigned long long)s.operation,
  (unsigned long long)s.stream,(unsigned long long)s.transaction,(unsigned long long)s.controller_ns);
 for(i=first;i<recent_event_count;i++) {
  const struct actryn_event *e=&recent_events[i%16];
  fprintf(stderr,"event sequence=%llu captured_ns=%llu kind=0x%x state=%u operation_state=%u reason=%u flags=%u transaction=%llu\n",
   (unsigned long long)e->sequence,(unsigned long long)e->captured_ns,e->kind,
   e->status.state,e->status.operation_state,e->status.reason,e->status.flags,
   (unsigned long long)e->status.transaction);
 }
}
static void health(struct handles *h)
{
 struct actryn_request r=req(ACTRYN_HEALTH); struct actryn_status s=status(h->admin);
 memcpy(r.runtime_nonce,s.runtime_nonce,16); r.deadline_ns=now()+1500*MS; submit(h->runtime,&r);
 last_health=r;
}
static struct actryn_status await_state(struct handles *h,unsigned int state,unsigned int op,bool refresh)
{
 unsigned long long end=now()+2000*MS; struct actryn_status s;
 do {
  s=status(h->admin); drain(h->events);
  if(s.state==state && s.operation_state==op) return s;
  if(s.state==ACTRYN_FAULT_LATCHED && state!=ACTRYN_FAULT_LATCHED) break;
  if(refresh) health(h);
  pause_ms(5);
 } while(now()<end);
 fprintf(stderr,"wanted %u/%u\n",state,op); diagnostic("state wait failed",s,end); abort();
}
static struct handles start(void)
{
 struct handles h; struct actryn_request r; struct actryn_status s; unsigned long long end;
 deny_exec(); h.admin=bind_role(ACTRYN_ADMIN); h.runtime=bind_role(ACTRYN_RUNTIME);
 h.events=bind_role(ACTRYN_EVENTS); h.acquisition=bind_role(ACTRYN_ACQUISITION);
 r=req(ACTRYN_HANDSHAKE); submit(h.admin,&r); end=now()+1500*MS;
 do { s=status(h.admin); drain(h.events); if(s.flags&ACTRYN_STATUS_HANDSHAKEN) break; pause_ms(2); } while(now()<end);
 if(!(s.flags&ACTRYN_STATUS_HANDSHAKEN)) { diagnostic("handshake failed",s,end); abort(); }
 r=req(ACTRYN_REARM); submit(h.admin,&r);
 await_state(&h,ACTRYN_READY,ACTRYN_OP_NONE,false);
 r=req(ACTRYN_GRANT); r.instance=1; r.deadline_ns=now()+15000*MS; submit(h.admin,&r);
 health(&h); s=status(h.admin); r=req(ACTRYN_ACTIVATE);
 memcpy(r.runtime_nonce,s.runtime_nonce,16); r.grant=s.grant; r.instance=s.instance; submit(h.runtime,&r);
 return h;
}
static struct actryn_request allocate(struct handles *h,unsigned long long duration)
{
 struct actryn_status s=status(h->admin); struct actryn_request r=req(ACTRYN_OBSERVE);
 memcpy(r.runtime_nonce,s.runtime_nonce,16); r.observation=++observation; r.context_revision=1;
 r.acquired_earliest_ns=now()-MS; r.acquired_latest_ns=now(); r.valid_until_ns=now()+900*MS;
 submit(h->acquisition,&r); last_observation=r;
 r=req(ACTRYN_ALLOCATE); memcpy(r.runtime_nonce,s.runtime_nonce,16);
 r.grant=s.grant; r.instance=s.instance; r.observation=observation; r.context_revision=1;
 r.deadline_ns=now()+duration; submit(h->runtime,&r); return r;
}
static unsigned long long begin(struct handles *h,unsigned long long duration)
{ struct actryn_request r=allocate(h,duration); r.opcode=ACTRYN_START; submit(h->runtime,&r); await_state(h,ACTRYN_ACTIVE,ACTRYN_OP_RUNNING,true); return r.deadline_ns; }
static struct actryn_request operation(struct handles *h,unsigned int opcode)
{
 struct actryn_status s=status(h->admin); struct actryn_request r=req(opcode);
 memcpy(r.runtime_nonce,s.runtime_nonce,16); r.grant=s.grant; r.operation=s.operation; r.stream=s.stream; return r;
}
static void finish_handles(struct handles *h)
{ close(h->runtime); close(h->acquisition); close(h->events); close(h->admin); }
static void send_fd(int socket,int fd)
{
 char byte='F',control[CMSG_SPACE(sizeof(fd))]={0}; struct iovec io={.iov_base=&byte,.iov_len=1};
 struct msghdr msg={.msg_iov=&io,.msg_iovlen=1,.msg_control=control,.msg_controllen=sizeof(control)};
 struct cmsghdr *c=CMSG_FIRSTHDR(&msg); c->cmsg_level=SOL_SOCKET; c->cmsg_type=SCM_RIGHTS; c->cmsg_len=CMSG_LEN(sizeof(fd));
 memcpy(CMSG_DATA(c),&fd,sizeof(fd)); assert(sendmsg(socket,&msg,0)==1);
}
static int receive_fd(int socket)
{
 char byte,control[CMSG_SPACE(sizeof(int))]={0}; struct iovec io={.iov_base=&byte,.iov_len=1}; int fd;
 struct msghdr msg={.msg_iov=&io,.msg_iovlen=1,.msg_control=control,.msg_controllen=sizeof(control)};
 struct cmsghdr *c; assert(recvmsg(socket,&msg,0)==1 && byte=='F'); assert(!(msg.msg_flags&MSG_CTRUNC));
 c=CMSG_FIRSTHDR(&msg); assert(c && c->cmsg_level==SOL_SOCKET && c->cmsg_type==SCM_RIGHTS && c->cmsg_len==CMSG_LEN(sizeof(fd)));
 memcpy(&fd,CMSG_DATA(c),sizeof(fd)); return fd;
}
static void wait_child(pid_t child)
{ int w; assert(waitpid(child,&w,0)==child && WIFEXITED(w) && WEXITSTATUS(w)==0); }
static void duplicate_fd(void)
{
 struct handles h=start(); int other=dup(h.runtime); struct actryn_status s;
 assert(other>=0); close(h.runtime); h.runtime=other; health(&h);
 s=status(h.admin); assert(s.state==ACTRYN_ACTIVE);
 close(h.runtime); h.runtime=-1;
 s=await_state(&h,ACTRYN_FAULT_LATCHED,ACTRYN_OP_NONE,false); assert(s.reason==ACTRYN_OWNER_LOST);
 finish_handles(&h);
}
static void inhibited_revoke(void)
{
 int adminfd,runtimefd,result; struct actryn_status s; struct actryn_request r=req(ACTRYN_REVOKE);
 deny_exec(); adminfd=bind_role(ACTRYN_ADMIN); runtimefd=bind_role(ACTRYN_RUNTIME);
 s=status(adminfd); assert(s.state==ACTRYN_INHIBITED && s.grant==0);
 memcpy(r.runtime_nonce,s.runtime_nonce,16); r.grant=s.grant;
 errno=0; result=ioctl(adminfd,ACTRYN_IOCTL_REQUEST,&r); s=status(adminfd);
 printf("inhibited REVOKE result=%d errno=%d state=%u flags=%u grant=%llu\n",
  result,errno,s.state,s.flags,(unsigned long long)s.grant); fflush(stdout);
 /* Revoking absent authority must never bypass baseline reconciliation. */
 assert(s.state==ACTRYN_INHIBITED);
 close(runtimefd); close(adminfd);
}
static void rights_transfer(void)
{
 struct handles h=start(); int pair[2]; pid_t child;
 assert(!socketpair(AF_UNIX,SOCK_SEQPACKET,0,pair)); child=fork(); assert(child>=0);
 if(!child) {
  int received; struct actryn_status s; struct actryn_request r=req(ACTRYN_HEALTH);
  close(pair[0]); finish_handles(&h); received=receive_fd(pair[1]); s=status(received);
  memcpy(r.runtime_nonce,s.runtime_nonce,16); r.deadline_ns=now()+1000*MS;
  errno=0; assert(ioctl(received,ACTRYN_IOCTL_REQUEST,&r)==-1 && errno==EPERM);
  close(received); close(pair[1]); _exit(0);
 }
 close(pair[1]); send_fd(pair[0],h.runtime); wait_child(child); close(pair[0]);
 health(&h); assert(status(h.admin).state==ACTRYN_ACTIVE); finish_handles(&h);
}
static void ready_recovery(void)
{
 struct handles h=start(); struct actryn_status first=status(h.admin),second;
 /* No reset, unload, or fixture admin action between these lifetimes. */
 finish_handles(&h); h=start(); second=status(h.admin);
 assert(second.controller_boot==first.controller_boot);
 assert(second.controller_session>first.controller_session);
 assert(memcmp(second.runtime_nonce,first.runtime_nonce,16));
 printf("fresh READY recovery boot=%llu sessions=%llu->%llu\n",
  (unsigned long long)first.controller_boot,(unsigned long long)first.controller_session,
  (unsigned long long)second.controller_session);
 finish_handles(&h);
}
static void owner_exit(void)
{
 int pair[2],retained,adminfd; pid_t child; char byte='Q'; struct actryn_status s; unsigned long long end;
 assert(!socketpair(AF_UNIX,SOCK_SEQPACKET,0,pair)); child=fork(); assert(child>=0);
 if(!child) {
  struct handles h; close(pair[0]); h=start(); begin(&h,5000*MS); send_fd(pair[1],h.runtime);
  assert(read(pair[1],&byte,1)==1); _exit(0);
 }
 close(pair[1]); retained=receive_fd(pair[0]); adminfd=bind_role(ACTRYN_ADMIN);
 assert(status(adminfd).state==ACTRYN_ACTIVE); assert(write(pair[0],&byte,1)==1); wait_child(child);
 end=now()+1500*MS;
 do { s=status(adminfd); if(s.state==ACTRYN_FAULT_LATCHED) break; pause_ms(5); } while(now()<end);
 assert(s.state==ACTRYN_FAULT_LATCHED && s.reason==ACTRYN_OWNER_LOST && s.operation_state==ACTRYN_OP_UNKNOWN);
 assert(status(retained).state==ACTRYN_FAULT_LATCHED); close(retained); close(adminfd); close(pair[0]);
}
static void sysfs_binding(const char *action,const char *binding)
{
 char path[192]; int fd; size_t len=strlen(binding);
 assert(len && len<64 && !strspn(binding,"/") && !strchr(binding,'/') && !strchr(binding,'.'));
 assert(snprintf(path,sizeof(path),"/sys/bus/serial/drivers/actryn-authority/%s",action)>0);
 fd=open(path,O_WRONLY); assert(fd>=0); assert(write(fd,binding,len)==(ssize_t)len); close(fd);
}
static void unbind_rebind(const char *binding)
{
 struct handles h=start(); struct actryn_request r; int fresh;
 begin(&h,5000*MS); r=operation(&h,ACTRYN_CANCEL);
 sysfs_binding("unbind",binding);
 assert(status(h.admin).state==ACTRYN_DETACHED); assert(status(h.runtime).state==ACTRYN_DETACHED);
 errno=0; assert(ioctl(h.runtime,ACTRYN_IOCTL_REQUEST,&r)==-1 && errno==ENODEV);
 sysfs_binding("bind",binding); fresh=bind_role(ACTRYN_ADMIN);
 assert(status(fresh).state==ACTRYN_INHIBITED && status(fresh).operation_state==ACTRYN_OP_NONE);
 assert(status(h.admin).state==ACTRYN_DETACHED);
 errno=0; assert(ioctl(h.runtime,ACTRYN_IOCTL_REQUEST,&r)==-1 && errno==ENODEV);
 close(fresh); finish_handles(&h);
}
static void event_capacity(void)
{
 struct handles h=start(); struct actryn_status s; struct actryn_event e; unsigned int i,count=0;
 unsigned long long sequence=0; begin(&h,5000*MS); drain(h.events);
 for(i=0;i<400;i++) { health(&h); s=status(h.admin); if(s.state==ACTRYN_FAULT_LATCHED) break; }
 assert(i<400 && s.reason==ACTRYN_EVIDENCE_LOST && s.events_lost>0 && s.operation_state==ACTRYN_OP_UNKNOWN);
 while(read(h.events,&e,sizeof(e))==(ssize_t)sizeof(e)) {
  /* A pending closure event can arrive while this consumer frees slots. */
  assert(e.sequence>sequence); sequence=e.sequence; assert(++count<=512);
 }
 assert(errno==EAGAIN && count>0); assert(!(status(h.admin).flags&ACTRYN_STATUS_GRANT_AUTHORIZED));
 finish_handles(&h);
}
static void fixture_control(const char *command)
{ char answer; printf("CONTROL %s\n",command); fflush(stdout); assert(read(STDIN_FILENO,&answer,1)==1 && answer=='Y'); }
static void repeated_revoke(bool escalate)
{
 struct handles h=start(); struct actryn_request r; struct actryn_status s;
 unsigned long long end,barrier_transaction; unsigned int i;
 begin(&h,5000*MS); fixture_control("delay 250000000");
 r=operation(&h,escalate?ACTRYN_CANCEL:ACTRYN_REVOKE);
 if(!escalate) { r.operation=0; r.stream=0; }
 submit(escalate?h.runtime:h.admin,&r); end=now()+200*MS;
 do {
  s=status(h.admin); drain(h.events);
  if(s.flags&ACTRYN_STATUS_AWAITING) break;
  if(s.state==ACTRYN_FAULT_LATCHED) break;
  pause_ms(1);
 } while(now()<end);
 if(!(s.flags&ACTRYN_STATUS_AWAITING)) { diagnostic("barrier never pending",s,end); abort(); }
 barrier_transaction=s.transaction;
 r=operation(&h,ACTRYN_REVOKE); r.operation=0; r.stream=0;
 for(i=0;i<10;i++) { submit(h.admin,&r); drain(h.events); pause_ms(5); }
 s=await_state(&h,ACTRYN_READY,ACTRYN_OP_RECONCILED,true);
 assert(s.reason==ACTRYN_GRANT_REVOKED);
 assert(s.transaction==barrier_transaction);
 assert(!(s.flags&ACTRYN_STATUS_GRANT_AUTHORIZED));
 assert(!s.left_permille && !s.right_permille);
 fixture_control("delay 0"); fixture_control("replay"); pause_ms(30);
 s=status(h.admin); assert(s.state==ACTRYN_READY && s.operation_state==ACTRYN_OP_RECONCILED);
 printf("one immutable QUIESCE transaction=%llu across repeated revoke%s\n",
  barrier_transaction,escalate?" after cancel":"");
 finish_handles(&h);
}
static void controller_restart(void)
{
 struct handles h=start(); struct actryn_request r; struct actryn_status original,s;
 unsigned long long end,before_restart,after_restart,submitted;
 int error;
 begin(&h,5000*MS); original=status(h.admin); before_restart=now();
 fprintf(stderr,"restart before_ns=%llu observation=%llu acquired_earliest_ns=%llu acquired_latest_ns=%llu valid_until_ns=%llu health_deadline_ns=%llu\n",
  before_restart,(unsigned long long)last_observation.observation,
  (unsigned long long)last_observation.acquired_earliest_ns,
  (unsigned long long)last_observation.acquired_latest_ns,
  (unsigned long long)last_observation.valid_until_ns,(unsigned long long)last_health.deadline_ns);
 diagnostic("before fixture restart",original,0);
 fixture_control("restart"); after_restart=now();
 r=operation(&h,ACTRYN_SAMPLE); r.sequence=1; r.observation=observation;
 r.context_revision=1; r.deadline_ns=now()+300*MS;
 submitted=now();
 fprintf(stderr,"restart after_ns=%llu elapsed_ns=%llu sample_submit_ns=%llu grant=%llu operation=%llu stream=%llu sequence=%llu observation=%llu context=%llu deadline_ns=%llu duties=%d,%d\n",
  after_restart,after_restart-before_restart,submitted,(unsigned long long)r.grant,
  (unsigned long long)r.operation,(unsigned long long)r.stream,(unsigned long long)r.sequence,
  (unsigned long long)r.observation,(unsigned long long)r.context_revision,
  (unsigned long long)r.deadline_ns,r.left_permille,r.right_permille);
 if(ioctl(h.runtime,ACTRYN_IOCTL_REQUEST,&r)) {
  error=errno; s=status(h.admin); drain(h.events);
  fprintf(stderr,"restart sample rejected: errno=%d (%s) returned_ns=%llu\n",error,strerror(error),now());
  diagnostic("after rejected restart sample",s,r.deadline_ns); abort();
 }
 /* A newer controller epoch must close authority on receipt, rather than
  * waiting for the one-second missing-receipt timeout. This is a test timeout,
  * not a measured or guaranteed scheduling bound. */
 end=now()+500*MS;
 do { s=status(h.admin); drain(h.events); if(s.state==ACTRYN_FAULT_LATCHED) break; pause_ms(5); } while(now()<end);
 if(s.state!=ACTRYN_FAULT_LATCHED) { diagnostic("controller reset not closed",s,end); abort(); }
 assert(s.reason==ACTRYN_TRANSPORT && s.operation_state==ACTRYN_OP_UNKNOWN);
 assert(!(s.flags&ACTRYN_STATUS_GRANT_AUTHORIZED));
 assert(s.controller_boot==original.controller_boot && s.controller_session==original.controller_session);
 assert(s.operation==original.operation && s.stream==original.stream);
 fixture_control("replay"); pause_ms(100); s=status(h.admin);
 assert(s.state==ACTRYN_FAULT_LATCHED && s.operation_state==ACTRYN_OP_UNKNOWN);
 finish_handles(&h);
}
static void delayed_fixture(bool barrier,bool expire)
{
 struct handles h=start(); struct actryn_request r; struct actryn_status s; unsigned long long end,operation_end;
 operation_end=begin(&h,barrier && expire?300*MS:5000*MS);
 fixture_control(barrier && !expire?"delay 250000000":"delay 600000000");
 s=status(h.admin); assert(s.state==ACTRYN_ACTIVE && s.operation_state==ACTRYN_OP_RUNNING);
 assert(now()+50*MS<operation_end);
 r=operation(&h,barrier?ACTRYN_FINISH:ACTRYN_SAMPLE);
 if(!barrier) { r.sequence=1; r.observation=observation; r.context_revision=1; r.deadline_ns=now()+150*MS; }
 submit(h.runtime,&r);
 if(barrier && !expire) {
  struct actryn_request next=req(ACTRYN_ALLOCATE); s=status(h.admin);
  memcpy(next.runtime_nonce,s.runtime_nonce,16); next.grant=s.grant; next.instance=s.instance;
  next.observation=observation; next.context_revision=1; next.deadline_ns=now()+3000*MS;
  errno=0; assert(ioctl(h.runtime,ACTRYN_IOCTL_REQUEST,&next)==-1 && errno==EINVAL);
  await_state(&h,ACTRYN_ACTIVE,ACTRYN_OP_RECONCILED,true);
  fixture_control("delay 0"); next=allocate(&h,3000*MS); assert(next.operation>r.operation);
 } else {
  s=await_state(&h,ACTRYN_FAULT_LATCHED,ACTRYN_OP_UNKNOWN,true); assert(s.reason==ACTRYN_EXPIRED);
  /* Wait beyond the delayed receipt and replay once; neither may reconcile. */
  end=now()+800*MS; do { pause_ms(10); s=status(h.admin); drain(h.events); assert(s.state==ACTRYN_FAULT_LATCHED && s.operation_state==ACTRYN_OP_UNKNOWN); } while(now()<end);
  fixture_control("delay 0"); fixture_control("replay"); pause_ms(100);
  s=status(h.admin); assert(s.state==ACTRYN_FAULT_LATCHED && s.operation_state==ACTRYN_OP_UNKNOWN);
 }
 finish_handles(&h);
}
int main(int argc,char **argv)
{
 assert(argc==2 || argc==3); guard_guest(); alarm(20);
 if(!strcmp(argv[1],"dup")) duplicate_fd();
 else if(!strcmp(argv[1],"inhibited-revoke")) inhibited_revoke();
 else if(!strcmp(argv[1],"rights")) rights_transfer();
 else if(!strcmp(argv[1],"ready-recovery")) ready_recovery();
 else if(!strcmp(argv[1],"owner-exit")) owner_exit();
 else if(!strcmp(argv[1],"unbind-rebind") && argc==3) unbind_rebind(argv[2]);
 else if(!strcmp(argv[1],"event-capacity")) event_capacity();
 else if(!strcmp(argv[1],"late-sample")) delayed_fixture(false,true);
 else if(!strcmp(argv[1],"late-barrier")) delayed_fixture(true,true);
 else if(!strcmp(argv[1],"delayed-handoff")) delayed_fixture(true,false);
 else if(!strcmp(argv[1],"controller-restart")) controller_restart();
 else if(!strcmp(argv[1],"repeated-revoke")) repeated_revoke(false);
 else if(!strcmp(argv[1],"cancel-revoke")) repeated_revoke(true);
 else { fputs("unknown scenario\n",stderr); return 2; }
 printf("PASS authority scenario %s\n",argv[1]); return 0;
}
