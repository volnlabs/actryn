/* SPDX-License-Identifier: GPL-2.0-only */
#include <kunit/test.h>
#include <linux/kthread.h>
#include <linux/completion.h>

struct test_uart { u8 bytes[2*ACTRYN_ENCODED_MAX]; size_t count,limit; int error; };
static ssize_t test_write(struct serdev_controller *ctrl,const u8 *data,size_t n)
{
 struct test_uart *uart=serdev_controller_get_drvdata(ctrl);
 if(uart->error) return uart->error;
 n=min(n,uart->limit);
 if(n>sizeof(uart->bytes)-uart->count) return -ENOSPC;
 memcpy(uart->bytes+uart->count,data,n); uart->count+=n;
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
  mutex_init(&e->authority); spin_lock_init(&e->control_lock);
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
 mutex_init(&e->authority); spin_lock_init(&e->control_lock);
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
  mutex_init(&e->authority); spin_lock_init(&e->control_lock);
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
  mutex_init(&e->authority); spin_lock_init(&e->control_lock);
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
static struct kunit_case driver_cases[]={KUNIT_CASE(every_cancel_offset),KUNIT_CASE(concurrent_closure),KUNIT_CASE(late_receipts),KUNIT_CASE(every_fault_recovery_offset),KUNIT_CASE(stalled_parser_timeout),{}};
static struct kunit_suite driver_suite={.name="actryn-serdev-recovery",.test_cases=driver_cases};
kunit_test_suite(driver_suite);
