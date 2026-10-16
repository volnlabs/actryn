/* SPDX-License-Identifier: GPL-2.0-only */
#define _GNU_SOURCE
#include "protocol.h"
#include "common.h"
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <sys/wait.h>
static bool userspace;
static int journal=-1;
static unsigned trial;
static uint64_t observation_id;
static const char *scenarios[]={"normal","cancel","delayed-applied","owner-exit","normal",
 "cancel","delayed-applied","owner-exit","normal","normal"};
static void emit(const char *format,...)
{
 char line[4096]; va_list args; int n; size_t at=0;
 va_start(args,format); n=vsnprintf(line,sizeof(line),format,args); va_end(args);
 assert(n>0 && (size_t)n<sizeof(line));
 while(at<(size_t)n) { ssize_t w=write(journal,line+at,(size_t)n-at); assert(w>0); at+=(size_t)w; }
}
static void hex(const void *data,size_t n,char *out)
{ const unsigned char *b=data; for(size_t i=0;i<n;i++) sprintf(out+2*i,"%02x",b[i]); }
static void resources(const char *phase,int admin)
{
 FILE *f=fopen("/proc/stat","r"); unsigned long long c[8]; struct rusage usage;
 assert(f && fscanf(f,"cpu %llu %llu %llu %llu %llu %llu %llu %llu",&c[0],&c[1],&c[2],&c[3],&c[4],&c[5],&c[6],&c[7])==8);
 fclose(f); assert(!getrusage(RUSAGE_CHILDREN,&usage));
 emit("{\"type\":\"resources\",\"phase\":\"%s\",\"at_ns\":%llu,\"clock_ticks\":%ld,\"guest_cpu_ticks\":[%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu],\"children_user_us\":%llu,\"children_system_us\":%llu}\n",
  phase,(unsigned long long)a16_now(),sysconf(_SC_CLK_TCK),c[0],c[1],c[2],c[3],c[4],c[5],c[6],c[7],
  (unsigned long long)usage.ru_utime.tv_sec*1000000+usage.ru_utime.tv_usec,
  (unsigned long long)usage.ru_stime.tv_sec*1000000+usage.ru_stime.tv_usec);
 if(userspace) {
  struct ucred peer; socklen_t n=sizeof(peer); char path[80],buf[4096],*at,*save; unsigned field=3;
  unsigned long long utime=0,stime=0;
  assert(!getsockopt(admin,SOL_SOCKET,SO_PEERCRED,&peer,&n));
  snprintf(path,sizeof(path),"/proc/%d/stat",peer.pid); f=fopen(path,"r"); assert(f && fgets(buf,sizeof(buf),f)); fclose(f);
  at=strrchr(buf,')'); assert(at);
  for(at=strtok_r(at+2," ",&save);at;at=strtok_r(NULL," ",&save),field++) {
   if(field==14) utime=strtoull(at,NULL,10);
   if(field==15) stime=strtoull(at,NULL,10);
  }
  emit("{\"type\":\"baseline_cpu\",\"phase\":\"%s\",\"pid\":%d,\"user_ticks\":%llu,\"system_ticks\":%llu}\n",phase,peer.pid,utime,stime);
 }
}
static void sleep_ms(unsigned ms)
{ struct timespec t={.tv_sec=ms/1000,.tv_nsec=(ms%1000)*1000000}; while(nanosleep(&t,&t)) assert(errno==EINTR); }
static struct a16_reply exchange(int fd,struct a16_command *c)
{
 struct a16_reply r; struct pollfd p={.fd=fd,.events=POLLIN}; ssize_t n;
 assert(send(fd,c,sizeof(*c),MSG_NOSIGNAL)==sizeof(*c)); assert(poll(&p,1,2000)==1);
 n=recv(fd,&r,sizeof(r),MSG_TRUNC); assert(n==sizeof(r) && !r.reserved); return r;
}
static int request(int fd,struct actryn_request *r)
{
 uint64_t before=a16_now(),after; int rc; char bytes[2*sizeof(*r)+1]; struct actryn_request submitted=*r;
 if(userspace) { struct a16_command c={.action=A16_REQUEST,.request=*r};
  struct a16_reply reply=exchange(fd,&c); rc=reply.error; if(!rc) *r=reply.data.request;
 } else rc=ioctl(fd,ACTRYN_IOCTL_REQUEST,r)?-errno:0;
 after=a16_now(); hex(&submitted,sizeof(submitted),bytes);
 emit("{\"type\":\"request\",\"trial\":%u,\"opcode\":%u,\"before_ns\":%llu,\"after_ns\":%llu,\"rc\":%d,\"operation\":%llu,\"sequence\":%llu,\"deadline_ns\":%llu,\"observation\":%llu,\"acquired_earliest_ns\":%llu,\"bytes\":\"%s\"}\n",
 trial,r->opcode,(unsigned long long)before,(unsigned long long)after,rc,(unsigned long long)r->operation,
 (unsigned long long)r->sequence,(unsigned long long)r->deadline_ns,(unsigned long long)r->observation,
 (unsigned long long)r->acquired_earliest_ns,bytes); return rc;
}
static int bind_role(unsigned role)
{
 int fd; struct actryn_request r={.version=1,.opcode=ACTRYN_BIND,.role=role};
 if(userspace) {
  struct sockaddr_un addr={.sun_family=AF_UNIX}; struct a16_command c={.action=A16_BIND,.request=r};
  fd=socket(AF_UNIX,SOCK_SEQPACKET|SOCK_CLOEXEC,0); assert(fd>=0); strcpy(addr.sun_path,A16_SOCKET);
  assert(!connect(fd,(struct sockaddr *)&addr,sizeof(addr))); assert(!exchange(fd,&c).error);
 } else { fd=open(ACTRYN_DEVICE,O_RDWR|O_NONBLOCK|O_CLOEXEC); assert(fd>=0); assert(!ioctl(fd,ACTRYN_IOCTL_REQUEST,&r)); }
 return fd;
}
static struct actryn_status status(int fd)
{
 struct actryn_status s;
 if(userspace) { struct a16_command c={.action=A16_STATUS}; struct a16_reply r=exchange(fd,&c); assert(!r.error); s=r.data.status; }
 else assert(!ioctl(fd,ACTRYN_IOCTL_STATUS,&s));
 assert(s.version==1); return s;
}
static void drain(int fd)
{
 for(unsigned i=0;i<256;i++) {
  struct actryn_event v; char bytes[2*sizeof(v)+1]; int rc;
  if(userspace) { struct a16_command c={.action=A16_EVENT}; struct a16_reply r=exchange(fd,&c); rc=r.error; v=r.data.event; }
  else { ssize_t n=read(fd,&v,sizeof(v)); rc=n==(ssize_t)sizeof(v)?0:-errno; }
  if(rc==-EAGAIN) return;
  assert(!rc); hex(&v,sizeof(v),bytes);
  emit("{\"type\":\"event\",\"trial\":%u,\"sequence\":%llu,\"captured_ns\":%llu,\"kind\":%u,\"state\":%u,\"operation_state\":%u,\"reason\":%u,\"operation\":%llu,\"sample\":%llu,\"lost\":%u,\"bytes\":\"%s\"}\n",
   trial,(unsigned long long)v.sequence,(unsigned long long)v.captured_ns,v.kind,v.status.state,
   v.status.operation_state,v.status.reason,(unsigned long long)v.status.operation,
   (unsigned long long)v.status.sequence,v.status.events_lost,bytes);
 }
}
static struct actryn_request req(unsigned opcode,struct actryn_status s)
{ struct actryn_request r={.version=1,.opcode=opcode}; memcpy(r.runtime_nonce,s.runtime_nonce,16); return r; }
static void heartbeat(int runtime,int admin)
{ struct actryn_request r=req(ACTRYN_HEALTH,status(admin)); r.deadline_ns=a16_now()+1500*A16_MS; assert(!request(runtime,&r)); }
static struct actryn_status wait_state(int admin,int events,unsigned state,unsigned op)
{
 uint64_t end=a16_now()+2000*A16_MS; struct actryn_status s;
 do { drain(events); s=status(admin); if(s.state==state && s.operation_state==op) return s;
  if(s.state>=ACTRYN_FAULT_LATCHED && state!=ACTRYN_FAULT_LATCHED) break;
  sleep_ms(2);
 } while(a16_now()<end);
 emit("{\"type\":\"wait_failure\",\"trial\":%u,\"state\":%u,\"operation_state\":%u,\"reason\":%u}\n",trial,s.state,s.operation_state,s.reason);
 abort();
}
static bool terminal_matches(const struct actryn_status *s,const struct actryn_request *closing)
{
 unsigned reason=closing->opcode==ACTRYN_FINISH?ACTRYN_SKILL_FINISHED:ACTRYN_CANCELLED;
 return (closing->opcode==ACTRYN_FINISH || closing->opcode==ACTRYN_CANCEL) &&
  s->state==ACTRYN_ACTIVE && s->operation_state==ACTRYN_OP_RECONCILED && s->reason==reason &&
  (s->flags&9)==9 && !s->left_permille && !s->right_permille && closing->grant &&
  s->grant==closing->grant && s->operation==closing->operation && s->stream==closing->stream &&
  !memcmp(s->runtime_nonce,closing->runtime_nonce,16);
}
static void control(const char *command)
{ char ack; printf("CONTROL %s\n",command); fflush(stdout); assert(read(STDIN_FILENO,&ack,1)==1 && ack=='Y'); }
static void observe(int acquisition,int admin)
{
 struct actryn_request r=req(ACTRYN_OBSERVE,status(admin)); uint64_t now=a16_now();
 r.observation=++observation_id; r.context_revision=1; r.acquired_earliest_ns=r.acquired_latest_ns=now;
 r.valid_until_ns=now+900*A16_MS; assert(!request(acquisition,&r));
}
static void send_retained(int socket,int fd)
{
 uint64_t before=a16_now(); char cbuf[CMSG_SPACE(sizeof(int))]={0};
 struct iovec io={.iov_base=&before,.iov_len=sizeof(before)};
 struct msghdr m={.msg_iov=&io,.msg_iovlen=1,.msg_control=cbuf,.msg_controllen=sizeof(cbuf)};
 struct cmsghdr *c=CMSG_FIRSTHDR(&m); c->cmsg_level=SOL_SOCKET; c->cmsg_type=SCM_RIGHTS; c->cmsg_len=CMSG_LEN(sizeof(int));
 memcpy(CMSG_DATA(c),&fd,sizeof(fd)); assert(sendmsg(socket,&m,0)==sizeof(before));
}
static void child_trial(int parent_socket,int intent)
{
 int admin=bind_role(ACTRYN_ADMIN),runtime=bind_role(ACTRYN_RUNTIME),events=bind_role(ACTRYN_EVENTS);
 int acquisition=bind_role(ACTRYN_ACQUISITION); uint64_t end,start; struct actryn_status s; struct actryn_request r;
 alarm(10); r=(struct actryn_request){.version=1,.opcode=ACTRYN_RECOVER}; assert(!request(admin,&r));
 end=a16_now()+1500*A16_MS;
 do { drain(events); s=status(admin); if(s.flags&1) break; sleep_ms(2); } while(a16_now()<end);
 assert(s.flags&1); r=(struct actryn_request){.version=1,.opcode=ACTRYN_REARM}; assert(!request(admin,&r));
 s=wait_state(admin,events,ACTRYN_READY,ACTRYN_OP_NONE);
 r=(struct actryn_request){.version=1,.opcode=ACTRYN_GRANT,.instance=1,.deadline_ns=a16_now()+15000*A16_MS};
 assert(!request(admin,&r)); heartbeat(runtime,admin); s=status(admin); r=req(ACTRYN_ACTIVATE,s);
 r.grant=s.grant; r.instance=1; assert(!request(runtime,&r)); observe(acquisition,admin); s=status(admin);
 r=req(ACTRYN_ALLOCATE,s); r.grant=s.grant; r.instance=s.instance; r.observation=observation_id;
 r.context_revision=1; r.deadline_ns=a16_now()+5000*A16_MS; assert(!request(runtime,&r));
 assert(write(intent,&r,sizeof(r))==sizeof(r)); assert(!fdatasync(intent));
 r.opcode=ACTRYN_START; assert(!request(runtime,&r)); wait_state(admin,events,ACTRYN_ACTIVE,ACTRYN_OP_RUNNING);
 start=a16_now();
 for(unsigned i=1;i<=10;i++) {
  while(a16_now()<start+(i-1)*100*A16_MS) { drain(events); sleep_ms(2); }
  heartbeat(runtime,admin); observe(acquisition,admin); s=status(admin); r=req(ACTRYN_SAMPLE,s);
  r.grant=s.grant; r.operation=s.operation; r.stream=s.stream; r.sequence=i;
  r.observation=observation_id; r.context_revision=1; r.deadline_ns=a16_now()+400*A16_MS;
  if(!strcmp(scenarios[trial],"delayed-applied") && i==1) { control("delay 600000000"); r.deadline_ns=a16_now()+150*A16_MS; }
  assert(!request(runtime,&r));
  if(!strcmp(scenarios[trial],"delayed-applied")) {
   s=wait_state(admin,events,ACTRYN_FAULT_LATCHED,ACTRYN_OP_UNKNOWN); assert(s.reason==ACTRYN_EXPIRED);
   control("delay 0"); break;
  }
  end=a16_now()+600*A16_MS;
  do { drain(events); s=status(admin); if(s.sequence==i || s.state==ACTRYN_FAULT_LATCHED) break; sleep_ms(2); } while(a16_now()<end);
  assert(s.sequence==i && s.state==ACTRYN_ACTIVE);
  if(i==5 && !strcmp(scenarios[trial],"owner-exit")) { send_retained(parent_socket,runtime); _exit(77); }
  if(i==5 && !strcmp(scenarios[trial],"cancel")) break;
 }
 s=status(admin);
 if(s.state==ACTRYN_ACTIVE) {
  r=req(!strcmp(scenarios[trial],"cancel")?ACTRYN_CANCEL:ACTRYN_FINISH,s);
  r.grant=s.grant; r.operation=s.operation; r.stream=s.stream;
  assert(!request(runtime,&r)); s=wait_state(admin,events,ACTRYN_ACTIVE,ACTRYN_OP_RECONCILED);
  emit("{\"type\":\"terminal\",\"trial\":%u,\"state\":%u,\"operation_state\":%u,\"reason\":%u,\"flags\":%u,\"left\":%d,\"right\":%d,\"grant\":%llu,\"operation\":%llu,\"stream\":%llu,\"expected_grant\":%llu,\"expected_operation\":%llu,\"expected_stream\":%llu}\n",
   trial,s.state,s.operation_state,s.reason,s.flags,s.left_permille,s.right_permille,
   (unsigned long long)s.grant,(unsigned long long)s.operation,(unsigned long long)s.stream,
   (unsigned long long)r.grant,(unsigned long long)r.operation,(unsigned long long)r.stream);
  assert(terminal_matches(&s,&r));
 }
 drain(events); close(runtime); close(acquisition); close(events); close(admin); _exit(0);
}
int main(int argc,char **argv)
{
 int directory,admin,events; char boot[80]={0}; unsigned failures=0; int bootfd;
 assert(argc==3 && (!strcmp(argv[1],"kernel") || !strcmp(argv[1],"userspace")));
 userspace=!strcmp(argv[1],"userspace"); a16_guard(userspace); a16_deny_exec(); umask(077);
 assert(!mkdir(argv[2],0700)); directory=open(argv[2],O_RDONLY|O_DIRECTORY|O_CLOEXEC); assert(directory>=0);
 journal=openat(directory,"events.jsonl",O_WRONLY|O_CREAT|O_EXCL|O_APPEND|O_CLOEXEC,0600); assert(journal>=0);
 bootfd=open("/proc/sys/kernel/random/boot_id",O_RDONLY|O_CLOEXEC); assert(bootfd>=0); assert(read(bootfd,boot,36)==36); close(bootfd);
 emit("{\"type\":\"manifest\",\"revision\":1,\"amendment\":2,\"arm\":\"%s\",\"boot\":\"%s\",\"planned_trials\":10}\n",argv[1],boot);
 admin=bind_role(ACTRYN_ADMIN); events=bind_role(ACTRYN_EVENTS);
 resources("begin",admin);
 for(trial=0;trial<10;trial++) {
  int pair[2],intent,w,retained=-1; pid_t child; char name[40]; uint64_t before;
  control("delay 0"); control("restart"); drain(events);
  snprintf(name,sizeof(name),"intent-%02u.bin",trial); intent=openat(directory,name,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600); assert(intent>=0);
  assert(!fsync(directory)); assert(!socketpair(AF_UNIX,SOCK_SEQPACKET|SOCK_CLOEXEC,0,pair));
  emit("{\"type\":\"trial_begin\",\"trial\":%u,\"scenario\":\"%s\",\"at_ns\":%llu,\"lost_baseline\":%u}\n",trial,scenarios[trial],(unsigned long long)a16_now(),status(admin).events_lost);
  child=fork(); assert(child>=0);
  if(!child) { close(pair[0]); close(admin); close(events); child_trial(pair[1],intent); }
  close(pair[1]); assert(waitpid(child,&w,0)==child); close(intent);
  if(WIFEXITED(w) && WEXITSTATUS(w)==77) {
   char cbuf[CMSG_SPACE(sizeof(int))]; struct iovec io={.iov_base=&before,.iov_len=sizeof(before)};
   struct msghdr m={.msg_iov=&io,.msg_iovlen=1,.msg_control=cbuf,.msg_controllen=sizeof(cbuf)};
   assert(recvmsg(pair[0],&m,0)==sizeof(before)); assert(!(m.msg_flags&MSG_CTRUNC));
   memcpy(&retained,CMSG_DATA(CMSG_FIRSTHDR(&m)),sizeof(retained));
   emit("{\"type\":\"owner_exit\",\"trial\":%u,\"before_exit_ns\":%llu}\n",trial,(unsigned long long)before);
   assert(wait_state(admin,events,ACTRYN_FAULT_LATCHED,ACTRYN_OP_UNKNOWN).reason==ACTRYN_OWNER_LOST);
   close(retained); w=0;
  }
  close(pair[0]); drain(events);
  if(!WIFEXITED(w) || WEXITSTATUS(w)) failures++;
  emit("{\"type\":\"trial_end\",\"trial\":%u,\"wait_status\":%d,\"pass\":%s,\"at_ns\":%llu,\"lost_final\":%u}\n",trial,w,
   WIFEXITED(w)&&!WEXITSTATUS(w)?"true":"false",(unsigned long long)a16_now(),status(admin).events_lost);
  assert(!fdatasync(journal));
 }
 resources("end",admin);
 emit("{\"type\":\"complete\",\"trials\":10,\"failures\":%u}\n",failures); assert(!fdatasync(journal));
 close(events); close(admin); close(journal); close(directory); return failures?1:0;
}
