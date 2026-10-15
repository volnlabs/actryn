// SPDX-License-Identifier: GPL-2.0-only
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stddef.h>
#include <stdbool.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include "../include/uapi/linux/actryn_authority.h"
#define MS 1000000ULL
static int adminfd, runtimefd, observefd, eventsfd;
static struct actryn_status status;
static unsigned long long obsid;
static void deny_exec(void)
{
 struct sock_filter code[]={
  BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,nr)),
  BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,__NR_execve,2,0),
  BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,__NR_execveat,1,0),
  BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW),
  BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ERRNO|EPERM),
 };
 struct sock_fprog program={.len=sizeof(code)/sizeof(code[0]),.filter=code};
 assert(!prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0));
 assert(!prctl(PR_SET_SECCOMP,SECCOMP_MODE_FILTER,&program));
}
static unsigned long long now(void)
{ struct timespec t; assert(!clock_gettime(CLOCK_BOOTTIME,&t)); return t.tv_sec*1000000000ULL+t.tv_nsec; }
static void query(void) { assert(!ioctl(adminfd,ACTRYN_IOCTL_STATUS,&status)); }
static struct actryn_request request(unsigned int op)
{ struct actryn_request r={.version=1,.opcode=op}; return r; }
static void submit(int fd,struct actryn_request *r)
{ if(ioctl(fd,ACTRYN_IOCTL_REQUEST,r)) { fprintf(stderr,"opcode %u: %s\n",r->opcode,strerror(errno)); exit(1); } }
static void health(void)
{ struct actryn_request r=request(ACTRYN_HEALTH); query(); memcpy(r.runtime_nonce,status.runtime_nonce,16); r.deadline_ns=now()+1500*MS; submit(runtimefd,&r); }
static void drain(void)
{ struct actryn_event e; while(read(eventsfd,&e,sizeof(e))>0) {} assert(errno==EAGAIN); }
static void wait_for(unsigned int state,unsigned int opstate)
{
 unsigned long long end=now()+1800*MS; struct timespec delay={.tv_nsec=10000000};
 do { query(); drain(); if(status.state==state && status.operation_state==opstate) return;
  if(status.state==ACTRYN_FAULT_LATCHED) break;
  health(); nanosleep(&delay,NULL);
 } while(now()<end);
 fprintf(stderr,"wait wanted state%u/op%u got state%u/op%u reason%u\n",state,opstate,status.state,status.operation_state,status.reason); exit(1);
}
static int bind_role(unsigned int role)
{ int fd=open(ACTRYN_DEVICE,O_RDWR|O_NONBLOCK); struct actryn_request r=request(ACTRYN_BIND); assert(fd>=0); r.role=role; submit(fd,&r); return fd; }
static void observe(void)
{
 struct actryn_request r=request(ACTRYN_OBSERVE); query(); memcpy(r.runtime_nonce,status.runtime_nonce,16);
 r.observation=++obsid; r.context_revision=1; r.acquired_earliest_ns=now()-MS;
 r.acquired_latest_ns=now(); r.valid_until_ns=now()+900*MS; submit(observefd,&r);
}
static struct actryn_request allocate(void)
{
 struct actryn_request r=request(ACTRYN_ALLOCATE); observe(); query();
 memcpy(r.runtime_nonce,status.runtime_nonce,16); r.grant=status.grant; r.instance=status.instance;
 r.deadline_ns=now()+2000*MS; r.observation=obsid; r.context_revision=1;
 submit(runtimefd,&r); assert(r.operation && r.stream); return r;
}
static struct actryn_request op_request(unsigned int op)
{
 struct actryn_request r=request(op); query(); memcpy(r.runtime_nonce,status.runtime_nonce,16);
 r.grant=status.grant; r.operation=status.operation; r.stream=status.stream; return r;
}
static void grant(bool activate)
{
 struct actryn_request r=request(ACTRYN_GRANT);
 r.instance=1; r.deadline_ns=now()+15000*MS; submit(adminfd,&r);
 health(); query();
 if(activate) {
  r=request(ACTRYN_ACTIVATE); memcpy(r.runtime_nonce,status.runtime_nonce,16);
  r.grant=status.grant; r.instance=1; submit(runtimefd,&r);
 }
}
static void revoke_reject_activation(void)
{
 struct actryn_request old=request(ACTRYN_ACTIVATE),r=request(ACTRYN_REVOKE);
 query(); memcpy(old.runtime_nonce,status.runtime_nonce,16); old.grant=status.grant; old.instance=status.instance;
 memcpy(r.runtime_nonce,status.runtime_nonce,16); r.grant=status.grant; submit(adminfd,&r);
 errno=0; assert(ioctl(runtimefd,ACTRYN_IOCTL_REQUEST,&old)==-1 && errno==EPERM);
 query(); assert(status.state==ACTRYN_READY && !(status.flags&ACTRYN_STATUS_GRANT_AUTHORIZED));
}
static void reject_stale_horizons(void)
{
 struct actryn_request r=request(ACTRYN_HEALTH),sample;
 query(); memcpy(r.runtime_nonce,status.runtime_nonce,16);
 r.deadline_ns=now()+200*MS; submit(runtimefd,&r); observe();
 sample=op_request(ACTRYN_SAMPLE); sample.sequence=1; sample.observation=obsid;
 sample.context_revision=1; sample.deadline_ns=now()+400*MS;
 errno=0; assert(ioctl(runtimefd,ACTRYN_IOCTL_REQUEST,&sample)==-1 && errno==EINVAL);
 health();
 r=request(ACTRYN_OBSERVE); memcpy(r.runtime_nonce,status.runtime_nonce,16);
 r.observation=++obsid; r.context_revision=1; r.acquired_earliest_ns=now()-900*MS;
 r.acquired_latest_ns=r.acquired_earliest_ns; r.valid_until_ns=now()+900*MS;
 submit(observefd,&r);
 sample.observation=obsid; sample.deadline_ns=now()+400*MS;
 errno=0; assert(ioctl(runtimefd,ACTRYN_IOCTL_REQUEST,&sample)==-1 && errno==EINVAL);
 observe();
}
int main(void)
{
 struct actryn_request r, allocation, sample; struct timespec step={.tv_nsec=120000000};
 unsigned int i; pid_t child; int w;
 deny_exec();
 adminfd=bind_role(ACTRYN_ADMIN); runtimefd=bind_role(ACTRYN_RUNTIME);
 observefd=bind_role(ACTRYN_ACQUISITION); eventsfd=bind_role(ACTRYN_EVENTS);
 errno=0; execl("/bin/true","true",(char *)NULL); assert(errno==EPERM);
 r=request(ACTRYN_HANDSHAKE); submit(adminfd,&r);
 for(i=0;i<100;i++) { struct timespec d={.tv_nsec=10000000}; query(); drain(); if(status.controller_session) break; nanosleep(&d,NULL); }
 assert(status.controller_session && status.state==ACTRYN_INHIBITED);
 r=request(ACTRYN_REARM); submit(adminfd,&r); wait_for(ACTRYN_READY,ACTRYN_OP_NONE);
 grant(false); revoke_reject_activation();
 grant(true); revoke_reject_activation();
 grant(true);
 for(i=0;i<2;i++) {
  allocation=allocate(); query(); assert(status.operation_state==ACTRYN_OP_ALLOCATED);
  r=allocation; r.opcode=ACTRYN_START; submit(runtimefd,&r); wait_for(ACTRYN_ACTIVE,ACTRYN_OP_RUNNING);
  reject_stale_horizons();
  nanosleep(&step,NULL); observe(); sample=op_request(ACTRYN_SAMPLE);
  sample.sequence=1; sample.observation=obsid; sample.context_revision=1;
  sample.deadline_ns=now()+400*MS; sample.left_permille=100; sample.right_permille=100;
  submit(runtimefd,&sample);
  child=fork(); assert(child>=0); if(!child) { errno=0; _exit(ioctl(runtimefd,ACTRYN_IOCTL_REQUEST,&sample)==-1 && errno==EPERM?0:1); }
  assert(waitpid(child,&w,0)==child && WIFEXITED(w) && !WEXITSTATUS(w));
  nanosleep(&step,NULL); health(); query(); assert(status.sequence==1);
  submit(runtimefd,&sample); sample.left_permille=99; errno=0;
  assert(ioctl(runtimefd,ACTRYN_IOCTL_REQUEST,&sample)==-1 && errno==EEXIST);
  r=op_request(ACTRYN_FINISH); submit(runtimefd,&r);
  /* Closing retains occupation; the later allocation is admitted only after its barrier. */
  wait_for(ACTRYN_ACTIVE,ACTRYN_OP_RECONCILED); assert(status.reason==ACTRYN_SKILL_FINISHED);
 }
 revoke_reject_activation(); grant(true);
 allocation=allocate(); r=op_request(ACTRYN_CANCEL); submit(runtimefd,&r);
 wait_for(ACTRYN_ACTIVE,ACTRYN_OP_RECONCILED);
 allocation.opcode=ACTRYN_START; errno=0;
 assert(ioctl(runtimefd,ACTRYN_IOCTL_REQUEST,&allocation)==-1 && errno==ESTALE);
 r=request(ACTRYN_HEALTH); r.reserved[0]=1; errno=0;
 assert(ioctl(runtimefd,ACTRYN_IOCTL_REQUEST,&r)==-1 && errno==EINVAL);
 allocation=allocate(); r=allocation; r.opcode=ACTRYN_START; submit(runtimefd,&r);
 wait_for(ACTRYN_ACTIVE,ACTRYN_OP_RUNNING);
 for(i=0;i<300;i++) {
  struct timespec d={.tv_nsec=10000000}; query(); drain();
  if(status.state==ACTRYN_FAULT_LATCHED) break;
  health(); nanosleep(&d,NULL);
 }
 assert(status.state==ACTRYN_FAULT_LATCHED && status.operation_state==ACTRYN_OP_UNKNOWN);
 assert(status.reason==ACTRYN_EXPIRED || status.reason==ACTRYN_TRANSPORT);
 r=request(ACTRYN_REVOKE); memcpy(r.runtime_nonce,status.runtime_nonce,16); r.grant=status.grant;
 submit(adminfd,&r); query(); assert(status.state==ACTRYN_FAULT_LATCHED);
 r=op_request(ACTRYN_CANCEL); submit(runtimefd,&r); query();
 assert(status.state==ACTRYN_FAULT_LATCHED && status.operation_state==ACTRYN_OP_UNKNOWN);
 puts("authority: two completions, allocated cancellation, stale START, duplicate mutation, forked FD, exec denial, malformed UAPI, revoke non-resurrection, sample horizons and expiry passed");
 close(runtimefd); close(observefd); close(eventsfd); close(adminfd); return 0;
}
