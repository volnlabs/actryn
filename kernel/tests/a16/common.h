/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef ACTRYN_A16_COMMON_H
#define ACTRYN_A16_COMMON_H
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <sys/utsname.h>
#include <time.h>
#include <unistd.h>
static inline uint64_t a16_now(void)
{ struct timespec t; assert(!clock_gettime(CLOCK_BOOTTIME,&t)); return (uint64_t)t.tv_sec*1000000000+t.tv_nsec; }
static inline void a16_deny_exec(void)
{
 struct sock_filter code[]={
  BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,nr)),
  BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,__NR_execve,2,0),
  BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,__NR_execveat,1,0),
  BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW), BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ERRNO|EPERM)};
 struct sock_fprog p={.len=sizeof(code)/sizeof(code[0]),.filter=code};
 assert(!prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0)); assert(!prctl(PR_SET_SECCOMP,SECCOMP_MODE_FILTER,&p));
}
static inline void a16_guard(int userspace)
{
 struct utsname u; char buf[512]={0}; size_t off=0; ssize_t n; int fd,matched=0;
 assert(!uname(&u) && !strcmp(u.machine,"aarch64") && !strcmp(u.release,"6.12.111+deb13-arm64"));
 assert(geteuid()==0); fd=open("/proc/device-tree/compatible",O_RDONLY|O_CLOEXEC); assert(fd>=0);
 n=read(fd,buf,sizeof(buf)-1); assert(n>0); close(fd);
 while(off<(size_t)n) { if(!strcmp(buf+off,"linux,dummy-virt")) matched=1; off+=strlen(buf+off)+1; }
 assert(matched);
 if(userspace) { assert(access("/dev/actryn-authority",F_OK)<0 && errno==ENOENT); assert(!access("/dev/ttyAMA1",F_OK)); }
 else { assert(access("/dev/ttyAMA1",F_OK)<0 && errno==ENOENT); assert(!access("/dev/actryn-authority",F_OK)); }
}
#endif
