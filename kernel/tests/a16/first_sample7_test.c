/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <stdio.h>
#include "first_sample7.h"
int main(void)
{
 struct first_sample7 g,bad;
 struct actryn_status s={.version=1,.runtime_nonce={1}};
 struct actryn_event h={.sequence=3,.captured_ns=1000*A16_MS,
  .kind=ACTRYN_EVENT_WIRE|AW_HELLO_ACK,.status={.version=1,.runtime_nonce={1},
  .device_identity={2},.controller_boot=3,.controller_session=4,.flags=1,.controller_ns=2000*A16_MS}};
 struct actryn_request r={.runtime_nonce={1},.grant=5,.instance=6,.operation=7,.stream=8};
 struct actryn_event t=h; uint64_t lower=0;
 first7_begin(&g,&s); assert(first7_expect(&g,&r)<0); assert(!first7_event(&g,&h));
 assert(!first7_expect(&g,&r)); t.sequence=4; t.kind=ACTRYN_EVENT_WIRE|AW_STARTED;
 t.captured_ns=1200*A16_MS; t.status.state=ACTRYN_ACTIVE;
 t.status.operation_state=ACTRYN_OP_RUNNING; t.status.flags=9;
 t.status.grant=5; t.status.instance=6; t.status.operation=7; t.status.stream=8;
 t.status.controller_ns=2200*A16_MS; assert(!first7_event(&g,&t)); s=t.status;
 assert(first7_ready(&g,&s,1200*A16_MS,&lower)==0);
 assert(lower<g.started_ctl && actryn_slew(0,0,g.started_ctl,lower)<0);
 assert(first7_ready(&g,&s,1300*A16_MS,&lower)==0); /* 100 ms host sleep is insufficient. */
 assert(first7_ready(&g,&s,1301*A16_MS,&lower)==1);
 assert(!actryn_slew(0,0,g.started_ctl,lower));
 assert(first7_ready(&g,&s,60990*A16_MS,&lower)<0);
 assert(first7_ready(&g,&s,999*A16_MS,&lower)<0);
 for(unsigned i=0;i<9;i++) {
  struct actryn_status changed=s;
  switch(i) {
   case 0: changed.runtime_nonce[0]++; break; case 1: changed.device_identity[0]++; break;
   case 2: changed.controller_boot++; break; case 3: changed.controller_session++; break;
   case 4: changed.grant++; break; case 5: changed.instance++; break;
   case 6: changed.operation++; break; case 7: changed.stream++; break; case 8: changed.events_lost++; break;
  }
  assert(first7_ready(&g,&changed,1301*A16_MS,&lower)<0);
 }
 bad=g; bad.started=false; assert(!first7_ready(&bad,&s,1301*A16_MS,&lower));
 bad=g; bad.hello_ctl=UINT64_MAX; assert(first7_ready(&bad,&s,1301*A16_MS,&lower)<0);
 bad=g; assert(first7_event(&bad,&t)<0); /* duplicate receipt cannot renew eligibility */
 bad=g; t.sequence+=2; assert(first7_event(&bad,&t)<0);
 puts("PASS amendment7 actual-receipt epoch, conservative first sample and fixed bounds");
 return 0;
}
