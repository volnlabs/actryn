/* SPDX-License-Identifier: GPL-2.0-only */
/* Included only in the explicitly derived, non-production diagnostic8 module. */
#include <linux/hex.h>
#define H8_CAPACITY 8U
enum h8_kind { H8_BEGIN=1,H8_TX,H8_RX,H8_PROCESS,H8_DECISION,H8_CLOSE };
struct h8_record {
 __le32 sequence,kind;
 __le64 at,first,other;
 __le32 correlation,flags,length,aux;
 u8 payload[160];
};
static struct {
 u8 magic[8];
 __le32 version,record_size,capacity,count,dropped,armed,finished,attempts;
 u8 reserved[24];
 struct h8_record records[H8_CAPACITY];
} h8_dump={ .magic="A16HLO08",.version=cpu_to_le32(8),
 .record_size=cpu_to_le32(208),.capacity=cpu_to_le32(H8_CAPACITY) };
static DEFINE_SPINLOCK(h8_lock);

/* No allocation, printing, UART writes, timers or authority decisions here. */
static u32 h8_record(u32 kind,u64 at,u64 first,u64 other,u32 correlation,
                    u32 flags,s32 aux,const u8 *payload,u32 length,u32 finish)
{
 unsigned long irq; u32 count,id=0; struct h8_record *r;
 spin_lock_irqsave(&h8_lock,irq);
 if(!le32_to_cpu(h8_dump.armed) || le32_to_cpu(h8_dump.finished)) goto out;
 count=le32_to_cpu(h8_dump.count);
 if(count==H8_CAPACITY || length>160) {
  u32 dropped=le32_to_cpu(h8_dump.dropped);
  if(dropped<U32_MAX) h8_dump.dropped=cpu_to_le32(dropped+1);
  goto done;
 }
 id=count+1; r=&h8_dump.records[count];
 r->sequence=cpu_to_le32(id); r->kind=cpu_to_le32(kind);
 r->at=cpu_to_le64(at); r->first=cpu_to_le64(first); r->other=cpu_to_le64(other);
 r->correlation=cpu_to_le32(correlation); r->flags=cpu_to_le32(flags);
 r->length=cpu_to_le32(length); r->aux=cpu_to_le32((u32)aux);
 if(length) memcpy(r->payload,payload,length);
 h8_dump.count=cpu_to_le32(id);
done:
 if(finish) h8_dump.finished=cpu_to_le32(finish);
out:
 spin_unlock_irqrestore(&h8_lock,irq); return id;
}
static int h8_begin(u64 original_now)
{
 unsigned long irq; u32 attempts; struct h8_record *r;
 spin_lock_irqsave(&h8_lock,irq);
 attempts=le32_to_cpu(h8_dump.attempts);
 if(attempts<U32_MAX) h8_dump.attempts=cpu_to_le32(attempts+1);
 if(!attempts) {
  /* Arm and publish BEGIN atomically with respect to concurrent RX. */
  r=&h8_dump.records[0]; r->sequence=cpu_to_le32(1); r->kind=cpu_to_le32(H8_BEGIN);
  r->at=cpu_to_le64(original_now); h8_dump.count=cpu_to_le32(1);
  h8_dump.armed=cpu_to_le32(1);
 }
 spin_unlock_irqrestore(&h8_lock,irq);
 if(attempts) return -EALREADY;
 return 0;
}
static void h8_tx(struct actryn_endpoint *e,u64 original_now,int result)
{
 if(e->tx_frame.kind!=AW_HELLO) return;
 h8_record(H8_TX,original_now,e->hello_sent,now_ns(),e->tx_frame.transaction,
           e->tx_off,result,e->tx+e->tx_off,e->tx_len-e->tx_off,0);
}
static u32 h8_rx(struct actryn_endpoint *e,u64 original_now,int decoded)
{
 u32 flags=(!original_now?1:0) |
  (original_now && original_now-e->parser_started>=500*MS?2:0) |
  (decoded?4:0);
 return h8_record(H8_RX,original_now,e->parser_started,0,0,flags,decoded,
                  e->parser,e->parser_len,0);
}
static void h8_process(struct actryn_endpoint *e,const struct actryn_frame *f,u64 original_now)
{
 u32 mismatch=(f->kind!=AW_HELLO_ACK) | ((!e->await)<<1) |
  ((e->awaited.kind!=AW_HELLO)<<2) | ((f->transaction!=e->awaited.transaction)<<3) |
  ((!!memcmp(f->nonce,e->s.runtime_nonce,16))<<4);
 u8 bytes[ACTRYN_WIRE_SIZE]; actryn_pack(f,bytes);
 h8_record(H8_PROCESS,original_now,e->hello_sent,0,e->h8_processing_id,
           mismatch,0,bytes,sizeof(bytes),0);
}
static void h8_decision(struct actryn_endpoint *e,const struct actryn_frame *f,
                       u64 original_now,bool rejected)
{
 /* Called after the original if resolved, under authority. Reuse its exact
  * sampled time and stable fields; this mask never drives the decision. */
 u32 mask=(f->status!=1) | ((!f->boot)<<1) | ((!f->session)<<2) |
  (is_zero(f->device,16)<<3) | ((!!f->grant)<<4) | ((!!f->operation)<<5) |
  ((!!f->stream)<<6) | ((!!f->sequence)<<7) | ((!!f->expiry)<<8) |
  ((!!f->left)<<9) | ((!!f->right)<<10) | ((!!f->context)<<11) |
  ((original_now-e->hello_sent>10*MS)<<12);
 u8 bytes[ACTRYN_WIRE_SIZE]; actryn_pack(f,bytes);
 h8_record(H8_DECISION,original_now,e->hello_sent,0,e->h8_processing_id,
           mask,rejected,bytes,sizeof(bytes),rejected?2:1);
}
static void h8_close(u32 rank,u32 reason,int result)
{
 if(!result) h8_record(H8_CLOSE,now_ns(),0,0,rank,reason,0,NULL,0,3);
}
/* One atomic snapshot fits the existing root-readable sysfs parameter path.
 * No debugfs lifetime or additional device is introduced. */
static int h8_snapshot_get(char *buf,const struct kernel_param *unused)
{
 unsigned long irq; size_t size=sizeof(h8_dump);
 BUILD_BUG_ON(sizeof(struct h8_record)!=208);
 BUILD_BUG_ON(sizeof(h8_dump)!=1728);
 BUILD_BUG_ON(sizeof(h8_dump)*2+1>PAGE_SIZE);
 spin_lock_irqsave(&h8_lock,irq);
 bin2hex(buf,&h8_dump,size);
 spin_unlock_irqrestore(&h8_lock,irq);
 buf[size*2]='\n'; return size*2+1;
}
static const struct kernel_param_ops h8_snapshot_ops={ .get=h8_snapshot_get };
module_param_cb(hello8_snapshot,&h8_snapshot_ops,NULL,0400);
MODULE_PARM_DESC(hello8_snapshot,"Read-only bounded cold-HELLO diagnostic8 snapshot; no reset");
