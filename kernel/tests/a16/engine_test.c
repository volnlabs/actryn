/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include "engine.h"
static struct a16_engine e;
static unsigned char output[512];
static size_t used,limit=sizeof(output);
static int write_error;
static ptrdiff_t writer(void *unused,const unsigned char *p,size_t n)
{
 (void)unused;
 if(write_error) return -EIO;
 if(n>limit) n=limit;
 assert(n<=sizeof(output)-used); memcpy(output+used,p,n); used+=n; return (ptrdiff_t)n;
}
static struct actryn_request request(unsigned op)
{
 struct actryn_request r={.version=1,.opcode=op};
 memcpy(r.runtime_nonce,e.status.runtime_nonce,16); return r;
}
static void drain(void)
{ struct actryn_event event; while(!a16_event(&e,&event)) {} }
static void step(void)
{ a16_time(&e,e.now+A16_MS); a16_tick(&e,writer,NULL); }
static void reply(unsigned kind)
{
 struct actryn_frame f; unsigned char bytes[ACTRYN_ENCODED_MAX]; size_t start=0,n;
 step(); assert(used && output[used-1]==0);
 while(start<used && !output[start]) start++;
 assert(!actryn_decode(output+start,used-start-1,&f));
 if(kind==AW_HELLO_ACK) { assert(f.kind==AW_HELLO); f.device[0]=1;
  f.boot=1; f.session=1; f.status=1; }
 else { assert((kind==AW_BASELINE && f.kind==AW_REARM) ||
  (kind==AW_STARTED && f.kind==AW_START) || (kind==AW_APPLIED && f.kind==AW_SAMPLE) ||
  (kind==AW_QUIESCED && f.kind==AW_QUIESCE)); }
 f.kind=kind; f.controller_ns=e.now; used=0;
 n=actryn_encode(&f,bytes); a16_receive(&e,bytes,n); step(); drain();
}
static void boot(void)
{
 unsigned char nonce[16]={1}; struct actryn_request r={.version=1,.opcode=ACTRYN_HANDSHAKE};
 a16_init(&e); a16_time(&e,100000*A16_MS); e.owner=true;
 used=0; limit=sizeof(output); write_error=0;
 assert(!a16_request(&e,ACTRYN_ADMIN,&r,nonce)); reply(AW_HELLO_ACK);
 r=(struct actryn_request){.version=1,.opcode=ACTRYN_REARM};
 assert(!a16_request(&e,ACTRYN_ADMIN,&r,NULL)); reply(AW_BASELINE);
 r=(struct actryn_request){.version=1,.opcode=ACTRYN_GRANT,.instance=1,.deadline_ns=e.now+15000*A16_MS};
 assert(!a16_request(&e,ACTRYN_ADMIN,&r,NULL));
 r=request(ACTRYN_HEALTH); r.deadline_ns=e.now+1500*A16_MS;
 assert(!a16_request(&e,ACTRYN_RUNTIME,&r,NULL));
 r=request(ACTRYN_ACTIVATE); r.grant=e.status.grant; r.instance=1;
 assert(!a16_request(&e,ACTRYN_RUNTIME,&r,NULL)); drain();
}
static struct actryn_request allocate(void)
{
 struct actryn_request r=request(ACTRYN_OBSERVE);
 r.observation=e.observation.observation+1; r.context_revision=1;
 r.acquired_earliest_ns=r.acquired_latest_ns=e.now; r.valid_until_ns=e.now+900*A16_MS;
 assert(!a16_request(&e,ACTRYN_ACQUISITION,&r,NULL));
 r=request(ACTRYN_ALLOCATE); r.grant=e.status.grant; r.instance=1;
 r.observation=e.observation.observation; r.context_revision=1; r.deadline_ns=e.now+5000*A16_MS;
 assert(!a16_request(&e,ACTRYN_RUNTIME,&r,NULL));
 assert(e.status.operation_state==ACTRYN_OP_ALLOCATED && used==0 && !e.tx_busy);
 return r;
}
static struct actryn_request running(void)
{
 struct actryn_request r=allocate(); r.opcode=ACTRYN_START;
 assert(!a16_request(&e,ACTRYN_RUNTIME,&r,NULL)); reply(AW_STARTED);
 assert(e.status.operation_state==ACTRYN_OP_RUNNING); return r;
}
static struct actryn_request op(unsigned opcode)
{
 struct actryn_request r=request(opcode); r.grant=e.status.grant;
 r.operation=e.status.operation; r.stream=e.status.stream; return r;
}
static struct actryn_request sample(void)
{
 struct actryn_request r=op(ACTRYN_SAMPLE); r.sequence=1; r.observation=e.observation.observation;
 r.context_revision=1; r.deadline_ns=e.now+400*A16_MS; return r;
}
static void lifecycle(void)
{
 struct actryn_request r,next; uint64_t first;
 boot(); running(); first=e.status.operation;
 r=op(ACTRYN_FINISH); assert(!a16_request(&e,ACTRYN_RUNTIME,&r,NULL));
 next=request(ACTRYN_ALLOCATE); next.grant=e.status.grant; next.instance=1;
 next.observation=e.observation.observation; next.context_revision=1; next.deadline_ns=e.now+3000*A16_MS;
 assert(a16_request(&e,ACTRYN_RUNTIME,&next,NULL)<0);
 reply(AW_QUIESCED); assert(e.status.operation_state==ACTRYN_OP_RECONCILED);
 r=running(); assert(r.operation>first); r=op(ACTRYN_CANCEL);
 assert(!a16_request(&e,ACTRYN_RUNTIME,&r,NULL)); reply(AW_QUIESCED);
 assert(e.status.reason==ACTRYN_CANCELLED && e.authorized);
 boot(); r=allocate(); next=op(ACTRYN_CANCEL);
 assert(!a16_request(&e,ACTRYN_RUNTIME,&next,NULL)); r.opcode=ACTRYN_START;
 assert(a16_request(&e,ACTRYN_RUNTIME,&r,NULL)<0); reply(AW_QUIESCED);
}
static void rejection(void)
{
 struct actryn_request r; uint64_t deadline;
 boot(); running(); r=sample(); r.left_permille=201;
 assert(a16_request(&e,ACTRYN_RUNTIME,&r,NULL)<0);
 r=sample(); r.reserved[0]=1; assert(a16_request(&e,ACTRYN_RUNTIME,&r,NULL)==-EINVAL);
 r=sample(); r.deadline_ns=e.health_deadline+1; assert(a16_request(&e,ACTRYN_RUNTIME,&r,NULL)<0);
 r=sample(); assert(!a16_request(&e,ACTRYN_RUNTIME,&r,NULL)); deadline=e.sample.deadline_ns;
 assert(!a16_request(&e,ACTRYN_RUNTIME,&r,NULL)); assert(e.sample.deadline_ns==deadline);
 r.left_permille=1; assert(a16_request(&e,ACTRYN_RUNTIME,&r,NULL)==-EEXIST);
 a16_time(&e,deadline); a16_tick(&e,writer,NULL);
 assert(e.status.state==ACTRYN_FAULT_LATCHED && e.status.operation_state==ACTRYN_OP_UNKNOWN);
 boot(); r=op(ACTRYN_REVOKE); r.operation=r.stream=0;
 assert(!a16_request(&e,ACTRYN_ADMIN,&r,NULL));
 r=request(ACTRYN_ACTIVATE); r.grant=e.status.grant; r.instance=1;
 assert(a16_request(&e,ACTRYN_RUNTIME,&r,NULL)<0);
}
static void partial_writes(void)
{
 size_t cut;
 for(cut=0;cut<ACTRYN_ENCODED_MAX;cut++) {
  struct actryn_request r; struct actryn_frame f; unsigned char original[ACTRYN_ENCODED_MAX];
  size_t n;
  boot(); running(); r=sample(); assert(!a16_request(&e,ACTRYN_RUNTIME,&r,NULL));
  limit=cut; step(); n=actryn_encode(&e.tx_frame,original); assert(n==ACTRYN_ENCODED_MAX);
  assert(used==cut); r=op(ACTRYN_CANCEL); assert(!a16_request(&e,ACTRYN_RUNTIME,&r,NULL));
  limit=sizeof(output); step(); step();
  if(cut) { assert(!memcmp(output,original,n)); assert(!actryn_decode(output+n,used-n-1,&f)); }
  else assert(!actryn_decode(output,used-1,&f));
  assert(f.kind==AW_QUIESCE && e.status.operation_state==ACTRYN_OP_CLOSING);
  /* An error at the identical offset must retain the original safety horizon. */
  boot(); running(); r=sample(); assert(!a16_request(&e,ACTRYN_RUNTIME,&r,NULL));
  limit=cut; step(); write_error=1; step();
  assert(e.status.state==ACTRYN_FAULT_LATCHED && e.status.operation_state==ACTRYN_OP_UNKNOWN);
  assert(e.resync_after==(cut?r.deadline_ns:0));
  {
   unsigned char nonce[16]={2}; struct actryn_request recovery={.version=1,.opcode=ACTRYN_RECOVER};
   assert(!a16_request(&e,ACTRYN_ADMIN,&recovery,nonce)); write_error=0; limit=sizeof(output);
   if(cut) { a16_time(&e,r.deadline_ns-1); a16_tick(&e,writer,NULL); assert(used==cut); }
   a16_time(&e,r.deadline_ns); a16_tick(&e,writer,NULL);
   assert(output[cut]==0); assert(!actryn_decode(output+cut+1,used-cut-2,&f));
   assert(f.kind==AW_HELLO && f.nonce[0]==2 && !e.authorized);
  }
 }
}
static void receipt_safety(void)
{
 struct actryn_request r; struct actryn_frame f; unsigned char bytes[ACTRYN_ENCODED_MAX]; size_t n;
 boot(); running(); r=sample(); assert(!a16_request(&e,ACTRYN_RUNTIME,&r,NULL)); step();
 assert(!actryn_decode(output,used-1,&f)); f.kind=AW_APPLIED; f.controller_ns=e.now;
 f.nonce[0]^=1; n=actryn_encode(&f,bytes); a16_receive(&e,bytes,n); step();
 assert(e.awaiting && e.status.sequence==0 && e.status.state==ACTRYN_ACTIVE);
 f.nonce[0]^=1; n=actryn_encode(&f,bytes); a16_time(&e,r.deadline_ns);
 a16_receive(&e,bytes,n); a16_tick(&e,writer,NULL);
 assert(e.status.state==ACTRYN_FAULT_LATCHED && e.status.reason==ACTRYN_EXPIRED);
 boot(); running(); memset(&f,0,sizeof(f)); f.kind=AW_FAULT;
 memcpy(f.device,e.status.device_identity,16); f.boot=e.status.controller_boot+1;
 n=actryn_encode(&f,bytes); a16_receive(&e,bytes,n); step();
 assert(e.status.state==ACTRYN_FAULT_LATCHED && e.status.reason==ACTRYN_TRANSPORT);
 boot(); running(); a16_owner_lost(&e);
 assert(!e.authorized && e.status.operation_state==ACTRYN_OP_UNKNOWN && e.status.reason==ACTRYN_OWNER_LOST);
}
static void capacity(void)
{
 struct actryn_request r; struct actryn_frame f={.kind=AW_OBSERVATION,.sequence=1};
 unsigned char bytes[ACTRYN_ENCODED_MAX]; unsigned i; size_t n=actryn_encode(&f,bytes);
 boot(); running(); drain();
 for(i=0;i<=A16_EVENTS;i++) { r=request(ACTRYN_HEALTH); r.deadline_ns=e.now+1500*A16_MS; a16_request(&e,ACTRYN_RUNTIME,&r,NULL); }
 assert(e.status.state==ACTRYN_FAULT_LATCHED && e.status.reason==ACTRYN_EVIDENCE_LOST && e.status.events_lost);
 boot(); for(i=0;i<=A16_RX;i++) a16_receive(&e,bytes,n);
 assert(e.rx_count==A16_RX && e.status.state==ACTRYN_FAULT_LATCHED);
 boot(); running(); r=sample(); assert(!a16_request(&e,ACTRYN_RUNTIME,&r,NULL));
 limit=0; step(); assert(e.tx_busy && e.tx_off==0);
 a16_time(&e,r.deadline_ns); a16_tick(&e,writer,NULL);
 assert(e.status.state==ACTRYN_FAULT_LATCHED && e.status.reason==ACTRYN_EXPIRED);
}
static void closure_idempotence(void)
{
 for(unsigned initial=ACTRYN_CANCEL;initial<=ACTRYN_REVOKE;initial++)
 for(size_t cut=0;cut<=ACTRYN_ENCODED_MAX;cut++) {
  struct actryn_request r; unsigned char expected[ACTRYN_ENCODED_MAX];
  uint64_t deadline,transaction; size_t length;
  boot(); running(); r=op(initial);
  if(initial==ACTRYN_REVOKE) r.operation=r.stream=0;
  assert(!a16_request(&e,initial==ACTRYN_REVOKE?ACTRYN_ADMIN:ACTRYN_RUNTIME,&r,NULL));
  limit=cut; step(); deadline=e.close_deadline; transaction=e.next_transaction;
  length=actryn_encode(&e.tx_frame,expected);
  r=op(ACTRYN_REVOKE); r.operation=r.stream=0;
  assert(!a16_request(&e,ACTRYN_ADMIN,&r,NULL));
  assert(!a16_request(&e,ACTRYN_ADMIN,&r,NULL));
  limit=sizeof(output); step(); step();
  assert(e.next_transaction==transaction && used==length && !memcmp(output,expected,length));
  assert(e.awaiting && e.close_deadline==deadline && !e.authorized);
  reply(AW_QUIESCED);
  assert(e.status.state==ACTRYN_READY && e.status.reason==ACTRYN_GRANT_REVOKED);
 }
}
static void freshness_and_immutable_horizon(void)
{
 struct actryn_request r,next; uint64_t cutoff;
 boot(); running(); r=request(ACTRYN_OBSERVE); r.observation=2; r.context_revision=1;
 r.acquired_earliest_ns=e.now; r.acquired_latest_ns=e.now+1; r.valid_until_ns=e.now+900*A16_MS;
 assert(a16_request(&e,ACTRYN_ACQUISITION,&r,NULL)==-EINVAL);
 r.acquired_latest_ns=e.now; r.acquired_earliest_ns=e.now-1000*A16_MS-1;
 assert(a16_request(&e,ACTRYN_ACQUISITION,&r,NULL)==-EINVAL);
 r.acquired_earliest_ns=e.now-900*A16_MS;
 assert(!a16_request(&e,ACTRYN_ACQUISITION,&r,NULL));
 r=sample(); r.deadline_ns=e.now+200*A16_MS;
 assert(a16_request(&e,ACTRYN_RUNTIME,&r,NULL)==-EINVAL);
 boot(); running(); r=sample(); r.left_permille=100;
 assert(!a16_request(&e,ACTRYN_RUNTIME,&r,NULL)); step();
 assert(e.status.state==ACTRYN_FAULT_LATCHED && used==0); /* Slew lacks 100 ms credit. */
 boot(); running(); r=sample(); cutoff=r.deadline_ns;
 assert(!a16_request(&e,ACTRYN_RUNTIME,&r,NULL)); limit=1; step();
 a16_time(&e,e.now+20*A16_MS); next=r; next.sequence=2; next.deadline_ns=e.now+400*A16_MS;
 assert(!a16_request(&e,ACTRYN_RUNTIME,&next,NULL));
 assert(e.tx_deadline==cutoff && e.mailbox_valid);
 a16_time(&e,cutoff); limit=sizeof(output); a16_tick(&e,writer,NULL);
 assert(e.status.state==ACTRYN_FAULT_LATCHED && e.status.reason==ACTRYN_EXPIRED && used==1);
 assert(e.resync_after==cutoff);
}
static void handshake_and_receipt_boundaries(void)
{
 unsigned char nonce[16]={7},bytes[ACTRYN_ENCODED_MAX],bad[]={2,0};
 struct actryn_request r={.version=1,.opcode=ACTRYN_HANDSHAKE}; struct actryn_frame f;
 uint64_t timeout;
 a16_init(&e); a16_time(&e,100000*A16_MS); e.owner=true;
 used=0; limit=sizeof(output); write_error=0;
 assert(!a16_request(&e,ACTRYN_ADMIN,&r,nonce)); timeout=e.receipt_deadline;
 a16_receive(&e,bad,sizeof(bad)); assert(e.status.state==ACTRYN_INHIBITED);
 reply(AW_HELLO_ACK); assert(e.handshaken);
 a16_receive(&e,bad,sizeof(bad)); assert(e.status.state==ACTRYN_FAULT_LATCHED);
 r.opcode=ACTRYN_RECOVER; nonce[0]=8; used=0;
 assert(!a16_request(&e,ACTRYN_ADMIN,&r,nonce)); timeout=e.receipt_deadline;
 for(unsigned i=0;i<10;i++) { a16_receive(&e,bad,sizeof(bad)); step(); }
 assert(e.receipt_deadline==timeout);
 a16_time(&e,timeout); a16_tick(&e,writer,NULL);
 assert(e.status.state==ACTRYN_FAULT_LATCHED && !e.handshaken);
 boot(); running(); r=sample(); assert(!a16_request(&e,ACTRYN_RUNTIME,&r,NULL)); step();
 f=e.awaited; f.kind=AW_APPLIED; f.controller_ns=e.now; f.left=1;
 a16_receive(&e,bytes,actryn_encode(&f,bytes)); step();
 assert(e.status.state==ACTRYN_FAULT_LATCHED && e.status.reason==ACTRYN_PROTOCOL);
 boot(); running(); e.operation_deadline=e.now+100*A16_MS; /* Short operation expires before receipt timeout. */
 r=op(ACTRYN_FINISH); assert(!a16_request(&e,ACTRYN_RUNTIME,&r,NULL)); step();
 f=e.awaited; f.kind=AW_QUIESCED; f.controller_ns=e.now;
 a16_time(&e,e.operation_deadline); a16_receive(&e,bytes,actryn_encode(&f,bytes));
 a16_tick(&e,writer,NULL);
 assert(e.status.operation_state==ACTRYN_OP_UNKNOWN && e.status.reason==ACTRYN_EXPIRED);
 boot(); e.event_sequence=UINT64_MAX; e.status.events_lost=UINT32_MAX-1;
 r=request(ACTRYN_HEALTH); r.deadline_ns=e.now+1000*A16_MS;
 (void)a16_request(&e,ACTRYN_RUNTIME,&r,NULL); (void)a16_request(&e,ACTRYN_RUNTIME,&r,NULL);
 assert(e.event_sequence==UINT64_MAX && e.status.events_lost==UINT32_MAX);
 assert(e.status.state==ACTRYN_FAULT_LATCHED);
}
int main(void)
{
 lifecycle(); rejection(); partial_writes(); receipt_safety(); capacity(); closure_idempotence();
 freshness_and_immutable_horizon(); handshake_and_receipt_boundaries();
 puts("PASS independent A16 lifecycle, freshness, limits, partial writes, closure, receipts, owner loss and capacity");
 return 0;
}
