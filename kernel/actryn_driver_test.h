/* SPDX-License-Identifier: GPL-2.0-only */
#include <kunit/test.h>
#include <linux/kthread.h>
#include <linux/completion.h>

struct test_uart {
 u8 bytes[2*ACTRYN_ENCODED_MAX]; size_t count,limit; int error;
 struct serdev_device *inject_rx;
};
static ssize_t test_write(struct serdev_controller *ctrl,const u8 *data,size_t n)
{
 struct test_uart *uart=serdev_controller_get_drvdata(ctrl);
 if(uart->error) return uart->error;
 n=min(n,uart->limit);
 if(n>sizeof(uart->bytes)-uart->count) return -ENOSPC;
 memcpy(uart->bytes+uart->count,data,n); uart->count+=n;
 if(uart->inject_rx) {
  struct actryn_frame f={.kind=AW_OBSERVATION,.sequence=1,.context=1};
  u8 encoded[ACTRYN_ENCODED_MAX]; size_t length=actryn_encode(&f,encoded);
  struct serdev_device *serdev=uart->inject_rx; uart->inject_rx=NULL;
  /* The first worker already found RX empty. Arrival publishes an immediate
   * wakeup while its transmit call is still in progress. */
  receive_buf(serdev,encoded,length);
 }
 return n;
}
static const struct serdev_controller_ops test_uart_ops={.write_buf=test_write};

static void every_cancel_offset(struct kunit *test)
{
 struct actryn_frame original={.kind=AW_SAMPLE,.grant=1,.operation=1,.stream=1,
  .sequence=1,.transaction=7,.left=20,.right=20,.context=1}, received;
 u8 encoded[ACTRYN_ENCODED_MAX]; size_t len,cut;
 original.expiry=now_ns()+500*MS; len=actryn_encode(&original,encoded);
 for(cut=0;cut<len;cut++) {
  struct actryn_endpoint *e=kzalloc(sizeof(*e),GFP_KERNEL);
  struct test_transport {
   struct serdev_controller ctrl;
   struct serdev_device serdev;
   struct test_uart uart;
  } *transport=kunit_kzalloc(test,sizeof(*transport),GFP_KERNEL);
  struct test_uart *uart; u64 now=now_ns();
  KUNIT_ASSERT_NOT_NULL(test,e);
  KUNIT_ASSERT_NOT_NULL(test,transport);
  transport->ctrl.ops=&test_uart_ops; transport->serdev.ctrl=&transport->ctrl;
  uart=&transport->uart; uart->limit=cut;
  mutex_init(&e->authority); spin_lock_init(&e->control_lock); spin_lock_init(&e->rx_lock);
  spin_lock_init(&e->event_lock); init_waitqueue_head(&e->event_wait);
  e->stopping=true; e->serdev=&transport->serdev; e->handshake=true;
  e->s.state=ACTRYN_ACTIVE; e->s.operation_state=ACTRYN_OP_RUNNING;
  e->s.grant=1; e->s.operation=1; e->s.stream=1;
  e->published_grant=1; e->published_operation=1;
  e->map_host=now; e->map_ctl=now; e->next_transaction=7;
  e->observation.observation=1; e->observation.acquired_earliest_ns=now;
  e->observation.valid_until_ns=now+500*MS; e->tx_observation=e->observation;
  e->sample.deadline_ns=now+500*MS;
  original.expiry=now+500*MS; len=actryn_encode(&original,encoded);
  serdev_controller_set_drvdata(&transport->ctrl,uart);
  mutex_lock(&e->authority);
  KUNIT_EXPECT_EQ(test,queue_frame(e,&original),0);
  transmit(e);
  KUNIT_EXPECT_EQ(test,e->tx_off,cut);
  KUNIT_EXPECT_EQ(test,request_close(e,CTRL_OPERATION,ACTRYN_CANCELLED,1,1),0);
  apply_close(e); uart->limit=ACTRYN_ENCODED_MAX;
  transmit(e); transmit(e);
  if(cut) {
   KUNIT_EXPECT_EQ(test,memcmp(uart->bytes,encoded,len),0);
   KUNIT_EXPECT_EQ(test,actryn_decode(uart->bytes,len-1,&received),0);
   KUNIT_EXPECT_EQ(test,received.kind,(u16)AW_SAMPLE);
   KUNIT_EXPECT_EQ(test,actryn_decode(uart->bytes+len,uart->count-len-1,&received),0);
  } else KUNIT_EXPECT_EQ(test,actryn_decode(uart->bytes,uart->count-1,&received),0);
  KUNIT_EXPECT_EQ(test,received.kind,(u16)AW_QUIESCE);
  KUNIT_EXPECT_EQ(test,e->s.operation_state,(u32)ACTRYN_OP_CLOSING);
  mutex_unlock(&e->authority); kfree(e); kunit_kfree(test,transport);
 }
}
struct close_racer { struct actryn_endpoint *e; struct completion *start; u32 rank,reason; };
static int race_close(void *opaque)
{
 struct close_racer *r=opaque; unsigned int i;
 wait_for_completion(r->start);
 for(i=0;i<1000 && !kthread_should_stop();i++) {
  request_close(r->e,r->rank,r->reason,1,1); cond_resched();
 }
 while(!kthread_should_stop()) schedule_timeout_interruptible(1);
 return 0;
}
static void concurrent_closure(struct kunit *test)
{
 struct actryn_endpoint *e=kunit_kzalloc(test,sizeof(*e),GFP_KERNEL);
 DECLARE_COMPLETION_ONSTACK(start);
 struct close_racer a={.e=e,.start=&start,.rank=CTRL_OPERATION,.reason=ACTRYN_CANCELLED};
 struct close_racer b={.e=e,.start=&start,.rank=CTRL_FAULT,.reason=ACTRYN_TRANSPORT};
 struct task_struct *first,*second; unsigned int i;
 KUNIT_ASSERT_NOT_NULL(test,e);
 mutex_init(&e->authority); spin_lock_init(&e->control_lock); spin_lock_init(&e->rx_lock);
 spin_lock_init(&e->event_lock); init_waitqueue_head(&e->event_wait);
 e->stopping=true; e->s.state=ACTRYN_ACTIVE; e->s.operation_state=ACTRYN_OP_RUNNING;
 e->s.grant=e->published_grant=1; e->s.operation=e->published_operation=1;
 first=kthread_run(race_close,&a,"actryn-close-a");
 second=kthread_run(race_close,&b,"actryn-close-b");
 complete_all(&start);
 for(i=0;i<1000;i++) { mutex_lock(&e->authority); apply_close(e); mutex_unlock(&e->authority); cond_resched(); }
 if(!IS_ERR(first)) kthread_stop(first);
 if(!IS_ERR(second)) kthread_stop(second);
 KUNIT_ASSERT_FALSE(test,IS_ERR(first)); KUNIT_ASSERT_FALSE(test,IS_ERR(second));
 mutex_lock(&e->authority);
 request_close(e,CTRL_FAULT,ACTRYN_TRANSPORT,0,0); apply_close(e);
 request_close(e,CTRL_GRANT,ACTRYN_GRANT_REVOKED,1,0); apply_close(e);
 request_close(e,CTRL_OPERATION,ACTRYN_CANCELLED,1,1); apply_close(e);
 KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_FAULT_LATCHED);
 KUNIT_EXPECT_EQ(test,e->s.operation_state,(u32)ACTRYN_OP_UNKNOWN);
 request_close(e,CTRL_DETACH,ACTRYN_DEVICE_REMOVED,0,0); apply_close(e);
 request_close(e,CTRL_FAULT,ACTRYN_TRANSPORT,0,0); apply_close(e);
 KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_DETACHED);
 mutex_unlock(&e->authority);
}
static void late_receipts(struct kunit *test)
{
 unsigned int kind;
 for(kind=0;kind<2;kind++) {
  struct actryn_endpoint *e=kunit_kzalloc(test,sizeof(*e),GFP_KERNEL);
  struct actryn_frame f={.kind=kind?AW_QUIESCED:AW_APPLIED,.grant=1,.operation=1,
   .stream=1,.transaction=8,.context=1};
  u64 now=now_ns();
  KUNIT_ASSERT_NOT_NULL(test,e);
  mutex_init(&e->authority); spin_lock_init(&e->control_lock); spin_lock_init(&e->rx_lock);
  spin_lock_init(&e->event_lock); init_waitqueue_head(&e->event_wait);
  e->stopping=true; e->s.state=ACTRYN_ACTIVE;
  e->s.operation_state=kind?ACTRYN_OP_CLOSING:ACTRYN_OP_RUNNING;
  e->s.grant=e->published_grant=1; e->s.operation=e->published_operation=1;
  e->grant_deadline=e->health_deadline=e->close_deadline=now+1000*MS;
  e->operation_deadline=kind?now-1:now+1000*MS;
  e->awaited_host_deadline=now-1; e->await=true; e->awaited=f;
  e->awaited.kind=kind?AW_QUIESCE:AW_SAMPLE;
  mutex_lock(&e->authority); receive_frame(e,&f); mutex_unlock(&e->authority);
  KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_FAULT_LATCHED);
  KUNIT_EXPECT_EQ(test,e->s.operation_state,(u32)ACTRYN_OP_UNKNOWN);
  KUNIT_EXPECT_EQ(test,e->s.reason,(u32)ACTRYN_EXPIRED);
 }
}
static void every_fault_recovery_offset(struct kunit *test)
{
 struct actryn_frame original={.kind=AW_SAMPLE,.grant=1,.operation=1,.stream=1,
  .sequence=1,.transaction=7,.left=20,.right=20,.context=1},hello,ack;
 u8 encoded[ACTRYN_ENCODED_MAX]; size_t len,cut;
 original.expiry=now_ns()+500*MS; len=actryn_encode(&original,encoded);
 for(cut=0;cut<len;cut++) {
  struct actryn_endpoint *e=kunit_kzalloc(test,sizeof(*e),GFP_KERNEL);
  struct serdev_controller *ctrl=kunit_kzalloc(test,sizeof(*ctrl),GFP_KERNEL);
  struct serdev_device *serdev=kunit_kzalloc(test,sizeof(*serdev),GFP_KERNEL);
  struct test_uart *uart=kunit_kzalloc(test,sizeof(*uart),GFP_KERNEL);
  u64 now=now_ns(),expiry=now+500*MS;
  KUNIT_ASSERT_NOT_NULL(test,e); KUNIT_ASSERT_NOT_NULL(test,ctrl);
  KUNIT_ASSERT_NOT_NULL(test,serdev); KUNIT_ASSERT_NOT_NULL(test,uart);
  ctrl->ops=&test_uart_ops; serdev->ctrl=ctrl; e->serdev=serdev;
  serdev_controller_set_drvdata(ctrl,uart); uart->limit=cut;
  mutex_init(&e->authority); spin_lock_init(&e->control_lock); spin_lock_init(&e->rx_lock);
  spin_lock_init(&e->event_lock); init_waitqueue_head(&e->event_wait);
  e->stopping=true; e->handshake=true; e->s.state=ACTRYN_ACTIVE;
  e->s.operation_state=ACTRYN_OP_RUNNING; e->s.operation=1;
  e->s.grant=1; e->s.stream=1; e->map_host=now; e->map_ctl=now;
  e->observation.observation=1; e->observation.acquired_earliest_ns=now;
  e->observation.valid_until_ns=expiry; e->tx_observation=e->observation;
  e->sample.deadline_ns=expiry; original.expiry=expiry;
  mutex_lock(&e->authority); KUNIT_EXPECT_EQ(test,queue_frame(e,&original),0);
  transmit_at(e,now); KUNIT_EXPECT_EQ(test,e->tx_off,cut);
  uart->error=-EIO; transmit_at(e,now);
  KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_FAULT_LATCHED);
  KUNIT_EXPECT_EQ(test,e->s.operation_state,(u32)ACTRYN_OP_UNKNOWN);
  KUNIT_EXPECT_EQ(test,e->resync_after,cut?expiry:0);
  uart->error=0; uart->limit=ACTRYN_ENCODED_MAX+1;
  /* One recovery handshake, with deterministic host-time snapshots. */
  KUNIT_EXPECT_EQ(test,handshake(e),0);
  if(cut) { transmit_at(e,expiry-1); KUNIT_EXPECT_EQ(test,uart->count,cut); }
  transmit_at(e,expiry);
  KUNIT_EXPECT_EQ(test,uart->bytes[cut],(u8)0);
  KUNIT_EXPECT_EQ(test,actryn_decode(uart->bytes+cut+1,uart->count-cut-2,&hello),0);
  KUNIT_EXPECT_EQ(test,hello.kind,(u16)AW_HELLO);
  KUNIT_EXPECT_TRUE(test,e->await);
  ack=hello; ack.kind=AW_HELLO_ACK; ack.device[0]=1;
  ack.boot=1; ack.session=1; ack.status=1; ack.controller_ns=expiry;
  /* Receipt validation gets its own fresh real snapshot. */
  e->hello_sent=now_ns(); receive_frame(e,&ack);
  KUNIT_EXPECT_TRUE(test,e->handshake);
  KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_INHIBITED);
  KUNIT_EXPECT_FALSE(test,e->grant_authorized);
  mutex_unlock(&e->authority);
  kunit_kfree(test,uart); kunit_kfree(test,serdev); kunit_kfree(test,ctrl); kunit_kfree(test,e);
 }
}
static void stalled_parser_timeout(struct kunit *test)
{
 struct actryn_endpoint *e=kunit_kzalloc(test,sizeof(*e),GFP_KERNEL);
 struct serdev_device *serdev=kunit_kzalloc(test,sizeof(*serdev),GFP_KERNEL);
 struct actryn_frame f={.kind=AW_APPLIED,.transaction=1};
 u8 encoded[ACTRYN_ENCODED_MAX]; size_t len=actryn_encode(&f,encoded);
 KUNIT_ASSERT_NOT_NULL(test,e); KUNIT_ASSERT_NOT_NULL(test,serdev);
 mutex_init(&e->authority); spin_lock_init(&e->control_lock);
 spin_lock_init(&e->rx_lock); spin_lock_init(&e->event_lock);
 init_waitqueue_head(&e->event_wait); e->stopping=true;
 e->s.state=ACTRYN_ACTIVE; e->s.operation=1;
 serdev_device_set_drvdata(serdev,e);
 KUNIT_EXPECT_EQ(test,receive_buf(serdev,encoded,len-1),len-1);
 e->parser_started=now_ns()-500*MS;
 KUNIT_EXPECT_EQ(test,receive_buf(serdev,encoded+len-1,1),(size_t)1);
 KUNIT_EXPECT_EQ(test,e->rx_count,0U);
 mutex_lock(&e->authority); apply_close(e); mutex_unlock(&e->authority);
 KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_FAULT_LATCHED);
 KUNIT_EXPECT_EQ(test,e->s.reason,(u32)ACTRYN_PROTOCOL);
}
static void inhibited_revoke(struct kunit *test)
{
 struct actryn_endpoint *e=kunit_kzalloc(test,sizeof(*e),GFP_KERNEL);
 KUNIT_ASSERT_NOT_NULL(test,e);
 mutex_init(&e->authority); spin_lock_init(&e->control_lock);
 spin_lock_init(&e->event_lock); init_waitqueue_head(&e->event_wait);
 e->stopping=true; e->s.state=ACTRYN_INHIBITED;
 e->s.grant=e->published_grant=1; e->s.instance=1;
 e->tx_busy=true; e->tx_frame.kind=AW_HELLO;
 mutex_lock(&e->authority);
 KUNIT_EXPECT_EQ(test,request_close(e,CTRL_GRANT,ACTRYN_GRANT_REVOKED,1,0),0);
 apply_close(e); mutex_unlock(&e->authority);
 KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_INHIBITED);
 KUNIT_EXPECT_EQ(test,e->s.instance,0ULL);
 KUNIT_EXPECT_FALSE(test,e->grant_authorized);
 KUNIT_EXPECT_TRUE(test,e->tx_busy);
}
static struct actryn_endpoint *test_endpoint(struct kunit *test)
{
 struct actryn_endpoint *e=kunit_kzalloc(test,sizeof(*e),GFP_KERNEL);
 if(!e) return NULL;
 mutex_init(&e->authority); spin_lock_init(&e->control_lock);
 spin_lock_init(&e->rx_lock); spin_lock_init(&e->event_lock);
 init_waitqueue_head(&e->event_wait); e->stopping=true;
 return e;
}
static void retained_rx_recovery(struct kunit *test)
{
 struct actryn_frame old={.kind=AW_OBSERVATION,.boot=1,.session=1,.sequence=1};
 u8 old_bytes[ACTRYN_ENCODED_MAX],ack_bytes[ACTRYN_ENCODED_MAX];
 size_t len=actryn_encode(&old,old_bytes),cut;
 for(cut=1;cut<len;cut++) {
  struct actryn_endpoint *e=test_endpoint(test);
  struct serdev_controller *ctrl=kunit_kzalloc(test,sizeof(*ctrl),GFP_KERNEL);
  struct serdev_device *serdev=kunit_kzalloc(test,sizeof(*serdev),GFP_KERNEL);
  struct test_uart *uart=kunit_kzalloc(test,sizeof(*uart),GFP_KERNEL);
  struct actryn_frame ack={.kind=AW_HELLO_ACK,.boot=2,.session=1,.status=1,.transaction=1};
  size_t ack_len;
  KUNIT_ASSERT_NOT_NULL(test,e); KUNIT_ASSERT_NOT_NULL(test,ctrl);
  KUNIT_ASSERT_NOT_NULL(test,serdev); KUNIT_ASSERT_NOT_NULL(test,uart);
  ctrl->ops=&test_uart_ops; serdev->ctrl=ctrl; e->serdev=serdev;
  serdev_controller_set_drvdata(ctrl,uart); serdev_device_set_drvdata(serdev,e);
  uart->limit=ACTRYN_ENCODED_MAX+1; ack.device[0]=1;
  mutex_lock(&e->authority);
  KUNIT_ASSERT_EQ(test,handshake(e),0); transmit(e);
  memcpy(ack.nonce,e->s.runtime_nonce,16); ack_len=actryn_encode(&ack,ack_bytes);
  /* Without a synchronization delimiter, a retained prefix can corrupt the
   * next ACK. No authority is created; explicit recovery needs a fresh ACK. */
  KUNIT_EXPECT_EQ(test,receive_buf(serdev,old_bytes,cut),cut);
  KUNIT_EXPECT_EQ(test,receive_buf(serdev,ack_bytes,ack_len),ack_len);
  apply_close(e);
  KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_INHIBITED);
  KUNIT_EXPECT_FALSE(test,e->handshake);
  KUNIT_EXPECT_EQ(test,e->rx_count,0U);
  /* The delimiter has retired the malformed prefix. One explicit RECOVER
   * performs a new nonce handshake; the old ACK cannot authorize it. */
  uart->count=0; KUNIT_ASSERT_EQ(test,handshake(e),0); transmit(e);
  receive_frame(e,&ack); KUNIT_EXPECT_FALSE(test,e->handshake);
  memcpy(ack.nonce,e->s.runtime_nonce,16); ack.session=2;
  ack_len=actryn_encode(&ack,ack_bytes); e->hello_sent=now_ns();
  KUNIT_EXPECT_EQ(test,receive_buf(serdev,ack_bytes,ack_len),ack_len);
  KUNIT_ASSERT_EQ(test,e->rx_count,1U); receive_frame(e,&e->rx[e->rx_tail]);
  KUNIT_EXPECT_TRUE(test,e->handshake);
  KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_INHIBITED);
  KUNIT_EXPECT_FALSE(test,e->grant_authorized);
  mutex_unlock(&e->authority);
  kunit_kfree(test,uart); kunit_kfree(test,serdev); kunit_kfree(test,ctrl); kunit_kfree(test,e);
 }
}
static void stale_epoch_receipts(struct kunit *test)
{
 unsigned int field;
 for(field=0;field<4;field++) {
  struct actryn_endpoint *e=test_endpoint(test);
  struct actryn_frame f={.kind=AW_APPLIED,.boot=2,.session=2,.grant=1,
   .operation=1,.stream=1,.sequence=1,.transaction=8,.context=1};
  KUNIT_ASSERT_NOT_NULL(test,e);
  e->s.state=ACTRYN_ACTIVE; e->s.operation_state=ACTRYN_OP_RUNNING;
  e->s.controller_boot=f.boot; e->s.controller_session=f.session;
  e->s.device_identity[0]=f.device[0]=1; e->s.runtime_nonce[0]=f.nonce[0]=1;
  e->await=true; e->awaited=f; e->awaited.kind=AW_SAMPLE;
  if(field==0) f.device[0]=2;
  if(field==1) f.nonce[0]=2;
  if(field==2) f.boot--;
  if(field==3) f.session--;
  mutex_lock(&e->authority); receive_frame(e,&f); mutex_unlock(&e->authority);
  KUNIT_EXPECT_TRUE(test,e->await);
  KUNIT_EXPECT_EQ(test,e->s.sequence,0ULL);
  KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_ACTIVE);
  KUNIT_EXPECT_EQ(test,e->event_count,0U);
 }
}
static void handshake_rx_sync(struct kunit *test)
{
 struct actryn_endpoint *e=test_endpoint(test);
 struct serdev_device *serdev=kunit_kzalloc(test,sizeof(*serdev),GFP_KERNEL);
 struct actryn_frame old={.kind=AW_OBSERVATION,.boot=1,.session=1,.sequence=1};
 struct actryn_frame ack={.kind=AW_HELLO_ACK,.boot=2,.session=1,.status=1,.transaction=1};
 u8 bytes[ACTRYN_ENCODED_MAX]; size_t len;
 KUNIT_ASSERT_NOT_NULL(test,e); KUNIT_ASSERT_NOT_NULL(test,serdev);
 serdev_device_set_drvdata(serdev,e); e->serdev=serdev; ack.device[0]=1;
 mutex_lock(&e->authority);
 KUNIT_ASSERT_EQ(test,handshake(e),0);
 /* Model an already transmitted HELLO, without a timing-dependent UART. */
 e->awaited=e->tx_frame; e->tx_busy=false; e->await=true; e->hello_sent=now_ns();
 memcpy(ack.nonce,e->s.runtime_nonce,16);
 /* Actual ARM trace: retained observation missing one byte, then valid ACK. */
 len=actryn_encode(&old,bytes);
 KUNIT_EXPECT_EQ(test,receive_buf(serdev,bytes+1,len-1),len-1);
 apply_close(e);
 KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_INHIBITED);
 KUNIT_EXPECT_FALSE(test,e->handshake); KUNIT_EXPECT_FALSE(test,e->grant_authorized);
 len=actryn_encode(&ack,bytes); e->hello_sent=now_ns();
 KUNIT_EXPECT_EQ(test,receive_buf(serdev,bytes,len),len);
 KUNIT_ASSERT_EQ(test,e->rx_count,1U);
 receive_frame(e,&e->rx[e->rx_tail]);
 KUNIT_EXPECT_TRUE(test,e->handshake);
 KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_INHIBITED);
 /* Once mapping exists, the same malformed suffix is a protocol fault. */
 len=actryn_encode(&old,bytes);
 KUNIT_EXPECT_EQ(test,receive_buf(serdev,bytes+1,len-1),len-1);
 apply_close(e);
 KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_FAULT_LATCHED);
 KUNIT_EXPECT_EQ(test,e->s.reason,(u32)ACTRYN_PROTOCOL);
 /* Noise cannot refresh the absolute handshake deadline. */
 KUNIT_ASSERT_EQ(test,handshake(e),0);
 {
  u64 deadline=e->receipt_deadline; unsigned int i;
  for(i=0;i<64;i++) receive_buf(serdev,bytes+1,len-1);
  KUNIT_EXPECT_EQ(test,e->receipt_deadline,deadline);
  KUNIT_EXPECT_LE(test,e->parser_sync_deadline,deadline);
  e->receipt_deadline=now_ns()-1; check_health(e);
  KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_FAULT_LATCHED);
  KUNIT_EXPECT_EQ(test,e->s.reason,(u32)ACTRYN_TRANSPORT);
 }
 /* Valid-frame capacity remains strict even during synchronization. */
 KUNIT_ASSERT_EQ(test,handshake(e),0);
 e->rx_head=e->rx_tail=e->rx_count=0;
 {
  unsigned int i;
  for(i=0;i<=RX_COUNT;i++) receive_buf(serdev,bytes,len);
  apply_close(e);
  KUNIT_EXPECT_EQ(test,e->rx_count,(unsigned int)RX_COUNT);
  KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_FAULT_LATCHED);
  KUNIT_EXPECT_EQ(test,e->s.reason,(u32)ACTRYN_PROTOCOL);
 }
 mutex_unlock(&e->authority);
}
static void new_controller_epoch(struct kunit *test)
{
 unsigned int field;
 for(field=0;field<2;field++) {
  struct actryn_endpoint *e=test_endpoint(test);
  struct actryn_frame f={.kind=AW_FAULT,.boot=2,.session=2};
  KUNIT_ASSERT_NOT_NULL(test,e);
  e->handshake=true; e->grant_authorized=true;
  e->s.state=ACTRYN_ACTIVE; e->s.operation_state=ACTRYN_OP_RUNNING;
  e->s.operation=1; e->s.controller_boot=f.boot; e->s.controller_session=f.session;
  e->s.device_identity[0]=f.device[0]=1; e->s.runtime_nonce[0]=1;
  if(field==0) { f.boot++; f.session=0; }
  else { f.session++; f.nonce[0]=2; }
  mutex_lock(&e->authority); receive_frame(e,&f); mutex_unlock(&e->authority);
  /* A strictly newer durable epoch is evidence of reset, unlike old replay. */
  KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_FAULT_LATCHED);
  KUNIT_EXPECT_EQ(test,e->s.operation_state,(u32)ACTRYN_OP_UNKNOWN);
  KUNIT_EXPECT_FALSE(test,e->grant_authorized);
 }
}
static void bounded_queues_counters(struct kunit *test)
{
 struct actryn_endpoint *e=test_endpoint(test),*full=test_endpoint(test);
 struct serdev_device *serdev=kunit_kzalloc(test,sizeof(*serdev),GFP_KERNEL);
 struct actryn_frame f={.kind=AW_OBSERVATION,.sequence=1};
 u8 bytes[ACTRYN_ENCODED_MAX]; size_t len=actryn_encode(&f,bytes); unsigned int i;
 u64 transaction=123;
 KUNIT_ASSERT_NOT_NULL(test,e); KUNIT_ASSERT_NOT_NULL(test,full); KUNIT_ASSERT_NOT_NULL(test,serdev);
 serdev_device_set_drvdata(serdev,e);
 for(i=0;i<RX_COUNT;i++) KUNIT_EXPECT_EQ(test,receive_buf(serdev,bytes,len),len);
 KUNIT_EXPECT_EQ(test,e->rx_count,(unsigned int)RX_COUNT);
 KUNIT_EXPECT_EQ(test,e->close.rank,0U);
 KUNIT_EXPECT_EQ(test,receive_buf(serdev,bytes,len),len);
 KUNIT_EXPECT_EQ(test,e->rx_count,(unsigned int)RX_COUNT);
 mutex_lock(&e->authority); apply_close(e);
 KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_FAULT_LATCHED);
 KUNIT_EXPECT_EQ(test,e->s.reason,(u32)ACTRYN_PROTOCOL);
 e->next_transaction=U64_MAX;
 KUNIT_EXPECT_EQ(test,next_transaction(e,&transaction),-EOVERFLOW);
 KUNIT_EXPECT_EQ(test,transaction,123ULL);
 KUNIT_EXPECT_EQ(test,e->next_transaction,U64_MAX);
 mutex_unlock(&e->authority);
 mutex_lock(&full->authority);
 full->event_sequence=U64_MAX; full->s.events_lost=U32_MAX-1;
 event(full,1); event(full,1); apply_close(full);
 KUNIT_EXPECT_EQ(test,full->event_sequence,U64_MAX);
 KUNIT_EXPECT_EQ(test,full->s.events_lost,U32_MAX);
 KUNIT_EXPECT_EQ(test,full->event_count,0U);
 KUNIT_EXPECT_EQ(test,full->s.state,(u32)ACTRYN_FAULT_LATCHED);
 full->close_serial=U64_MAX; full->close.rank=0;
 KUNIT_EXPECT_EQ(test,request_close(full,CTRL_OPERATION,ACTRYN_CANCELLED,0,0),-EOVERFLOW);
 KUNIT_EXPECT_EQ(test,full->close.rank,(u32)CTRL_FAULT);
 KUNIT_EXPECT_EQ(test,full->close.revision,0ULL);
 actryn_clear_close(&full->close,0);
 KUNIT_EXPECT_EQ(test,full->close.rank,(u32)CTRL_FAULT);
 mutex_unlock(&full->authority);
}
static void pm_inhibition(struct kunit *test)
{
 struct actryn_endpoint *e=test_endpoint(test);
 struct device *device=kunit_kzalloc(test,sizeof(*device),GFP_KERNEL);
 KUNIT_ASSERT_NOT_NULL(test,e); KUNIT_ASSERT_NOT_NULL(test,device);
 dev_set_drvdata(device,e); e->s.state=ACTRYN_ACTIVE; e->handshake=true;
 e->grant_authorized=true; e->s.operation=1; e->s.operation_state=ACTRYN_OP_RUNNING;
 KUNIT_EXPECT_EQ(test,authority_suspend(device),-EBUSY);
 KUNIT_EXPECT_TRUE(test,e->grant_authorized);
 KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_ACTIVE);
 e->s.state=ACTRYN_REVOKING;
 KUNIT_EXPECT_EQ(test,authority_suspend(device),-EBUSY);
 e->s.state=ACTRYN_READY;
 KUNIT_EXPECT_EQ(test,authority_suspend(device),0);
 KUNIT_EXPECT_FALSE(test,e->handshake); KUNIT_EXPECT_FALSE(test,e->grant_authorized);
 KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_INHIBITED);
 KUNIT_EXPECT_EQ(test,authority_resume(device),0);
 mutex_lock(&e->authority); apply_close(e); mutex_unlock(&e->authority);
 KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_FAULT_LATCHED);
 KUNIT_EXPECT_EQ(test,e->s.operation_state,(u32)ACTRYN_OP_UNKNOWN);
}
static void grant_closure_idempotence(struct kunit *test)
{
 unsigned int initial_rank; size_t cut;
 /* Includes zero accepted bytes, every partial prefix, and receipt pending.
  * The operation-close branch tests escalation as well as repeated revoke. */
 for(initial_rank=CTRL_OPERATION;initial_rank<=CTRL_GRANT;initial_rank++)
 for(cut=0;cut<=ACTRYN_ENCODED_MAX;cut++) {
  struct actryn_endpoint *e=test_endpoint(test);
  struct serdev_controller *ctrl=kunit_kzalloc(test,sizeof(*ctrl),GFP_KERNEL);
  struct serdev_device *serdev=kunit_kzalloc(test,sizeof(*serdev),GFP_KERNEL);
  struct test_uart *uart=kunit_kzalloc(test,sizeof(*uart),GFP_KERNEL);
  struct actryn_frame barrier,receipt; u8 bytes[ACTRYN_ENCODED_MAX];
  u64 now=now_ns(),deadline,transaction; size_t length; bool awaiting;
  KUNIT_ASSERT_NOT_NULL(test,e); KUNIT_ASSERT_NOT_NULL(test,ctrl);
  KUNIT_ASSERT_NOT_NULL(test,serdev); KUNIT_ASSERT_NOT_NULL(test,uart);
  ctrl->ops=&test_uart_ops; serdev->ctrl=ctrl; e->serdev=serdev;
  serdev_controller_set_drvdata(ctrl,uart); uart->limit=cut;
  e->handshake=true; e->grant_authorized=true;
  e->s.state=ACTRYN_ACTIVE; e->s.operation_state=ACTRYN_OP_RUNNING;
  e->s.grant=e->published_grant=1; e->s.operation=e->published_operation=1;
  e->s.stream=e->published_stream=1; e->s.instance=1;
  e->grant_deadline=e->health_deadline=e->operation_deadline=now+10000*MS;
  mutex_lock(&e->authority);
  KUNIT_EXPECT_EQ(test,request_close(e,initial_rank,
   initial_rank==CTRL_OPERATION?ACTRYN_CANCELLED:ACTRYN_GRANT_REVOKED,1,1),0);
  apply_close(e); deadline=e->close_deadline; transmit_at(e,now);
  barrier=e->tx_frame; transaction=e->next_transaction;
  length=actryn_encode(&barrier,bytes); awaiting=e->await;
  KUNIT_EXPECT_EQ(test,barrier.kind,(u16)AW_QUIESCE);
  KUNIT_EXPECT_EQ(test,uart->count,min(cut,length));
  /* Mirrors urgent publication, worker dispatch, then ioctl publication. */
  KUNIT_EXPECT_EQ(test,request_close(e,CTRL_GRANT,ACTRYN_GRANT_REVOKED,1,0),0);
  apply_close(e);
  KUNIT_EXPECT_EQ(test,request_close(e,CTRL_GRANT,ACTRYN_GRANT_REVOKED,1,0),0);
  apply_close(e);
  KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_REVOKING);
  KUNIT_EXPECT_EQ(test,e->s.reason,(u32)ACTRYN_GRANT_REVOKED);
  KUNIT_EXPECT_FALSE(test,e->grant_authorized);
  KUNIT_EXPECT_EQ(test,e->s.instance,0ULL);
  KUNIT_EXPECT_EQ(test,e->close_deadline,deadline);
  KUNIT_EXPECT_EQ(test,e->await,awaiting);
  KUNIT_EXPECT_FALSE(test,e->quiesce_needed);
  uart->limit=ACTRYN_ENCODED_MAX; transmit_at(e,now); transmit_at(e,now);
  KUNIT_EXPECT_EQ(test,e->next_transaction,transaction);
  KUNIT_EXPECT_EQ(test,uart->count,length);
  KUNIT_EXPECT_EQ(test,memcmp(uart->bytes,bytes,length),0);
  KUNIT_EXPECT_TRUE(test,e->await);
  KUNIT_EXPECT_EQ(test,memcmp(&e->awaited,&barrier,sizeof(barrier)),0);
  KUNIT_EXPECT_EQ(test,request_close(e,CTRL_GRANT,ACTRYN_GRANT_REVOKED,1,0),0);
  apply_close(e); KUNIT_EXPECT_TRUE(test,e->await);
  KUNIT_EXPECT_EQ(test,e->close_deadline,deadline);
  receipt=barrier; receipt.kind=AW_QUIESCED; receipt.controller_ns=now;
  receive_frame(e,&receipt);
  KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_READY);
  KUNIT_EXPECT_EQ(test,e->s.operation_state,(u32)ACTRYN_OP_RECONCILED);
  KUNIT_EXPECT_FALSE(test,e->grant_authorized);
  /* Idempotence never suppresses a stronger fault or resurrects authority. */
  fault(e,ACTRYN_TRANSPORT);
  KUNIT_EXPECT_EQ(test,request_close(e,CTRL_GRANT,ACTRYN_GRANT_REVOKED,1,0),0);
  apply_close(e);
  KUNIT_EXPECT_EQ(test,e->s.state,(u32)ACTRYN_FAULT_LATCHED);
  KUNIT_EXPECT_EQ(test,e->s.reason,(u32)ACTRYN_TRANSPORT);
  mutex_unlock(&e->authority);
  kunit_kfree(test,uart); kunit_kfree(test,serdev); kunit_kfree(test,ctrl); kunit_kfree(test,e);
 }
}
struct wakeup_test {
 struct actryn_endpoint endpoint;
 struct completion tail_done,release;
 bool first,queued;
 unsigned long tail_timer_expires;
};
static void wakeup_test_worker(struct work_struct *work)
{
 struct actryn_endpoint *e=container_of(to_delayed_work(work),struct actryn_endpoint,work);
 struct wakeup_test *t=container_of(e,struct wakeup_test,endpoint);
 if(!t->first) return;
 t->first=false;
 endpoint_work(work);
 /* A zero-delay kick does not arm the timer. Its expires field stays zero,
  * even if the incorrectly added ten-ms timer has fired before inspection. */
 t->tail_timer_expires=e->work.timer.expires;
 t->queued=delayed_work_pending(&e->work);
 complete(&t->tail_done); wait_for_completion(&t->release);
}
static void receive_wakeup_preserved(struct kunit *test)
{
 struct wakeup_test *t=kunit_kzalloc(test,sizeof(*t),GFP_KERNEL);
 struct serdev_controller *ctrl=kunit_kzalloc(test,sizeof(*ctrl),GFP_KERNEL);
 struct serdev_device *serdev=kunit_kzalloc(test,sizeof(*serdev),GFP_KERNEL);
 struct test_uart *uart=kunit_kzalloc(test,sizeof(*uart),GFP_KERNEL);
 struct actryn_endpoint *e; struct actryn_frame hello={.kind=AW_HELLO,.transaction=1};
 unsigned long flags,finished;
 KUNIT_ASSERT_NOT_NULL(test,t); KUNIT_ASSERT_NOT_NULL(test,ctrl);
 KUNIT_ASSERT_NOT_NULL(test,serdev); KUNIT_ASSERT_NOT_NULL(test,uart);
 e=&t->endpoint; mutex_init(&e->authority); spin_lock_init(&e->control_lock);
 spin_lock_init(&e->rx_lock); spin_lock_init(&e->event_lock); init_waitqueue_head(&e->event_wait);
 init_completion(&t->tail_done); init_completion(&t->release); t->first=true;
 INIT_DELAYED_WORK(&e->work,wakeup_test_worker);
 ctrl->ops=&test_uart_ops; serdev->ctrl=ctrl; e->serdev=serdev;
 serdev_controller_set_drvdata(ctrl,uart); serdev_device_set_drvdata(serdev,e);
 uart->limit=ACTRYN_ENCODED_MAX+1; uart->inject_rx=serdev;
 mutex_lock(&e->authority); KUNIT_EXPECT_EQ(test,queue_frame(e,&hello),0); mutex_unlock(&e->authority);
 KUNIT_EXPECT_TRUE(test,queue_delayed_work(system_wq,&e->work,0));
 finished=wait_for_completion_timeout(&t->tail_done,msecs_to_jiffies(3000));
 if(finished) {
  KUNIT_EXPECT_EQ(test,e->rx_count,1U);
  KUNIT_EXPECT_TRUE(test,t->queued);
  KUNIT_EXPECT_EQ(test,t->tail_timer_expires,0UL);
 }
 spin_lock_irqsave(&e->control_lock,flags); e->stopping=true;
 spin_unlock_irqrestore(&e->control_lock,flags);
 complete(&t->release); cancel_delayed_work_sync(&e->work);
 KUNIT_EXPECT_NE(test,finished,0UL);
}
static struct kunit_case driver_cases[]={KUNIT_CASE(every_cancel_offset),KUNIT_CASE(concurrent_closure),KUNIT_CASE(late_receipts),KUNIT_CASE(every_fault_recovery_offset),KUNIT_CASE(stalled_parser_timeout),KUNIT_CASE(inhibited_revoke),KUNIT_CASE(retained_rx_recovery),KUNIT_CASE(stale_epoch_receipts),KUNIT_CASE(handshake_rx_sync),KUNIT_CASE(new_controller_epoch),KUNIT_CASE(bounded_queues_counters),KUNIT_CASE(pm_inhibition),KUNIT_CASE(grant_closure_idempotence),KUNIT_CASE(receive_wakeup_preserved),{}};
static struct kunit_suite driver_suite={.name="actryn-serdev-recovery",.test_cases=driver_cases};
kunit_test_suite(driver_suite);
