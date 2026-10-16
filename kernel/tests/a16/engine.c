/* SPDX-License-Identifier: GPL-2.0-only */
#include "engine.h"
#include <errno.h>
#include <string.h>
#define MS A16_MS
#define S e->status
static bool zero(const void *p,size_t n)
{ const unsigned char *b=p; while(n--) if(*b++) return false; return true; }
void a16_init(struct a16_engine *e) { memset(e,0,sizeof(*e)); S.version=1; S.context_revision=1; }
void a16_time(struct a16_engine *e,uint64_t now) { e->now=now; }
struct actryn_status a16_status(struct a16_engine *e)
{
 S.now_ns=e->now; S.flags=(e->handshaken?1:0)|(e->tx_busy&&e->tx_off?2:0)|
  (e->awaiting?4:0)|(e->authorized?8:0); return S;
}
static void fault(struct a16_engine *e,unsigned reason)
{
 if(e->tx_busy && e->tx_off && e->tx_frame.expiry && e->tx_deadline>e->resync_after)
  e->resync_after=e->tx_deadline;
 S.state=ACTRYN_FAULT_LATCHED; S.operation_state=S.operation?ACTRYN_OP_UNKNOWN:ACTRYN_OP_NONE;
 S.reason=reason; e->handshaken=e->authorized=e->tx_busy=e->awaiting=e->mailbox_valid=false;
 e->sync_deadline=0;
}
static void record(struct a16_engine *e,unsigned kind)
{
 if(e->event_count==A16_EVENTS || e->event_sequence==UINT64_MAX) {
  if(S.events_lost<UINT32_MAX) S.events_lost++;
  fault(e,ACTRYN_EVIDENCE_LOST); return;
 }
 e->events[e->event_head]=(struct actryn_event){.sequence=++e->event_sequence,
  .captured_ns=e->now,.kind=kind,.status=a16_status(e)};
 e->event_head=(e->event_head+1)%A16_EVENTS; e->event_count++;
}
static void fail(struct a16_engine *e,unsigned reason)
{ fault(e,reason); record(e,ACTRYN_EVENT_CLOSURE|reason); }
void a16_owner_lost(struct a16_engine *e) { e->owner=false; fail(e,ACTRYN_OWNER_LOST); }
int a16_event(struct a16_engine *e,struct actryn_event *v)
{
 if(!e->event_count) return -EAGAIN;
 *v=e->events[e->event_tail]; e->event_tail=(e->event_tail+1)%A16_EVENTS; e->event_count--; return 0;
}
static int transaction(struct a16_engine *e,actryn_u64 *v)
{ if(e->next_transaction==UINT64_MAX) return -EOVERFLOW; *v=++e->next_transaction; return 0; }
static void frame(struct a16_engine *e,struct actryn_frame *f,unsigned kind)
{
 memset(f,0,sizeof(*f)); f->kind=kind; f->boot=S.controller_boot; f->session=S.controller_session;
 memcpy(f->device,S.device_identity,16); memcpy(f->nonce,S.runtime_nonce,16); f->context=1;
}
static bool epoch(struct a16_engine *e,const struct actryn_request *r)
{ return !memcmp(S.runtime_nonce,r->runtime_nonce,16); }
static bool operation(struct a16_engine *e,const struct actryn_request *r)
{ return epoch(e,r) && r->operation && r->operation==S.operation && r->stream==S.stream && r->grant==S.grant; }
static bool wire_epoch(struct a16_engine *e,const struct actryn_frame *f)
{ return !memcmp(S.device_identity,f->device,16) && !memcmp(S.runtime_nonce,f->nonce,16) &&
 f->boot==S.controller_boot && f->session==S.controller_session; }
static int controller_time(struct a16_engine *e,uint64_t host,actryn_u64 *out)
{
 uint64_t delta;
 if(!e->handshaken || host<e->map_host || e->now-e->map_host>=60000*MS) return -ESTALE;
 delta=host-e->map_host;
 if(delta>120000*MS || e->map_ctl>UINT64_MAX-delta) return -ERANGE;
 *out=e->map_ctl+delta-delta/10000; return 0;
}
static int queue(struct a16_engine *e,const struct actryn_frame *f,uint64_t deadline)
{
 if(e->tx_busy || e->awaiting) return -EBUSY;
 e->tx_frame=*f; e->tx_len=actryn_encode(f,e->tx); e->tx_off=0;
 if(f->kind==AW_HELLO) { memmove(e->tx+1,e->tx,e->tx_len); e->tx[0]=0; e->tx_len++; }
 e->tx_busy=true; e->tx_deadline=deadline;
 e->receipt_deadline=(e->now>e->resync_after?e->now:e->resync_after)+1000*MS;
 S.transaction=f->transaction; return 0;
}
static void health(struct a16_engine *e)
{
 if(e->authorized && (!e->owner || e->now>=e->grant_deadline)) {
  fail(e,e->owner?ACTRYN_EXPIRED:ACTRYN_OWNER_LOST); return;
 }
 if(S.state>=ACTRYN_FAULT_LATCHED) return;
 if((e->tx_busy||e->awaiting) && e->now>=e->receipt_deadline) { fail(e,ACTRYN_TRANSPORT); return; }
 if(S.state!=ACTRYN_ACTIVE && S.state!=ACTRYN_REVOKING) return;
 if(!e->owner) fail(e,ACTRYN_OWNER_LOST);
 else if(e->now>=e->grant_deadline || (S.operation_state!=ACTRYN_OP_NONE &&
  S.operation_state!=ACTRYN_OP_RECONCILED && e->now>=e->operation_deadline)) fail(e,ACTRYN_EXPIRED);
 else if(e->now>=e->health_deadline) fail(e,ACTRYN_EVIDENCE_LOST);
 else if(e->now-e->map_host>=60000*MS) fail(e,ACTRYN_EXPIRED);
 else if(e->close_deadline && e->now>=e->close_deadline) fail(e,ACTRYN_TRANSPORT);
}
static bool observation(struct a16_engine *e,uint64_t id)
{ return id && id==e->observation.observation && e->observation.context_revision==1 &&
 e->now>=e->observation.acquired_latest_ns && e->now<e->observation.valid_until_ns &&
 e->now-e->observation.acquired_earliest_ns<=1000*MS; }
static int canonical(const struct actryn_request *r)
{
 struct actryn_request z=*r;
 if(r->version!=1 || r->flags || r->reserved0 || !zero(r->reserved,sizeof(r->reserved))) return -EINVAL;
 z.version=z.opcode=0;
 switch(r->opcode) {
 case ACTRYN_HANDSHAKE: case ACTRYN_REARM: case ACTRYN_RECOVER: break;
 case ACTRYN_GRANT: z.instance=z.deadline_ns=0; memset(z.digest,0,32); break;
 case ACTRYN_ACTIVATE: z.grant=z.instance=0; memset(z.runtime_nonce,0,16); break;
 case ACTRYN_OBSERVE: memset(z.runtime_nonce,0,16); z.observation=z.acquired_earliest_ns=0;
  z.acquired_latest_ns=z.valid_until_ns=z.context_revision=0; break;
 case ACTRYN_ALLOCATE: case ACTRYN_START: memset(z.runtime_nonce,0,16);
  z.grant=z.instance=z.operation=z.stream=z.deadline_ns=z.observation=z.context_revision=0;
  memset(z.digest,0,32); break;
 case ACTRYN_SAMPLE: memset(z.runtime_nonce,0,16); z.grant=z.operation=z.stream=z.sequence=0;
  z.deadline_ns=z.observation=z.context_revision=0; z.left_permille=z.right_permille=0;
  memset(z.digest,0,32); break;
 case ACTRYN_FINISH: case ACTRYN_CANCEL: memset(z.runtime_nonce,0,16); z.grant=z.operation=z.stream=0; break;
 case ACTRYN_REVOKE: memset(z.runtime_nonce,0,16); z.grant=0; break;
 case ACTRYN_HEALTH: memset(z.runtime_nonce,0,16); z.deadline_ns=0; break;
 default: return -ENOTTY;
 }
 return zero(&z,sizeof(z))?0:-EINVAL;
}
static void close_operation(struct a16_engine *e,unsigned rank,unsigned reason)
{
 if(actryn_merge_close(&e->close,rank,reason,S.grant,S.operation,S.grant,S.operation,&e->close_serial)) {
  fail(e,ACTRYN_PROTOCOL); return;
 }
 if(S.state==ACTRYN_FAULT_LATCHED) return;
 if(S.operation_state==ACTRYN_OP_CLOSING) {
  if(rank==2) {
   bool changed=S.state!=ACTRYN_REVOKING;
   S.state=ACTRYN_REVOKING; S.reason=reason; e->authorized=false; S.instance=0;
   if(changed) record(e,ACTRYN_EVENT_CLOSURE|reason);
  }
  return;
 }
 if(rank==2) { e->authorized=false; S.instance=0;
  if(S.state==ACTRYN_INHIBITED) return;
  S.state=ACTRYN_REVOKING; S.reason=reason;
 }
 if(S.operation && S.operation_state!=ACTRYN_OP_RECONCILED) {
  if(S.operation_state!=ACTRYN_OP_CLOSING) S.reason=e->close.reason;
  S.operation_state=ACTRYN_OP_CLOSING; e->quiesce=true;
 } else if(rank==2) S.state=ACTRYN_READY;
 e->mailbox_valid=false; e->awaiting=false;
 if(e->tx_busy && !e->tx_off) e->tx_busy=false;
 if(!e->close_deadline && e->quiesce) e->close_deadline=e->now+1000*MS;
 record(e,ACTRYN_EVENT_CLOSURE|reason);
}
int a16_request(struct a16_engine *e,unsigned role,struct actryn_request *r,const unsigned char nonce[16])
{
 struct actryn_frame f; int rc=canonical(r); actryn_u64 expiry;
 if(rc) return rc;
 health(e);
 if(role<ACTRYN_ADMIN || role>ACTRYN_ACQUISITION || (role!=ACTRYN_ADMIN && !e->owner)) return -EPERM;
 switch(r->opcode) {
 case ACTRYN_HANDSHAKE: case ACTRYN_RECOVER:
  if(role!=ACTRYN_ADMIN || (S.state!=ACTRYN_INHIBITED && S.state!=ACTRYN_FAULT_LATCHED) ||
     !nonce || zero(nonce,16) || e->tx_busy) return -EPERM;
  S.state=ACTRYN_INHIBITED; S.operation_state=ACTRYN_OP_NONE;
  S.grant=S.instance=S.operation=S.stream=S.controller_boot=S.controller_session=S.controller_ns=0;
  S.observation=0; e->observation_sequence=e->last_applied_ctl=e->close_deadline=0;
  e->handshaken=e->authorized=e->awaiting=e->quiesce=e->mailbox_valid=false;
  memset(&e->observation,0,sizeof(e->observation)); memset(&e->close,0,sizeof(e->close));
  memcpy(S.runtime_nonce,nonce,16); memset(&f,0,sizeof(f)); f.kind=AW_HELLO;
  memcpy(f.nonce,nonce,16); e->next_transaction=0; transaction(e,&f.transaction);
  rc=queue(e,&f,0); e->sync_deadline=e->receipt_deadline; break;
 case ACTRYN_REARM:
  if(role!=ACTRYN_ADMIN || S.state!=ACTRYN_INHIBITED || !e->handshaken) return -EPERM;
  frame(e,&f,AW_REARM); rc=transaction(e,&f.transaction); if(!rc) rc=queue(e,&f,0); break;
 case ACTRYN_GRANT:
  if(role!=ACTRYN_ADMIN || S.state!=ACTRYN_READY || !e->owner || !r->instance ||
     actryn_window(e->now,r->deadline_ns,60000*MS)) return -EPERM;
  if(S.grant==UINT64_MAX) return -EOVERFLOW;
  r->grant=++S.grant; S.instance=r->instance; e->grant_deadline=S.deadline_ns=r->deadline_ns;
  memcpy(r->runtime_nonce,S.runtime_nonce,16); e->authorized=true; break;
 case ACTRYN_ACTIVATE:
  if(role!=ACTRYN_RUNTIME || !epoch(e,r) || r->grant!=S.grant || r->instance!=S.instance ||
     !r->instance || !e->authorized || S.state!=ACTRYN_READY || e->now>=e->grant_deadline ||
     e->now>=e->health_deadline) return -EPERM;
  S.state=ACTRYN_ACTIVE; S.operation_state=ACTRYN_OP_NONE; S.operation=S.stream=S.reason=0; break;
 case ACTRYN_HEALTH:
  if(role!=ACTRYN_RUNTIME || !epoch(e,r) || actryn_window(e->now,r->deadline_ns,2000*MS)) return -EINVAL;
  e->health_deadline=r->deadline_ns; break;
 case ACTRYN_OBSERVE:
  if(role!=ACTRYN_ACQUISITION || !epoch(e,r) || !r->observation || r->observation<=e->observation.observation ||
    r->context_revision!=1 || r->acquired_earliest_ns>r->acquired_latest_ns || r->acquired_latest_ns>e->now ||
    e->now-r->acquired_earliest_ns>1000*MS || actryn_window(e->now,r->valid_until_ns,1000*MS)) return -EINVAL;
  e->observation=*r; S.observation=r->observation; break;
 case ACTRYN_ALLOCATE:
  if(role!=ACTRYN_RUNTIME || !epoch(e,r) || r->grant!=S.grant || r->instance!=S.instance ||
    S.state!=ACTRYN_ACTIVE || r->operation || r->stream ||
    (S.operation_state!=ACTRYN_OP_NONE && S.operation_state!=ACTRYN_OP_RECONCILED) ||
    r->context_revision!=1 || !observation(e,r->observation) ||
    actryn_window(e->now,r->deadline_ns,10000*MS) || r->deadline_ns>e->grant_deadline) return -EINVAL;
  if(e->next_operation==UINT64_MAX) return -EOVERFLOW;
  r->operation=r->stream=++e->next_operation; S.operation=r->operation; S.stream=r->stream;
  S.sequence=S.reason=0; S.operation_state=ACTRYN_OP_ALLOCATED; e->allocation=*r;
  e->operation_deadline=r->deadline_ns; memset(&e->sample,0,sizeof(e->sample));
  memset(&e->close,0,sizeof(e->close)); break;
 case ACTRYN_START:
  if(role!=ACTRYN_RUNTIME || !operation(e,r) || S.state!=ACTRYN_ACTIVE || S.operation_state!=ACTRYN_OP_ALLOCATED ||
    r->instance!=e->allocation.instance || r->deadline_ns!=e->allocation.deadline_ns ||
    r->observation!=e->allocation.observation || r->context_revision!=1 ||
    memcmp(r->digest,e->allocation.digest,32) || !observation(e,r->observation) || e->now>=r->deadline_ns) return -ESTALE;
  frame(e,&f,AW_START); f.grant=S.grant; f.operation=S.operation; f.stream=S.stream;
  rc=controller_time(e,r->deadline_ns,&f.expiry); if(!rc) rc=transaction(e,&f.transaction);
  if(!rc) rc=queue(e,&f,e->operation_deadline);
  if(!rc) S.operation_state=ACTRYN_OP_STARTING;
  break;
 case ACTRYN_SAMPLE:
  if(role!=ACTRYN_RUNTIME || !operation(e,r) || S.state!=ACTRYN_ACTIVE || S.operation_state!=ACTRYN_OP_RUNNING ||
    !r->sequence || r->context_revision!=1 || !observation(e,r->observation) ||
    actryn_window(e->now,r->deadline_ns,500*MS) || r->deadline_ns>e->operation_deadline ||
    r->deadline_ns>e->grant_deadline || r->deadline_ns>e->health_deadline ||
    r->deadline_ns>e->observation.valid_until_ns || r->deadline_ns-e->observation.acquired_earliest_ns>1000*MS ||
    r->left_permille < -200 || r->left_permille>200 || r->right_permille < -200 || r->right_permille>200) return -EINVAL;
  if(r->sequence==e->sample.sequence) return memcmp(r,&e->sample,sizeof(*r))?-EEXIST:0;
  if(r->sequence<e->sample.sequence) return -ESTALE;
  rc=controller_time(e,r->deadline_ns,&expiry); if(rc) return rc;
  frame(e,&f,AW_SAMPLE); f.grant=S.grant; f.operation=S.operation; f.stream=S.stream;
  f.sequence=r->sequence; f.expiry=expiry; f.left=r->left_permille; f.right=r->right_permille;
  rc=transaction(e,&f.transaction); if(rc) return rc;
  e->sample=*r; e->mailbox=f; e->mailbox_valid=true; break;
 case ACTRYN_FINISH: case ACTRYN_CANCEL:
  if((role!=ACTRYN_RUNTIME && role!=ACTRYN_ADMIN) || !operation(e,r)) return -ESTALE;
  if(S.operation_state!=ACTRYN_OP_CLOSING && S.operation_state!=ACTRYN_OP_RECONCILED)
   close_operation(e,1,r->opcode==ACTRYN_FINISH?ACTRYN_SKILL_FINISHED:ACTRYN_CANCELLED);
  break;
 case ACTRYN_REVOKE:
  if(role!=ACTRYN_ADMIN || !r->grant || !epoch(e,r) || r->grant!=S.grant) return -ESTALE;
  close_operation(e,2,ACTRYN_GRANT_REVOKED); break;
 default: return -ENOTTY;
 }
 if(!rc) record(e,ACTRYN_EVENT_REQUEST|r->opcode);
 return rc;
}
static void receipt(struct a16_engine *e,const struct actryn_frame *f)
{
 const struct actryn_frame *a=&e->awaited;
 if(f->kind==AW_HELLO_ACK && e->awaiting && a->kind==AW_HELLO &&
    f->transaction==a->transaction && !memcmp(f->nonce,S.runtime_nonce,16)) {
  if(f->status!=1 || !f->boot || !f->session || zero(f->device,16) || f->grant ||
    f->operation || f->stream || f->sequence || f->expiry || f->left || f->right || f->context ||
    e->now-e->hello_sent>10*MS) { fail(e,ACTRYN_PROTOCOL); return; }
  memcpy(S.device_identity,f->device,16); S.controller_boot=f->boot; S.controller_session=f->session;
  e->map_host=e->now; e->map_ctl=S.controller_ns=f->controller_ns;
  e->handshaken=true; e->sync_deadline=0; e->awaiting=false; record(e,ACTRYN_EVENT_WIRE|f->kind); return;
 }
 if(e->handshaken && !memcmp(f->device,S.device_identity,16) && (f->boot>S.controller_boot ||
   (f->boot==S.controller_boot && f->session>S.controller_session))) { fail(e,ACTRYN_TRANSPORT); return; }
 if(!wire_epoch(e,f)) return;
 if(f->kind==AW_FAULT) { fail(e,ACTRYN_TRANSPORT); return; }
 if(f->kind==AW_OBSERVATION) {
  if(f->context!=1 || f->transaction || f->expiry || !f->sequence ||
    f->sequence<=e->observation_sequence || f->controller_ns<S.controller_ns) return;
  e->observation_sequence=f->sequence; S.left_encoder=f->left_encoder; S.right_encoder=f->right_encoder;
  S.controller_ns=f->controller_ns; record(e,ACTRYN_EVENT_WIRE|f->kind); return;
 }
 if(!e->awaiting || f->transaction!=a->transaction || f->grant!=a->grant ||
    f->operation!=a->operation || f->stream!=a->stream) return;
 if(f->status || f->context!=a->context || f->sequence!=a->sequence ||
    f->expiry!=a->expiry || f->controller_ns<e->last_applied_ctl) { fail(e,ACTRYN_PROTOCOL); return; }
 if(S.state>=ACTRYN_FAULT_LATCHED) return;
 health(e); if(S.state>=ACTRYN_FAULT_LATCHED) return;
 if(f->kind==AW_APPLIED && e->now>=e->awaited_deadline) { fail(e,ACTRYN_EXPIRED); return; }
 if(f->kind==AW_BASELINE && a->kind==AW_REARM && !f->left && !f->right) { S.state=ACTRYN_READY; S.reason=0; }
 else if(f->kind==AW_STARTED && a->kind==AW_START && S.operation_state==ACTRYN_OP_STARTING)
  S.operation_state=ACTRYN_OP_RUNNING;
 else if(f->kind==AW_APPLIED && a->kind==AW_SAMPLE && S.operation_state==ACTRYN_OP_RUNNING &&
   f->left==a->left && f->right==a->right) S.sequence=f->sequence;
 else if(f->kind==AW_QUIESCED && a->kind==AW_QUIESCE && S.operation_state==ACTRYN_OP_CLOSING &&
   e->now<e->close_deadline && !f->left && !f->right) {
  S.operation_state=ACTRYN_OP_RECONCILED; e->close_deadline=0;
  if(S.state==ACTRYN_REVOKING) { S.state=ACTRYN_READY; S.instance=0; }
 } else { fail(e,ACTRYN_PROTOCOL); return; }
 e->awaiting=false; e->last_applied_ctl=S.controller_ns=f->controller_ns;
 S.left_permille=f->left; S.right_permille=f->right; S.left_encoder=f->left_encoder;
 S.right_encoder=f->right_encoder; record(e,ACTRYN_EVENT_WIRE|f->kind);
}
void a16_receive(struct a16_engine *e,const unsigned char *p,size_t n)
{
 size_t i;
 for(i=0;i<n;i++) {
  if(!p[i]) {
   if(e->parser_len && !e->discard) {
    if(e->rx_count==A16_RX) fail(e,ACTRYN_PROTOCOL);
    else if(e->now-e->parser_started>=500*MS || actryn_decode(e->parser,e->parser_len,&e->rx[e->rx_head])) {
     if(e->now>=e->sync_deadline) fail(e,ACTRYN_PROTOCOL);
    } else { e->rx_head=(e->rx_head+1)%A16_RX; e->rx_count++; }
   }
   e->parser_len=0; e->discard=false;
  } else if(!e->discard) {
   if(e->parser_len>=ACTRYN_ENCODED_MAX-1) { e->discard=true; if(e->now>=e->sync_deadline) fail(e,ACTRYN_PROTOCOL); }
   else { if(!e->parser_len) e->parser_started=e->now; e->parser[e->parser_len++]=p[i]; }
  }
 }
}
void a16_tick(struct a16_engine *e,a16_writer writer,void *opaque)
{
 struct actryn_frame f; actryn_u64 ctl; ptrdiff_t n;
 health(e);
 if(e->parser_len && !e->discard && e->now-e->parser_started>=500*MS) {
  e->discard=true; if(e->now>=e->sync_deadline) fail(e,ACTRYN_PROTOCOL);
 }
 if(e->rx_count) { f=e->rx[e->rx_tail]; e->rx_tail=(e->rx_tail+1)%A16_RX; e->rx_count--; receipt(e,&f); }
 health(e); if(S.state>=ACTRYN_FAULT_LATCHED) return;
 if(!e->tx_busy && !e->awaiting && e->quiesce) {
  frame(e,&f,AW_QUIESCE); f.grant=S.grant; f.operation=S.operation; f.stream=S.stream;
  if(transaction(e,&f.transaction) || queue(e,&f,e->close_deadline)) { fail(e,ACTRYN_PROTOCOL); return; }
  e->quiesce=false;
 } else if(!e->tx_busy && !e->awaiting && e->mailbox_valid) {
  f=e->mailbox; e->mailbox_valid=false;
  if(S.operation_state!=ACTRYN_OP_RUNNING || controller_time(e,e->now,&ctl) || ctl>=f.expiry ||
    !observation(e,e->sample.observation) || actryn_slew(S.left_permille,f.left,e->last_applied_ctl,ctl) ||
    actryn_slew(S.right_permille,f.right,e->last_applied_ctl,ctl)) { fail(e,ACTRYN_EXPIRED); return; }
  e->tx_observation=e->observation;
  if(queue(e,&f,e->sample.deadline_ns)) { fail(e,ACTRYN_PROTOCOL); return; }
 }
 if(!e->tx_busy || (e->tx_frame.kind==AW_HELLO && e->now<e->resync_after)) return;
 if((e->tx_deadline && e->now>=e->tx_deadline) || (e->tx_frame.expiry &&
   (controller_time(e,e->now,&ctl) || ctl>=e->tx_frame.expiry))) { fail(e,ACTRYN_EXPIRED); return; }
 if(e->close_deadline && e->tx_off && e->tx_frame.kind!=AW_QUIESCE &&
   e->now>=e->close_deadline-500*MS) { fail(e,ACTRYN_TRANSPORT); return; }
 if(e->tx_frame.kind==AW_SAMPLE && (e->now>=e->tx_observation.valid_until_ns ||
   e->now-e->tx_observation.acquired_earliest_ns>1000*MS)) { fail(e,ACTRYN_EXPIRED); return; }
 if(e->tx_frame.kind==AW_HELLO && !e->tx_off) e->hello_sent=e->now;
 n=writer(opaque,e->tx+e->tx_off,e->tx_len-e->tx_off);
 if(n<0 || (size_t)n>e->tx_len-e->tx_off) { fail(e,ACTRYN_TRANSPORT); return; }
 e->tx_off+=(size_t)n;
 if(e->tx_off==e->tx_len) {
  e->tx_busy=false; e->awaited=e->tx_frame; e->awaited_deadline=e->tx_deadline;
  /* A cancellation finishing an old prefix must next send the barrier. */
  if(!e->quiesce) e->awaiting=true;
 }
}
