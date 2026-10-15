// SPDX-License-Identifier: GPL-2.0-only
#include <linux/module.h>
#include <linux/serdev.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/poll.h>
#include <linux/random.h>
#include <linux/sched/signal.h>
#include <linux/cred.h>
#include <linux/capability.h>
#include <linux/user_namespace.h>
#include <linux/kref.h>
#include <linux/mutex.h>
#include <linux/spinlock.h>
#include <linux/workqueue.h>
#include <linux/ktime.h>
#include <linux/of.h>
#include <linux/pm.h>
#include <linux/actryn_authority.h>
#include "actryn_wire.h"
#include "actryn_control.h"

#define MS 1000000ULL
#define RX_COUNT 32
#define EVENT_COUNT 256
#define CTRL_OPERATION 1
#define CTRL_GRANT 2
#define CTRL_FAULT 3
#define CTRL_DETACH 4

struct actryn_endpoint {
 struct kref refs;
 struct serdev_device *serdev;
 struct miscdevice misc;
 struct mutex authority;
 spinlock_t control_lock, rx_lock, event_lock;
 struct delayed_work work;
 wait_queue_head_t event_wait;
 bool stopping, opened, handshake, tx_busy, await, mailbox_valid, quiesce_needed, grant_authorized;
 struct task_struct *owner;
 kuid_t owner_uid;
 const struct cred *owner_cred;
 u64 owner_exec_id;
 u64 runtime_generation;
 struct actryn_status s;
 struct actryn_close close;
 u64 published_grant, published_operation, published_stream, close_serial;
 u8 published_nonce[16];
 u64 grant_deadline, operation_deadline, health_deadline, close_deadline, receipt_deadline;
 u64 tx_host_deadline, awaited_host_deadline, parser_started, resync_after;
 u64 next_operation, next_transaction, map_host, map_ctl, hello_sent;
 u64 last_applied_host, last_applied_ctl, observation_sequence;
 struct actryn_request observation, allocation, sample, tx_observation;
 struct actryn_frame tx_frame, awaited, mailbox;
 u8 tx[ACTRYN_ENCODED_MAX+1];
 size_t tx_len, tx_off;
 u8 parser[ACTRYN_ENCODED_MAX];
 size_t parser_len;
 bool parser_discard;
 u64 parser_sync_deadline;
 struct actryn_frame rx[RX_COUNT];
 unsigned int rx_head, rx_tail, rx_count;
 struct actryn_event events[EVENT_COUNT];
 unsigned int event_head, event_tail, event_count;
 u64 event_sequence;
};
struct actryn_file { struct actryn_endpoint *ep; u32 role; u64 runtime_generation; };
static void endpoint_work(struct work_struct *work);

static void endpoint_free(struct kref *ref)
{
 struct actryn_endpoint *e=container_of(ref,struct actryn_endpoint,refs);
 if(e->owner) put_task_struct(e->owner);
 if(e->owner_cred) put_cred(e->owner_cred);
 kfree(e);
}
static u64 now_ns(void) { return ktime_get_boottime_ns(); }
static bool is_zero(const void *p,size_t n) { return !memchr_inv(p,0,n); }
static bool admin(void) { return ns_capable(&init_user_ns,CAP_SYS_ADMIN); }
static bool owner_alive(struct actryn_endpoint *e)
{
 bool alive;
 if(!e->owner) return false;
 rcu_read_lock();
 alive=pid_alive(e->owner) && !(READ_ONCE(e->owner->flags)&PF_EXITING) &&
       !READ_ONCE(e->owner->exit_state) && __task_cred(e->owner)==e->owner_cred &&
       READ_ONCE(e->owner->self_exec_id)==e->owner_exec_id;
 rcu_read_unlock();
 return alive;
}
static bool is_owner(struct actryn_endpoint *e)
{
 struct task_struct *task=current->group_leader;
 /* The urgent path has not taken authority yet. Only dereference current's
  * retained leader, never an owner pointer that registration can replace. */
 return READ_ONCE(e->owner)==task && current_cred()==READ_ONCE(e->owner_cred) &&
        pid_alive(task) && !(READ_ONCE(task->flags)&PF_EXITING) &&
        !READ_ONCE(task->exit_state) &&
        READ_ONCE(task->self_exec_id)==READ_ONCE(e->owner_exec_id);
}
static void kick(struct actryn_endpoint *e)
{
 unsigned long flags;
 spin_lock_irqsave(&e->control_lock,flags);
 if(!e->stopping) mod_delayed_work(system_wq,&e->work,0);
 spin_unlock_irqrestore(&e->control_lock,flags);
}
static void publish_identity(struct actryn_endpoint *e)
{
 unsigned long flags;
 spin_lock_irqsave(&e->control_lock,flags);
 e->published_grant=e->s.grant; e->published_operation=e->s.operation;
 e->published_stream=e->s.stream; memcpy(e->published_nonce,e->s.runtime_nonce,16);
 spin_unlock_irqrestore(&e->control_lock,flags);
}
static int request_close(struct actryn_endpoint *e,u32 rank,u32 reason,u64 grant,u64 op)
{
 unsigned long flags; int ret=0;
 spin_lock_irqsave(&e->control_lock,flags);
 ret=actryn_merge_close(&e->close,rank,reason,grant,op,e->published_grant,
                       e->published_operation,&e->close_serial);
 if(ret) ret=ret==-1?-ESTALE:-EOVERFLOW;
 if(!ret && !e->stopping) mod_delayed_work(system_wq,&e->work,0);
 spin_unlock_irqrestore(&e->control_lock,flags);
 return ret;
}
static void event(struct actryn_endpoint *e,u32 kind)
{
 unsigned long flags; struct actryn_event *v;
 e->s.now_ns=now_ns();
 e->s.flags=(e->handshake?ACTRYN_STATUS_HANDSHAKEN:0)|
  (e->tx_busy && e->tx_off?ACTRYN_STATUS_TX_STARTED:0)|(e->await?ACTRYN_STATUS_AWAITING:0)|
  (e->grant_authorized?ACTRYN_STATUS_GRANT_AUTHORIZED:0);
 spin_lock_irqsave(&e->event_lock,flags);
 if(e->event_count==EVENT_COUNT || e->event_sequence==U64_MAX) {
  if(e->s.events_lost<U32_MAX) e->s.events_lost++;
  spin_unlock_irqrestore(&e->event_lock,flags);
  request_close(e,CTRL_FAULT,ACTRYN_EVIDENCE_LOST,0,0);
  return;
 }
 v=&e->events[e->event_head];
 *v=(struct actryn_event){ .sequence=++e->event_sequence,
  .captured_ns=e->s.now_ns,.kind=kind,.status=e->s };
 e->event_head=(e->event_head+1)%EVENT_COUNT; e->event_count++;
 spin_unlock_irqrestore(&e->event_lock,flags);
 wake_up_interruptible(&e->event_wait);
}
static int next_transaction(struct actryn_endpoint *e,u64 *out)
{
 if(e->next_transaction==U64_MAX) return -EOVERFLOW;
 *out=++e->next_transaction; return 0;
}
static void frame_base(struct actryn_endpoint *e,struct actryn_frame *f,u16 kind)
{
 memset(f,0,sizeof(*f)); f->kind=kind;
 memcpy(f->device,e->s.device_identity,16); memcpy(f->nonce,e->s.runtime_nonce,16);
 f->boot=e->s.controller_boot; f->session=e->s.controller_session; f->context=1;
}
static bool same_epoch(struct actryn_endpoint *e,const struct actryn_frame *f)
{
 return !memcmp(f->device,e->s.device_identity,16) &&
  !memcmp(f->nonce,e->s.runtime_nonce,16) && f->boot==e->s.controller_boot &&
  f->session==e->s.controller_session;
}
static bool same_operation(const struct actryn_frame *a,const struct actryn_frame *b)
{ return a->grant==b->grant && a->operation==b->operation && a->stream==b->stream; }
static int controller_time(struct actryn_endpoint *e,u64 host,u64 *out)
{
 u64 delta;
 if(!e->handshake || host<e->map_host || now_ns()-e->map_host>=60000*MS) return -ESTALE;
 delta=host-e->map_host;
 if(delta>120000*MS || e->map_ctl>U64_MAX-delta) return -ERANGE;
 *out=e->map_ctl+delta-delta/10000; return 0;
}
static int queue_frame(struct actryn_endpoint *e,const struct actryn_frame *f)
{
 lockdep_assert_held(&e->authority);
 if(e->tx_busy || e->await) return -EBUSY;
 e->tx_frame=*f; e->tx_len=actryn_encode(f,e->tx); e->tx_off=0;
 if(f->kind==AW_HELLO) {
  /* Retire an abandoned COBS prefix before a fresh session handshake. */
  memmove(e->tx+1,e->tx,e->tx_len); e->tx[0]=0; e->tx_len++;
 }
 e->tx_host_deadline=f->kind==AW_SAMPLE?e->sample.deadline_ns:
  f->kind==AW_START?e->operation_deadline:f->kind==AW_QUIESCE?e->close_deadline:0;
 e->tx_busy=true; e->receipt_deadline=max(now_ns(),e->resync_after)+1000*MS;
 e->s.transaction=f->transaction; return 0;
}
static void apply_close(struct actryn_endpoint *e)
{
 struct actryn_close c; unsigned long flags; u64 now=now_ns();
 lockdep_assert_held(&e->authority);
 spin_lock_irqsave(&e->control_lock,flags); c=e->close; spin_unlock_irqrestore(&e->control_lock,flags);
 if(!c.rank) return;
 if(e->s.state==ACTRYN_DETACHED ||
    (e->s.state==ACTRYN_FAULT_LATCHED && c.rank<CTRL_FAULT)) goto clear;
 if(e->s.state==ACTRYN_INHIBITED && c.rank==CTRL_GRANT) {
  /* Closure cannot substitute for an acknowledged baseline/rearm. */
  e->grant_authorized=false; e->s.instance=0; goto clear;
 }
 if(c.rank==CTRL_OPERATION && c.operation==e->s.operation &&
    (e->s.operation_state==ACTRYN_OP_CLOSING || e->s.operation_state==ACTRYN_OP_RECONCILED))
  goto clear;
 if(c.rank>=CTRL_FAULT || (c.grant==e->s.grant &&
    (c.rank!=CTRL_OPERATION || c.operation==e->s.operation))) {
  if(c.rank>=CTRL_FAULT) { e->s.state=c.rank==CTRL_DETACH?ACTRYN_DETACHED:ACTRYN_FAULT_LATCHED;
   e->s.operation_state=e->s.operation?ACTRYN_OP_UNKNOWN:ACTRYN_OP_NONE; e->s.reason=c.reason;
   e->handshake=false; e->grant_authorized=false;
  } else if(c.rank==CTRL_GRANT) {
   e->s.state=ACTRYN_REVOKING; e->s.reason=c.reason; e->grant_authorized=false; e->s.instance=0;
  }
  if(c.rank<CTRL_FAULT && e->s.operation && e->s.operation_state!=ACTRYN_OP_RECONCILED) {
   if(e->s.operation_state!=ACTRYN_OP_CLOSING) e->s.reason=c.reason;
   e->s.operation_state=ACTRYN_OP_CLOSING;
  }
  e->mailbox_valid=false;
  if(e->tx_busy && !e->tx_off) e->tx_busy=false;
  e->await=false;
  if(!e->close_deadline) e->close_deadline=now+1000*MS;
  e->quiesce_needed=e->s.operation && e->s.operation_state!=ACTRYN_OP_RECONCILED && c.rank<CTRL_FAULT;
  if(c.rank==CTRL_GRANT && !e->quiesce_needed) {
   e->s.state=ACTRYN_READY; e->close_deadline=0;
  }
  if(c.rank>=CTRL_FAULT) {
   spin_lock_irqsave(&e->rx_lock,flags); e->parser_sync_deadline=0;
   spin_unlock_irqrestore(&e->rx_lock,flags);
   /* The final missing byte can be the delimiter: never complete an old
    * effect-bearing frame while its immutable expiry is still valid. */
   if(e->tx_busy && e->tx_off && e->tx_frame.expiry)
    e->resync_after=max(e->resync_after,e->tx_host_deadline);
   e->tx_busy=false;
  }
  event(e,ACTRYN_EVENT_CLOSURE|c.reason);
 }
clear:
 spin_lock_irqsave(&e->control_lock,flags);
 actryn_clear_close(&e->close,c.revision);
 spin_unlock_irqrestore(&e->control_lock,flags);
}
static void fault(struct actryn_endpoint *e,u32 reason)
{ request_close(e,CTRL_FAULT,reason,0,0); apply_close(e); }

static int handshake(struct actryn_endpoint *e)
{
 struct actryn_frame f={.kind=AW_HELLO}; unsigned long flags;
 if(e->tx_busy) return -EBUSY;
 e->await=false; e->quiesce_needed=false; e->mailbox_valid=false;
 e->s.state=ACTRYN_INHIBITED; e->s.operation_state=ACTRYN_OP_NONE;
 e->s.grant=0; e->s.instance=0; e->s.operation=0; e->s.stream=0;
 e->s.controller_boot=0; e->s.controller_session=0; e->s.controller_ns=0;
 e->s.observation=0; e->observation_sequence=0;
 e->last_applied_ctl=0; e->last_applied_host=0;
 memset(&e->observation,0,sizeof(e->observation));
 e->close_deadline=0; e->handshake=false; e->grant_authorized=false;
 if(get_random_bytes_wait(e->s.runtime_nonce,16)) return -ERESTARTSYS;
 /* A new UART attachment may start in a retained frame. Only this explicit
  * no-authority handshake may discard malformed prefixes. The existing
  * absolute HELLO timeout and RX queue capacity remain fail-closed. */
 spin_lock_irqsave(&e->rx_lock,flags);
 e->parser_sync_deadline=max(now_ns(),e->resync_after)+1000*MS;
 spin_unlock_irqrestore(&e->rx_lock,flags);
 memcpy(f.nonce,e->s.runtime_nonce,16);
 e->next_transaction=0; next_transaction(e,&f.transaction);
 publish_identity(e); return queue_frame(e,&f);
}

static void receive_frame(struct actryn_endpoint *e,const struct actryn_frame *f)
{
 u64 now=now_ns(); unsigned long flags; const struct actryn_frame *a=&e->awaited;
 lockdep_assert_held(&e->authority);
 if(f->kind==AW_HELLO_ACK && e->await && a->kind==AW_HELLO &&
    f->transaction==a->transaction && !memcmp(f->nonce,e->s.runtime_nonce,16)) {
  if(f->status!=1 || !f->boot || !f->session || is_zero(f->device,16) ||
     f->grant || f->operation || f->stream || f->sequence || f->expiry ||
     f->left || f->right || f->context || now-e->hello_sent>10*MS) {
   fault(e,ACTRYN_PROTOCOL); return;
  }
  memcpy(e->s.device_identity,f->device,16);
  e->s.controller_boot=f->boot; e->s.controller_session=f->session;
  spin_lock_irqsave(&e->rx_lock,flags); e->parser_sync_deadline=0;
  spin_unlock_irqrestore(&e->rx_lock,flags);
  e->map_host=now; e->map_ctl=f->controller_ns; e->handshake=true;
  e->await=false; e->s.controller_ns=f->controller_ns; event(e,ACTRYN_EVENT_WIRE|AW_HELLO_ACK); return;
 }
 /* A newer durable epoch from this endpoint is positive reset evidence.
  * Older epochs and foreign nonces cannot renew or reconcile current work. */
 if(e->handshake && !memcmp(f->device,e->s.device_identity,16) &&
    (f->boot>e->s.controller_boot ||
     (f->boot==e->s.controller_boot && f->session>e->s.controller_session))) {
  fault(e,ACTRYN_TRANSPORT); return;
 }
 if(!same_epoch(e,f)) return;
 if(f->kind==AW_FAULT) { fault(e,ACTRYN_TRANSPORT); return; }
 if(f->kind==AW_OBSERVATION) {
  if(f->context!=1 || f->transaction || f->expiry || !f->sequence ||
     f->sequence<=e->observation_sequence || f->controller_ns<e->s.controller_ns) return;
  e->observation_sequence=f->sequence; e->s.left_encoder=f->left_encoder;
  e->s.right_encoder=f->right_encoder; e->s.controller_ns=f->controller_ns;
  event(e,ACTRYN_EVENT_WIRE|AW_OBSERVATION); return;
 }
 if(!e->await || f->transaction!=a->transaction || !same_operation(a,f)) return;
 if(f->status || f->context!=a->context || f->sequence!=a->sequence ||
    f->expiry!=a->expiry || f->controller_ns<e->last_applied_ctl) {
  fault(e,ACTRYN_PROTOCOL); return;
 }
 if(e->s.state==ACTRYN_FAULT_LATCHED || e->s.state==ACTRYN_DETACHED) return;
 /* Receipt capture time cannot substitute for eligibility at this transition. */
 now=now_ns();
 if((e->s.state==ACTRYN_ACTIVE || e->s.state==ACTRYN_REVOKING) &&
    (now>=e->grant_deadline || now>=e->health_deadline ||
     (e->s.operation_state!=ACTRYN_OP_NONE && e->s.operation_state!=ACTRYN_OP_RECONCILED &&
      now>=e->operation_deadline))) { fault(e,ACTRYN_EXPIRED); return; }
 if(f->kind==AW_APPLIED && now>=e->awaited_host_deadline) {
  fault(e,ACTRYN_EXPIRED); return;
 }
 if(f->kind==AW_BASELINE && a->kind==AW_REARM && !f->left && !f->right) {
  e->s.state=ACTRYN_READY; e->s.reason=ACTRYN_REASON_NONE;
 } else if(f->kind==AW_STARTED && a->kind==AW_START &&
           e->s.operation_state==ACTRYN_OP_STARTING) {
  e->s.operation_state=ACTRYN_OP_RUNNING;
 } else if(f->kind==AW_APPLIED && a->kind==AW_SAMPLE &&
           e->s.operation_state==ACTRYN_OP_RUNNING && f->left==a->left && f->right==a->right) {
  e->s.sequence=f->sequence;
 } else if(f->kind==AW_QUIESCED && a->kind==AW_QUIESCE &&
           e->s.operation_state==ACTRYN_OP_CLOSING && now<e->close_deadline &&
           !f->left && !f->right) {
  e->s.operation_state=ACTRYN_OP_RECONCILED; e->close_deadline=0;
  if(e->s.state==ACTRYN_REVOKING) { e->s.state=ACTRYN_READY; e->s.instance=0; }
 } else { fault(e,ACTRYN_PROTOCOL); return; }
 e->await=false; e->last_applied_ctl=f->controller_ns; e->last_applied_host=now;
 e->s.left_permille=f->left; e->s.right_permille=f->right;
 e->s.left_encoder=f->left_encoder; e->s.right_encoder=f->right_encoder;
 e->s.controller_ns=f->controller_ns; event(e,ACTRYN_EVENT_WIRE|f->kind);
}
static void check_health(struct actryn_endpoint *e)
{
 u64 now=now_ns();
 if(e->grant_authorized && (!owner_alive(e) || now>=e->grant_deadline)) {
  fault(e,!owner_alive(e)?ACTRYN_OWNER_LOST:ACTRYN_EXPIRED); return;
 }
 if((e->await || e->tx_busy) && now>=e->receipt_deadline &&
    e->s.state!=ACTRYN_FAULT_LATCHED && e->s.state!=ACTRYN_DETACHED) {
  fault(e,ACTRYN_TRANSPORT); return;
 }
 if(e->s.state!=ACTRYN_ACTIVE && e->s.state!=ACTRYN_REVOKING) return;
 if(!owner_alive(e)) fault(e,ACTRYN_OWNER_LOST);
 else if(now>=e->grant_deadline || (e->s.operation_state!=ACTRYN_OP_NONE &&
          e->s.operation_state!=ACTRYN_OP_RECONCILED && now>=e->operation_deadline))
  fault(e,ACTRYN_EXPIRED);
 else if(now>=e->health_deadline) fault(e,ACTRYN_EVIDENCE_LOST);
 else if(now-e->map_host>=60000*MS) fault(e,ACTRYN_EXPIRED);
 else if(e->close_deadline && now>=e->close_deadline) fault(e,ACTRYN_TRANSPORT);
}
static bool close_pending(struct actryn_endpoint *e)
{
 unsigned long flags; bool pending;
 spin_lock_irqsave(&e->control_lock,flags); pending=e->close.rank;
 spin_unlock_irqrestore(&e->control_lock,flags); return pending;
}
static void transmit_at(struct actryn_endpoint *e,u64 now)
{
 struct actryn_frame f; int n; u64 ctl;
 lockdep_assert_held(&e->authority);
 if(e->s.state==ACTRYN_DETACHED || e->s.state==ACTRYN_FAULT_LATCHED) return;
 if(!e->tx_busy && !e->await && e->quiesce_needed) {
  frame_base(e,&f,AW_QUIESCE); f.grant=e->s.grant; f.operation=e->s.operation;
  f.stream=e->s.stream;
  if(next_transaction(e,&f.transaction)) { fault(e,ACTRYN_PROTOCOL); return; }
  queue_frame(e,&f); e->quiesce_needed=false;
 } else if(!e->tx_busy && !e->await && e->mailbox_valid) {
  f=e->mailbox; e->mailbox_valid=false;
  if(e->s.operation_state!=ACTRYN_OP_RUNNING || controller_time(e,now,&ctl) ||
     ctl>=f.expiry || e->sample.observation!=e->observation.observation ||
     now>=e->observation.valid_until_ns ||
     now-e->observation.acquired_earliest_ns>1000*MS ||
     actryn_slew(e->s.left_permille,f.left,e->last_applied_ctl,ctl) ||
     actryn_slew(e->s.right_permille,f.right,e->last_applied_ctl,ctl)) {
   fault(e,ACTRYN_EXPIRED); return;
  }
  e->tx_observation=e->observation; queue_frame(e,&f);
 }
 if(!e->tx_busy || close_pending(e)) return;
 if(e->tx_frame.kind==AW_HELLO && now<e->resync_after) return;
 if(e->tx_host_deadline && now>=e->tx_host_deadline) {
  fault(e,ACTRYN_EXPIRED); return;
 }
 if(e->close_deadline && e->tx_off && e->tx_frame.kind!=AW_QUIESCE &&
    now>=e->close_deadline-500*MS) { fault(e,ACTRYN_TRANSPORT); return; }
 if(e->tx_frame.expiry && (controller_time(e,now,&ctl) || ctl>=e->tx_frame.expiry)) {
  fault(e,ACTRYN_EXPIRED); return;
 }
 if(e->tx_frame.kind==AW_SAMPLE && !e->close_deadline &&
    (e->tx_observation.observation!=e->observation.observation ||
     now>=e->tx_observation.valid_until_ns ||
     now-e->tx_observation.acquired_earliest_ns>1000*MS)) {
  fault(e,ACTRYN_EXPIRED); return;
 }
 /* write_wakeup can run inline while the UART lock is held. */
 if(e->tx_frame.kind==AW_HELLO && !e->tx_off) e->hello_sent=now;
 n=serdev_device_write_buf(e->serdev,e->tx+e->tx_off,e->tx_len-e->tx_off);
 if(n<0 || n>e->tx_len-e->tx_off) { fault(e,ACTRYN_TRANSPORT); return; }
 e->tx_off+=n;
 if(e->tx_off==e->tx_len) {
  e->tx_busy=false;
  if(!e->quiesce_needed) {
   e->await=true; e->awaited=e->tx_frame; e->awaited_host_deadline=e->tx_host_deadline;
  }
 }
}
static void transmit(struct actryn_endpoint *e)
{ transmit_at(e,now_ns()); }
static void endpoint_work(struct work_struct *work)
{
 struct actryn_endpoint *e=container_of(to_delayed_work(work),struct actryn_endpoint,work);
 struct actryn_frame f; unsigned long flags; bool have=false,parser_timeout=false;
 mutex_lock(&e->authority);
 if(e->s.state==ACTRYN_DETACHED) { mutex_unlock(&e->authority); return; }
 apply_close(e); check_health(e);
 spin_lock_irqsave(&e->rx_lock,flags);
 if(e->parser_len && !e->parser_discard && now_ns()-e->parser_started>=500*MS) {
  e->parser_discard=true; parser_timeout=now_ns()>=e->parser_sync_deadline;
 }
 if(e->rx_count) { f=e->rx[e->rx_tail]; e->rx_tail=(e->rx_tail+1)%RX_COUNT; e->rx_count--; have=true; }
 spin_unlock_irqrestore(&e->rx_lock,flags);
 if(parser_timeout) fault(e,ACTRYN_PROTOCOL);
 if(have) receive_frame(e,&f);
 apply_close(e); check_health(e); transmit(e);
 mutex_unlock(&e->authority);
 spin_lock_irqsave(&e->control_lock,flags);
 if(!e->stopping) mod_delayed_work(system_wq,&e->work,msecs_to_jiffies(have?0:10));
 spin_unlock_irqrestore(&e->control_lock,flags);
}
static size_t receive_buf(struct serdev_device *serdev,const u8 *data,size_t n)
{
 struct actryn_endpoint *e=serdev_device_get_drvdata(serdev);
 unsigned long flags; size_t i; bool bad=false;
 spin_lock_irqsave(&e->rx_lock,flags);
 for(i=0;i<n;i++) {
  if(!data[i]) {
   if(e->parser_len && !e->parser_discard) {
    if(e->rx_count==RX_COUNT) bad=true;
    else if(now_ns()-e->parser_started>=500*MS ||
       actryn_decode(e->parser,e->parser_len,&e->rx[e->rx_head])) {
     if(now_ns()>=e->parser_sync_deadline) bad=true;
    }
    else { e->rx_head=(e->rx_head+1)%RX_COUNT; e->rx_count++; }
   }
   e->parser_len=0; e->parser_discard=false;
  } else if(!e->parser_discard) {
   if(e->parser_len>=ACTRYN_ENCODED_MAX-1) {
    e->parser_discard=true; if(now_ns()>=e->parser_sync_deadline) bad=true;
   }
   else { if(!e->parser_len) e->parser_started=now_ns(); e->parser[e->parser_len++]=data[i]; }
  }
 }
 spin_unlock_irqrestore(&e->rx_lock,flags);
 if(bad) request_close(e,CTRL_FAULT,ACTRYN_PROTOCOL,0,0); else kick(e);
 return n;
}
static void write_wakeup(struct serdev_device *serdev)
{ kick(serdev_device_get_drvdata(serdev)); }
static const struct serdev_device_ops serial_ops={ .receive_buf=receive_buf,.write_wakeup=write_wakeup };

static bool request_epoch(struct actryn_endpoint *e,const struct actryn_request *r)
{ return !memcmp(e->s.runtime_nonce,r->runtime_nonce,16); }
static bool request_operation(struct actryn_endpoint *e,const struct actryn_request *r)
{ return request_epoch(e,r) && r->grant==e->s.grant && r->operation==e->s.operation &&
   r->stream==e->s.stream && r->operation; }
static int canonical_request(const struct actryn_request *r)
{
 struct actryn_request z=*r;
 if(r->version!=1 || r->flags || r->reserved0 || !is_zero(r->reserved,sizeof(r->reserved))) return -EINVAL;
 z.version=0; z.opcode=0;
 switch(r->opcode) {
 case ACTRYN_BIND: z.role=0; break;
 case ACTRYN_HANDSHAKE: case ACTRYN_REARM: case ACTRYN_RECOVER: break;
 case ACTRYN_GRANT: z.instance=0; z.deadline_ns=0; memset(z.digest,0,32); break;
 case ACTRYN_ACTIVATE: z.grant=0; z.instance=0; memset(z.runtime_nonce,0,16); break;
 case ACTRYN_OBSERVE:
  memset(z.runtime_nonce,0,16); z.observation=0; z.acquired_earliest_ns=0;
  z.acquired_latest_ns=0; z.valid_until_ns=0; z.context_revision=0; break;
 case ACTRYN_ALLOCATE: case ACTRYN_START:
  memset(z.runtime_nonce,0,16); z.grant=0; z.instance=0; z.operation=0; z.stream=0;
  z.deadline_ns=0; z.observation=0; z.context_revision=0; memset(z.digest,0,32); break;
 case ACTRYN_SAMPLE:
  memset(z.runtime_nonce,0,16); z.grant=0; z.operation=0; z.stream=0; z.sequence=0;
  z.deadline_ns=0; z.observation=0; z.context_revision=0;
  z.left_permille=0; z.right_permille=0; memset(z.digest,0,32); break;
 case ACTRYN_FINISH: case ACTRYN_CANCEL:
  memset(z.runtime_nonce,0,16); z.grant=0; z.operation=0; z.stream=0; break;
 case ACTRYN_REVOKE: memset(z.runtime_nonce,0,16); z.grant=0; break;
 case ACTRYN_HEALTH: memset(z.runtime_nonce,0,16); z.deadline_ns=0; break;
 default: return -ENOTTY;
 }
 return is_zero(&z,sizeof(z))?0:-EINVAL;
}
static bool observation_valid(struct actryn_endpoint *e,u64 id,u64 now)
{
 return id && id==e->observation.observation && e->observation.context_revision==1 &&
  now>=e->observation.acquired_latest_ns && now<e->observation.valid_until_ns &&
  now-e->observation.acquired_earliest_ns<=1000*MS;
}
static int do_request(struct actryn_file *file,struct actryn_request *r)
{
 struct actryn_endpoint *e=file->ep; struct actryn_frame f;
 u64 now=now_ns(), expiry; int ret;
 if(r->opcode==ACTRYN_BIND) {
  if(file->role || !admin() || r->role<ACTRYN_ADMIN || r->role>ACTRYN_EVENTS) return -EPERM;
  if(r->role==ACTRYN_RUNTIME) {
   if(e->runtime_generation==U64_MAX) return -EOVERFLOW;
   if(e->owner && owner_alive(e) && e->owner!=current->group_leader) return -EBUSY;
   if(e->s.state!=ACTRYN_INHIBITED && e->s.state!=ACTRYN_FAULT_LATCHED) return -EBUSY;
   if(e->owner) put_task_struct(e->owner);
   if(e->owner_cred) put_cred(e->owner_cred);
   e->owner=current->group_leader; get_task_struct(e->owner); e->owner_uid=current_euid();
   e->owner_cred=get_current_cred();
   e->owner_exec_id=READ_ONCE(e->owner->self_exec_id);
   e->runtime_generation++;
  } else if(r->role==ACTRYN_ACQUISITION && !is_owner(e)) return -EPERM;
  file->role=r->role; file->runtime_generation=e->runtime_generation; return 0;
 }
 if(!file->role || file->role==ACTRYN_EVENTS) return -EPERM;
 if(file->role==ACTRYN_ADMIN) { if(!admin()) return -EPERM; }
 else if(!is_owner(e) || file->runtime_generation!=e->runtime_generation) return -EPERM;
 switch(r->opcode) {
 case ACTRYN_HANDSHAKE: case ACTRYN_RECOVER:
  if(file->role!=ACTRYN_ADMIN || (e->s.state!=ACTRYN_INHIBITED && e->s.state!=ACTRYN_FAULT_LATCHED)) return -EPERM;
  ret=handshake(e); break;
 case ACTRYN_REARM:
  if(file->role!=ACTRYN_ADMIN || e->s.state!=ACTRYN_INHIBITED || !e->handshake) return -EPERM;
  frame_base(e,&f,AW_REARM); ret=next_transaction(e,&f.transaction);
  if(!ret) ret=queue_frame(e,&f);
  break;
 case ACTRYN_GRANT:
  if(file->role!=ACTRYN_ADMIN || e->s.state!=ACTRYN_READY || !r->instance ||
     !owner_alive(e) || actryn_window(now,r->deadline_ns,60000*MS)) return -EPERM;
  if(e->s.grant==U64_MAX) return -EOVERFLOW;
  e->s.grant++; e->s.instance=r->instance; e->grant_deadline=r->deadline_ns;
  e->grant_authorized=true;
  e->s.deadline_ns=r->deadline_ns; r->grant=e->s.grant;
  memcpy(r->runtime_nonce,e->s.runtime_nonce,16); publish_identity(e); ret=0; break;
 case ACTRYN_ACTIVATE:
  if(file->role!=ACTRYN_RUNTIME || !request_epoch(e,r) || r->grant!=e->s.grant ||
     r->instance!=e->s.instance || !r->instance || !e->grant_authorized || e->s.state!=ACTRYN_READY ||
     now>=e->grant_deadline || now>=e->health_deadline) return -EPERM;
  e->s.state=ACTRYN_ACTIVE; e->s.operation_state=ACTRYN_OP_NONE;
  e->s.operation=0; e->s.stream=0; e->s.reason=0; publish_identity(e); ret=0; break;
 case ACTRYN_HEALTH:
  if(file->role!=ACTRYN_RUNTIME || !request_epoch(e,r) ||
     actryn_window(now,r->deadline_ns,2000*MS)) return -EINVAL;
  e->health_deadline=r->deadline_ns; ret=0; break;
 case ACTRYN_OBSERVE:
  if(file->role!=ACTRYN_ACQUISITION || !request_epoch(e,r) || !r->observation ||
     r->observation<=e->observation.observation || r->context_revision!=1 ||
     r->acquired_earliest_ns>r->acquired_latest_ns || r->acquired_latest_ns>now ||
     now-r->acquired_earliest_ns>1000*MS ||
     actryn_window(now,r->valid_until_ns,1000*MS)) return -EINVAL;
  e->observation=*r; e->s.observation=r->observation; e->s.context_revision=1; ret=0; break;
 case ACTRYN_ALLOCATE:
  if(file->role!=ACTRYN_RUNTIME || !request_epoch(e,r) || r->grant!=e->s.grant ||
     r->instance!=e->s.instance || e->s.state!=ACTRYN_ACTIVE || r->operation || r->stream ||
     (e->s.operation_state!=ACTRYN_OP_NONE && e->s.operation_state!=ACTRYN_OP_RECONCILED) ||
     r->context_revision!=1 || !observation_valid(e,r->observation,now) ||
     actryn_window(now,r->deadline_ns,10000*MS) || r->deadline_ns>e->grant_deadline) return -EINVAL;
  if(e->next_operation==U64_MAX) return -EOVERFLOW;
  r->operation=++e->next_operation; r->stream=r->operation;
  e->s.operation=r->operation; e->s.stream=r->stream; e->s.sequence=0;
  e->s.operation_state=ACTRYN_OP_ALLOCATED; e->s.reason=0;
  e->operation_deadline=r->deadline_ns; e->allocation=*r;
  memset(&e->sample,0,sizeof(e->sample)); publish_identity(e); ret=0; break;
 case ACTRYN_START:
  if(file->role!=ACTRYN_RUNTIME || !request_operation(e,r) || e->s.state!=ACTRYN_ACTIVE ||
     e->s.operation_state!=ACTRYN_OP_ALLOCATED || r->instance!=e->allocation.instance ||
     r->deadline_ns!=e->allocation.deadline_ns || r->observation!=e->allocation.observation ||
     r->context_revision!=1 || memcmp(r->digest,e->allocation.digest,32) ||
     !observation_valid(e,r->observation,now) || now>=r->deadline_ns) return -ESTALE;
  frame_base(e,&f,AW_START); f.grant=e->s.grant; f.operation=e->s.operation; f.stream=e->s.stream;
  ret=controller_time(e,r->deadline_ns,&f.expiry); if(ret) break;
  ret=next_transaction(e,&f.transaction); if(ret) break;
  ret=queue_frame(e,&f); if(!ret) e->s.operation_state=ACTRYN_OP_STARTING; break;
 case ACTRYN_SAMPLE:
  if(file->role!=ACTRYN_RUNTIME || !request_operation(e,r) || e->s.state!=ACTRYN_ACTIVE ||
     e->s.operation_state!=ACTRYN_OP_RUNNING || !r->sequence || r->context_revision!=1 ||
     !observation_valid(e,r->observation,now) || actryn_window(now,r->deadline_ns,500*MS) ||
     r->deadline_ns>e->operation_deadline || r->deadline_ns>e->grant_deadline ||
     r->deadline_ns>e->health_deadline || r->deadline_ns>e->observation.valid_until_ns ||
     r->deadline_ns-e->observation.acquired_earliest_ns>1000*MS ||
     r->left_permille < -200 || r->left_permille>200 ||
     r->right_permille < -200 || r->right_permille>200) return -EINVAL;
  if(r->sequence==e->sample.sequence) return memcmp(r,&e->sample,sizeof(*r))?-EEXIST:0;
  if(r->sequence<e->sample.sequence) return -ESTALE;
  ret=controller_time(e,r->deadline_ns,&expiry); if(ret) break;
  frame_base(e,&f,AW_SAMPLE); f.grant=e->s.grant; f.operation=e->s.operation; f.stream=e->s.stream;
  f.sequence=r->sequence; f.expiry=expiry; f.left=r->left_permille; f.right=r->right_permille;
  ret=next_transaction(e,&f.transaction); if(ret) break;
  e->sample=*r; e->mailbox=f; e->mailbox_valid=true; ret=0; break;
 case ACTRYN_FINISH: case ACTRYN_CANCEL:
  if((file->role!=ACTRYN_RUNTIME && file->role!=ACTRYN_ADMIN) || !request_operation(e,r)) return -ESTALE;
  ret=request_close(e,CTRL_OPERATION,r->opcode==ACTRYN_FINISH?ACTRYN_SKILL_FINISHED:ACTRYN_CANCELLED,r->grant,r->operation);
  apply_close(e); break;
 case ACTRYN_REVOKE:
  if(file->role!=ACTRYN_ADMIN || !r->grant || !request_epoch(e,r) || r->grant!=e->s.grant) return -ESTALE;
  ret=request_close(e,CTRL_GRANT,ACTRYN_GRANT_REVOKED,r->grant,0); apply_close(e);
  if(e->s.state==ACTRYN_REVOKING &&
     (!e->s.operation || e->s.operation_state==ACTRYN_OP_RECONCILED)) e->s.state=ACTRYN_READY;
  break;
 default: return -ENOTTY;
 }
 if(!ret) { event(e,ACTRYN_EVENT_REQUEST|r->opcode); kick(e); }
 return ret;
}

static int urgent_request(struct actryn_file *f,const struct actryn_request *r)
{
 struct actryn_endpoint *e=f->ep; unsigned long flags; u32 rank,reason; int ret=0;
 if(r->opcode!=ACTRYN_CANCEL && r->opcode!=ACTRYN_FINISH && r->opcode!=ACTRYN_REVOKE) return 0;
 if(f->role==ACTRYN_ADMIN) { if(!admin()) return -EPERM; }
 else if(f->role!=ACTRYN_RUNTIME || !is_owner(e) ||
         f->runtime_generation!=READ_ONCE(e->runtime_generation) || r->opcode==ACTRYN_REVOKE) return -EPERM;
 if(r->opcode==ACTRYN_REVOKE && !r->grant) return -ESTALE;
 rank=r->opcode==ACTRYN_REVOKE?CTRL_GRANT:CTRL_OPERATION;
 reason=r->opcode==ACTRYN_REVOKE?ACTRYN_GRANT_REVOKED:
        r->opcode==ACTRYN_FINISH?ACTRYN_SKILL_FINISHED:ACTRYN_CANCELLED;
 spin_lock_irqsave(&e->control_lock,flags);
 if(memcmp(r->runtime_nonce,e->published_nonce,16) || r->grant!=e->published_grant ||
    (rank==CTRL_OPERATION && (!r->operation || r->operation!=e->published_operation || r->stream!=e->published_stream))) ret=-ESTALE;
 else if(actryn_merge_close(&e->close,rank,reason,r->grant,r->operation,
                           e->published_grant,e->published_operation,&e->close_serial)) ret=-EOVERFLOW;
 if(!ret && !e->stopping) mod_delayed_work(system_wq,&e->work,0);
 spin_unlock_irqrestore(&e->control_lock,flags); return ret;
}
static long authority_ioctl(struct file *file,unsigned int cmd,unsigned long arg)
{
 struct actryn_file *f=file->private_data; struct actryn_endpoint *e=f->ep;
 struct actryn_request r; struct actryn_status s; int ret;
 if(cmd==ACTRYN_IOCTL_STATUS) {
  if(!f->role) return -EPERM;
  mutex_lock(&e->authority); s=e->s; s.now_ns=now_ns();
  s.flags=(e->handshake?ACTRYN_STATUS_HANDSHAKEN:0)|
   (e->tx_busy && e->tx_off?ACTRYN_STATUS_TX_STARTED:0)|(e->await?ACTRYN_STATUS_AWAITING:0)|
   (e->grant_authorized?ACTRYN_STATUS_GRANT_AUTHORIZED:0);
  mutex_unlock(&e->authority);
  return copy_to_user((void __user *)arg,&s,sizeof(s))?-EFAULT:0;
 }
 if(cmd!=ACTRYN_IOCTL_REQUEST) return -ENOTTY;
 if(copy_from_user(&r,(void __user *)arg,sizeof(r))) return -EFAULT;
 ret=canonical_request(&r); if(ret) return ret;
 ret=urgent_request(f,&r); if(ret) return ret;
 if(mutex_lock_interruptible(&e->authority)) return -ERESTARTSYS;
 apply_close(e); check_health(e);
 ret=e->s.state==ACTRYN_DETACHED?-ENODEV:do_request(f,&r);
 mutex_unlock(&e->authority);
 if(!ret && copy_to_user((void __user *)arg,&r,sizeof(r))) ret=-EFAULT;
 return ret;
}
static int authority_open(struct inode *inode,struct file *file)
{
 struct miscdevice *m=file->private_data;
 struct actryn_endpoint *e=container_of(m,struct actryn_endpoint,misc);
 struct actryn_file *f=kzalloc(sizeof(*f),GFP_KERNEL);
 if(!f) return -ENOMEM;
 mutex_lock(&e->authority);
 if(e->s.state==ACTRYN_DETACHED) { mutex_unlock(&e->authority); kfree(f); return -ENODEV; }
 kref_get(&e->refs); mutex_unlock(&e->authority);
 f->ep=e; file->private_data=f; return nonseekable_open(inode,file);
}
static int authority_release(struct inode *inode,struct file *file)
{
 struct actryn_file *f=file->private_data;
 if(f->role==ACTRYN_RUNTIME) {
  mutex_lock(&f->ep->authority);
  if(f->runtime_generation==f->ep->runtime_generation && f->ep->s.state!=ACTRYN_DETACHED) {
   request_close(f->ep,CTRL_FAULT,ACTRYN_OWNER_LOST,0,0); apply_close(f->ep);
  }
  mutex_unlock(&f->ep->authority);
 }
 kref_put(&f->ep->refs,endpoint_free); kfree(f); return 0;
}
static ssize_t authority_read(struct file *file,char __user *buf,size_t n,loff_t *offset)
{
 struct actryn_file *f=file->private_data; struct actryn_endpoint *e=f->ep;
 struct actryn_event v; unsigned long flags; int ret;
 if(f->role!=ACTRYN_EVENTS) return -EPERM;
 if(n<sizeof(v)) return -EINVAL;
 for(;;) {
  spin_lock_irqsave(&e->event_lock,flags);
  if(e->event_count) {
   v=e->events[e->event_tail]; e->event_tail=(e->event_tail+1)%EVENT_COUNT; e->event_count--;
   spin_unlock_irqrestore(&e->event_lock,flags); break;
  }
  spin_unlock_irqrestore(&e->event_lock,flags);
  if(READ_ONCE(e->stopping)) return 0;
  if(file->f_flags&O_NONBLOCK) return -EAGAIN;
  ret=wait_event_interruptible(e->event_wait,READ_ONCE(e->event_count)||READ_ONCE(e->stopping));
  if(ret) return ret;
 }
 if(copy_to_user(buf,&v,sizeof(v))) { request_close(e,CTRL_FAULT,ACTRYN_EVIDENCE_LOST,0,0); return -EFAULT; }
 return sizeof(v);
}
static __poll_t authority_poll(struct file *file,poll_table *wait)
{
 struct actryn_file *f=file->private_data; __poll_t mask=0;
 if(f->role!=ACTRYN_EVENTS) return EPOLLERR;
 poll_wait(file,&f->ep->event_wait,wait);
 if(READ_ONCE(f->ep->event_count)) mask|=EPOLLIN|EPOLLRDNORM;
 if(READ_ONCE(f->ep->stopping)) mask|=EPOLLHUP;
 return mask;
}
static const struct file_operations authority_fops={
 .owner=THIS_MODULE,.open=authority_open,.release=authority_release,
 .unlocked_ioctl=authority_ioctl,.compat_ioctl=compat_ptr_ioctl,
 .read=authority_read,.poll=authority_poll,
};
static int authority_probe(struct serdev_device *serdev)
{
 struct actryn_endpoint *e; int ret;
 if(!of_machine_is_compatible("linux,dummy-virt")) return -ENODEV;
 e=kzalloc(sizeof(*e),GFP_KERNEL); if(!e) return -ENOMEM;
 kref_init(&e->refs); e->serdev=serdev; mutex_init(&e->authority);
 spin_lock_init(&e->control_lock); spin_lock_init(&e->rx_lock); spin_lock_init(&e->event_lock);
 init_waitqueue_head(&e->event_wait); INIT_DELAYED_WORK(&e->work,endpoint_work);
 e->s.version=1; e->s.context_revision=1; e->s.state=ACTRYN_INHIBITED;
 serdev_device_set_drvdata(serdev,e); serdev_device_set_client_ops(serdev,&serial_ops);
 ret=serdev_device_open(serdev); if(ret) goto free;
 e->opened=true;
 if(serdev_device_set_baudrate(serdev,115200)!=115200) { ret=-EINVAL; goto close; }
 serdev_device_set_flow_control(serdev,false);
 ret=serdev_device_set_parity(serdev,SERDEV_PARITY_NONE); if(ret) goto close;
 e->misc=(struct miscdevice){ .minor=MISC_DYNAMIC_MINOR,.name="actryn-authority",
  .fops=&authority_fops,.parent=&serdev->dev,.mode=0600 };
 ret=misc_register(&e->misc); if(ret) goto close;
 dev_info(&serdev->dev,"Actryn software fixture authority v1, physical actuation unsupported\n");
 kick(e); return 0;
close:
 spin_lock_irq(&e->control_lock); e->stopping=true; spin_unlock_irq(&e->control_lock);
 cancel_delayed_work_sync(&e->work); serdev_device_close(serdev);
free:
 kref_put(&e->refs,endpoint_free); return ret;
}
static void authority_remove(struct serdev_device *serdev)
{
 struct actryn_endpoint *e=serdev_device_get_drvdata(serdev); unsigned long flags;
 request_close(e,CTRL_DETACH,ACTRYN_DEVICE_REMOVED,0,0);
 mutex_lock(&e->authority); apply_close(e);
 spin_lock_irqsave(&e->control_lock,flags); e->stopping=true; spin_unlock_irqrestore(&e->control_lock,flags);
 mutex_unlock(&e->authority);
 misc_deregister(&e->misc); cancel_delayed_work_sync(&e->work);
 /* PL011 shutdown joins IRQs; tty close flush joins the receive consumer. */
 if(e->opened) serdev_device_close(serdev);
 wake_up_interruptible(&e->event_wait); kref_put(&e->refs,endpoint_free);
}
static int authority_suspend(struct device *dev)
{
 struct actryn_endpoint *e=dev_get_drvdata(dev); int ret=0;
 mutex_lock(&e->authority);
 if(e->s.state==ACTRYN_ACTIVE || e->s.state==ACTRYN_REVOKING) ret=-EBUSY;
 else { e->handshake=false; e->grant_authorized=false;
  if(e->s.state!=ACTRYN_FAULT_LATCHED) e->s.state=ACTRYN_INHIBITED; }
 mutex_unlock(&e->authority); return ret;
}
static int authority_resume(struct device *dev)
{
 struct actryn_endpoint *e=dev_get_drvdata(dev);
 request_close(e,CTRL_FAULT,ACTRYN_TRANSPORT,0,0); return 0;
}
static const struct dev_pm_ops authority_pm={ .suspend=authority_suspend,.resume=authority_resume,
 .freeze=authority_suspend,.thaw=authority_resume,.poweroff=authority_suspend,.restore=authority_resume };
static const struct of_device_id authority_of_match[]={ { .compatible="actryn,fixture-v2" },{} };
MODULE_DEVICE_TABLE(of,authority_of_match);
static struct serdev_device_driver authority_driver={ .probe=authority_probe,.remove=authority_remove,
 .driver={ .name="actryn-authority",.of_match_table=authority_of_match,.pm=&authority_pm } };
module_serdev_device_driver(authority_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Actryn software fixture typed authority and serdev backend");
MODULE_AUTHOR("Utkarsh Maurya");
#ifdef ACTRYN_KUNIT_ENABLED
#include "actryn_driver_test.h"
#endif
