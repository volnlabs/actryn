// SPDX-License-Identifier: GPL-2.0-only
/* Fixed additional lifetime cases, sharing the existing suite's exact setup.
 * No module loading, PID churn, namespace alias, or retry fallback is hidden
 * here. The target guard runs before either actual authority scenario. */
#define _GNU_SOURCE
#define main authority_adversarial_main
#include "authority_adversarial.c"
#undef main
#include <linux/sched.h>
#include <linux/nsfs.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <sys/stat.h>

static bool owner_terminal(struct actryn_status s,struct actryn_status before)
{
 return s.state==ACTRYN_FAULT_LATCHED && s.reason==ACTRYN_OWNER_LOST &&
  s.operation_state==ACTRYN_OP_UNKNOWN && s.flags==0 &&
  s.grant==before.grant && s.instance==before.instance &&
  s.operation==before.operation && s.stream==before.stream &&
  s.controller_boot==before.controller_boot && s.controller_session==before.controller_session &&
  !memcmp(s.runtime_nonce,before.runtime_nonce,sizeof(s.runtime_nonce)) &&
  !memcmp(s.device_identity,before.device_identity,sizeof(s.device_identity)) &&
  s.left_permille==before.left_permille && s.right_permille==before.right_permille;
}
static struct actryn_status wait_owner_terminal(int fd,int events,struct actryn_status before)
{
 unsigned long long end=now()+1500*MS; struct actryn_status s;
 do {
  if(events>=0) drain(events);
  s=status(fd);
  if(s.state==ACTRYN_FAULT_LATCHED) break;
  pause_ms(2);
 } while(now()<end);
 diagnostic("owner lifetime terminal",s,end);
 assert(owner_terminal(s,before)); return s;
}
static void denied_runtime(int fd,struct actryn_status before)
{
 struct actryn_request r=req(ACTRYN_HEALTH); int result,error;
 memcpy(r.runtime_nonce,before.runtime_nonce,sizeof(r.runtime_nonce));
 r.deadline_ns=now()+500*MS; errno=0;
 result=ioctl(fd,ACTRYN_IOCTL_REQUEST,&r); error=errno;
 printf("retained HEALTH result=%d errno=%d tgid=%ld tid=%ld\n",
  result,error,(long)getpid(),syscall(SYS_gettid));
 assert(result==-1 && error==EPERM);
 r=req(ACTRYN_ACTIVATE); memcpy(r.runtime_nonce,before.runtime_nonce,sizeof(r.runtime_nonce));
 r.grant=before.grant; r.instance=before.instance; errno=0;
 result=ioctl(fd,ACTRYN_IOCTL_REQUEST,&r); error=errno;
 printf("retained ACTIVATE result=%d errno=%d\n",result,error);
 assert(result==-1 && error==EPERM); fflush(stdout);
}
struct leader_case {
 pthread_t leader;
 pthread_mutex_t lock;
 pthread_cond_t changed;
 bool exit_leader;
 struct handles handles;
 int socket;
};
static void *surviving_thread(void *opaque)
{
 struct leader_case *c=opaque; char byte; struct actryn_status before;
 /* Prove that a live sibling is initially the same authorized owner. */
 health(&c->handles); before=status(c->handles.admin);
 assert(before.state==ACTRYN_ACTIVE && before.operation_state==ACTRYN_OP_RUNNING);
 send_fd(c->socket,c->handles.runtime);
 assert(read(c->socket,&byte,1)==1 && byte=='X');
 assert(!pthread_mutex_lock(&c->lock)); c->exit_leader=true;
 assert(!pthread_cond_signal(&c->changed)); assert(!pthread_mutex_unlock(&c->lock));
 /* Successful join establishes termination, while this thread remains alive. */
 assert(!pthread_join(c->leader,NULL)); assert(syscall(SYS_gettid)!=(long)getpid());
 printf("leader exited; surviving tgid=%ld tid=%ld\n",(long)getpid(),syscall(SYS_gettid));
 denied_runtime(c->handles.runtime,before);
 wait_owner_terminal(c->handles.runtime,c->handles.events,before);
 assert(write(c->socket,"D",1)==1);
 finish_handles(&c->handles); close(c->socket);
 assert(!pthread_cond_destroy(&c->changed)); assert(!pthread_mutex_destroy(&c->lock));
 free(c); return NULL;
}
static void leader_exit(void)
{
 int pair[2],retained; pid_t child; char byte; struct actryn_status before;
 assert(!socketpair(AF_UNIX,SOCK_SEQPACKET,0,pair)); child=fork(); assert(child>=0);
 if(!child) {
  struct leader_case *c=calloc(1,sizeof(*c)); pthread_t sibling;
  assert(c); alarm(15); close(pair[0]); c->socket=pair[1]; c->leader=pthread_self();
  assert(!pthread_mutex_init(&c->lock,NULL)); assert(!pthread_cond_init(&c->changed,NULL));
  c->handles=start(); begin(&c->handles,5000*MS);
  assert(!pthread_create(&sibling,NULL,surviving_thread,c));
  assert(!pthread_mutex_lock(&c->lock));
  while(!c->exit_leader) assert(!pthread_cond_wait(&c->changed,&c->lock));
  assert(!pthread_mutex_unlock(&c->lock)); pthread_exit(NULL);
 }
 close(pair[1]); retained=receive_fd(pair[0]); before=status(retained);
 assert(before.state==ACTRYN_ACTIVE && before.operation_state==ACTRYN_OP_RUNNING);
 printf("leader before exit tgid=%ld retained_fd=%d\n",(long)child,retained); fflush(stdout);
 assert(write(pair[0],"X",1)==1); assert(read(pair[0],&byte,1)==1 && byte=='D');
 wait_child(child); assert(owner_terminal(status(retained),before));
 close(retained); close(pair[0]);
}
static int pid_reuse(void)
{
 int pair[2],retained; pid_t child,wanted; long replacement;
 char byte; struct actryn_status before; struct clone_args args={0};
 assert(!socketpair(AF_UNIX,SOCK_SEQPACKET,0,pair)); child=fork(); assert(child>=0);
 if(!child) {
  struct handles h; alarm(15); close(pair[0]); h=start(); begin(&h,5000*MS);
  send_fd(pair[1],h.runtime); assert(read(pair[1],&byte,1)==1 && byte=='X'); _exit(0);
 }
 close(pair[1]); retained=receive_fd(pair[0]); before=status(retained);
 assert(before.state==ACTRYN_ACTIVE && before.operation_state==ACTRYN_OP_RUNNING);
 printf("original owner tgid=%ld retained_fd=%d\n",(long)child,retained); fflush(stdout);
 assert(write(pair[0],"X",1)==1); wait_child(child); close(pair[0]);
 wait_owner_terminal(retained,-1,before);
 {
  /* Successful ADMIN binding already required CAP_SYS_ADMIN in init_user_ns.
   * With that privilege a parent PID namespace must be visible if one exists. */
  int nsfd=open("/proc/self/ns/pid",O_RDONLY),parent,error; struct stat st;
  assert(nsfd>=0 && !fstat(nsfd,&st)); errno=0; parent=ioctl(nsfd,NS_GET_PARENT); error=errno;
  printf("PID namespace inode=%llu parent_result=%d errno=%d\n",
   (unsigned long long)st.st_ino,parent,error); fflush(stdout);
  assert(parent==-1 && error==EPERM); close(nsfd);
 }
 /* Request that same numeric PID in this existing namespace, after reaping.
  * No new PID namespace: an alias would not prove reuse of the original TGID. */
 wanted=child; args.exit_signal=SIGCHLD; args.set_tid=(uintptr_t)&wanted; args.set_tid_size=1;
 replacement=syscall(SYS_clone3,&args,sizeof(args));
 if(replacement<0) {
  fprintf(stderr,"NOT_RUN numeric PID reuse: clone3(set_tid=%ld) errno=%d (%s); no retry\n",
   (long)wanted,errno,strerror(errno)); close(retained); return 77;
 }
 if(!replacement) {
  alarm(15);
  assert(getpid()==wanted); assert(syscall(SYS_gettid)==(long)wanted);
  printf("replacement owner tgid=%ld equals reaped original\n",(long)getpid());
  denied_runtime(retained,before);
  assert(owner_terminal(status(retained),before)); close(retained); fflush(stdout); _exit(0);
 }
 assert(replacement==(long)wanted); wait_child((pid_t)replacement);
 assert(owner_terminal(status(retained),before)); close(retained); return 0;
}
static void predicate_selftest(void)
{
 struct actryn_status before={.grant=7,.instance=6,.operation=8,.stream=9,.controller_boot=10,
  .controller_session=11,.left_permille=12,.right_permille=-12};
 struct actryn_status terminal,bad;
 before.runtime_nonce[0]=1; before.device_identity[0]=3;
 terminal=before; terminal.state=ACTRYN_FAULT_LATCHED;
 terminal.reason=ACTRYN_OWNER_LOST; terminal.operation_state=ACTRYN_OP_UNKNOWN;
 assert(owner_terminal(terminal,before));
#define REJECT(field,value) do { bad=terminal; bad.field=(value); assert(!owner_terminal(bad,before)); } while(0)
 REJECT(state,ACTRYN_ACTIVE); REJECT(reason,ACTRYN_EXPIRED);
 REJECT(operation_state,ACTRYN_OP_RECONCILED); REJECT(flags,ACTRYN_STATUS_GRANT_AUTHORIZED);
 REJECT(grant,17); REJECT(instance,16); REJECT(operation,18); REJECT(stream,19);
 REJECT(controller_boot,20); REJECT(controller_session,21); REJECT(runtime_nonce[0],2);
 REJECT(device_identity[0],4);
 REJECT(left_permille,0); REJECT(right_permille,0);
#undef REJECT
 puts("PASS owner lifetime predicate and fourteen counterexamples");
}
int main(int argc,char **argv)
{
 int result=0; assert(argc==2);
 if(!strcmp(argv[1],"--selftest")) { predicate_selftest(); return 0; }
 guard_guest(); alarm(20);
 if(!strcmp(argv[1],"leader-exit")) leader_exit();
 else if(!strcmp(argv[1],"pid-reuse")) result=pid_reuse();
 else { fputs("unknown owner lifetime scenario\n",stderr); return 2; }
 if(!result) printf("PASS authority owner lifetime %s\n",argv[1]);
 return result;
}
