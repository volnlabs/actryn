// SPDX-License-Identifier: GPL-2.0-only
/* Test-only one-shot bounded capture. Never linked into the authority driver. */
#include <linux/module.h>
#include <linux/kprobes.h>
#include <linux/ktime.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/ptrace.h>
#include <linux/sched.h>
#include <linux/tty.h>
#include <linux/tty_driver.h>
#include <linux/uaccess.h>
#include <linux/utsname.h>
#include "prefix.h"

#define CAPACITY 4096
#define STOP _IO('U',0x41)
struct capture_header {
 u8 magic[8];
 __le32 version,record_size,capacity,records;
 __le64 started,stopped,entries,returns,dropped,over_cap,read_failure;
 __le64 invalid_return,concurrent,missed,inflight;
 u8 reserved[16];
};
struct capture_record {
 __le64 sequence,entry_ns,return_ns,tty,buffer,requested,result;
 __le32 tid,cpu,flags,copied;
 u8 data[A16_FRAME_MAX],reserved[26];
};
struct invocation { u64 entry_ns; struct tty_struct *tty; const u8 *buffer; size_t count; };
static struct { struct capture_header header; struct capture_record records[CAPACITY]; } dump;
static DEFINE_SPINLOCK(lock);
static DEFINE_MUTEX(lifecycle);
static u64 entries,returns,dropped,over_cap,read_failure,invalid_return,concurrent,inflight;
static unsigned used;
static bool stopped,registered;

static int capture_enter(struct kretprobe_instance *ri,struct pt_regs *regs)
{
 struct invocation *v=(void *)ri->data;
 struct tty_struct *tty=(void *)regs_get_kernel_argument(regs,0);
 unsigned long flags;
 if(!tty || tty->index!=1 || strcmp(tty->name,"ttyAMA1") || !tty->driver ||
    !tty->driver->name || strcmp(tty->driver->name,"ttyAMA")) return 1;
 v->entry_ns=ktime_get_boottime_ns(); v->tty=tty;
 v->buffer=(void *)regs_get_kernel_argument(regs,1);
 v->count=regs_get_kernel_argument(regs,2);
 spin_lock_irqsave(&lock,flags);
 entries++; if(inflight++) concurrent++;
 spin_unlock_irqrestore(&lock,flags);
 return 0;
}
NOKPROBE_SYMBOL(capture_enter);

static int capture_return(struct kretprobe_instance *ri,struct pt_regs *regs)
{
 struct invocation *v=(void *)ri->data;
 struct capture_record record={};
 s64 result=(s64)regs_return_value(regs);
 unsigned copied,flags=a16_prefix(v->count,result,&copied);
 unsigned long irqflags;
 /* Caller has not resumed. uart_write only copies from this synchronous input;
  * capture only the accepted prefix, never memory past the original count. */
 record.return_ns=cpu_to_le64(ktime_get_boottime_ns());
 if(copied && copy_from_kernel_nofault(record.data,v->buffer,copied)) {
  flags|=A16_READ_FAILURE; copied=0; memset(record.data,0,sizeof(record.data));
 }
 record.entry_ns=cpu_to_le64(v->entry_ns);
 record.tty=cpu_to_le64((unsigned long)v->tty);
 record.buffer=cpu_to_le64((unsigned long)v->buffer);
 record.requested=cpu_to_le64(v->count); record.result=cpu_to_le64(result);
 record.tid=cpu_to_le32(task_pid_nr(current)); record.cpu=cpu_to_le32(raw_smp_processor_id());
 record.flags=cpu_to_le32(flags); record.copied=cpu_to_le32(copied);
 spin_lock_irqsave(&lock,irqflags);
 record.sequence=cpu_to_le64(++returns); inflight--;
 if(flags&A16_OVER_CAP) over_cap++;
 if(flags&A16_READ_FAILURE) read_failure++;
 if(flags&A16_BAD_RETURN) invalid_return++;
 if(used<CAPACITY) dump.records[used++]=record; else dropped++;
 spin_unlock_irqrestore(&lock,irqflags);
 return 0;
}
NOKPROBE_SYMBOL(capture_return);

static struct kretprobe probe={.kp.symbol_name="uart_write",.entry_handler=capture_enter,
 .handler=capture_return,.maxactive=64,.data_size=sizeof(struct invocation)};

static void freeze(void)
{
 if(stopped) return;
 if(registered) { unregister_kretprobe(&probe); registered=false; }
 /* No handler may touch module storage after unregister has synchronized. */
 dump.header.records=cpu_to_le32(used);
 dump.header.stopped=cpu_to_le64(ktime_get_boottime_ns());
 dump.header.entries=cpu_to_le64(entries); dump.header.returns=cpu_to_le64(returns);
 dump.header.dropped=cpu_to_le64(dropped); dump.header.over_cap=cpu_to_le64(over_cap);
 dump.header.read_failure=cpu_to_le64(read_failure);
 dump.header.invalid_return=cpu_to_le64(invalid_return);
 dump.header.concurrent=cpu_to_le64(concurrent);
 dump.header.missed=cpu_to_le64((u64)(u32)READ_ONCE(probe.nmissed));
 dump.header.inflight=cpu_to_le64(inflight); stopped=true;
}
static long capture_ioctl(struct file *file,unsigned int command,unsigned long argument)
{
 if(command!=STOP || argument) return -EINVAL;
 if(!capable(CAP_SYS_ADMIN)) return -EPERM;
 if(mutex_lock_interruptible(&lifecycle)) return -EINTR;
 freeze(); mutex_unlock(&lifecycle); return 0;
}
static ssize_t capture_read(struct file *file,char __user *buffer,size_t count,loff_t *position)
{
 ssize_t result;
 if(mutex_lock_interruptible(&lifecycle)) return -EINTR;
 result=stopped?simple_read_from_buffer(buffer,count,position,&dump,
   sizeof(dump.header)+used*sizeof(struct capture_record)):-EBUSY;
 mutex_unlock(&lifecycle); return result;
}
static const struct file_operations operations={.owner=THIS_MODULE,.read=capture_read,
 .unlocked_ioctl=capture_ioctl,.llseek=default_llseek};
static struct miscdevice device={.minor=MISC_DYNAMIC_MINOR,.name="actryn-a16-capture",
 .fops=&operations,.mode=0600};
static int __init capture_init(void)
{
 int result;
 static_assert(sizeof(struct capture_header)==128);
 static_assert(sizeof(struct capture_record)==256);
 if(!IS_ENABLED(CONFIG_ARM64) || strcmp(utsname()->nodename,"actryn-a16") ||
    strcmp(init_utsname()->release,"6.12.111+deb13-arm64") ||
    !of_machine_is_compatible("linux,dummy-virt")) return -ENODEV;
 memcpy(dump.header.magic,"A16UART4",8); dump.header.version=cpu_to_le32(4);
 dump.header.record_size=cpu_to_le32(sizeof(struct capture_record));
 dump.header.capacity=cpu_to_le32(CAPACITY);
 dump.header.started=cpu_to_le64(ktime_get_boottime_ns());
 result=register_kretprobe(&probe); if(result) return result; registered=true;
 result=misc_register(&device); if(result) freeze();
 return result;
}
static void __exit capture_exit(void)
{ misc_deregister(&device); mutex_lock(&lifecycle); freeze(); mutex_unlock(&lifecycle); }
module_init(capture_init); module_exit(capture_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("A16 test-only bounded accepted UART prefix capture");
