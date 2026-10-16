/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef A16_FIRST_SAMPLE7_H
#define A16_FIRST_SAMPLE7_H
#include "engine.h"
#include <string.h>

/* Test workload eligibility only. The authority still validates every request. */
struct first_sample7 {
 bool enabled,hello,started,expect_start;
 struct actryn_status epoch;
 struct actryn_request operation;
 uint64_t hello_host,hello_ctl,started_host,started_ctl,hello_sequence,started_sequence;
 uint64_t last_event;
 uint32_t lost;
};
static bool first7_epoch(const struct actryn_status *a,const struct actryn_status *b)
{
 return !memcmp(a->runtime_nonce,b->runtime_nonce,16) &&
  !memcmp(a->device_identity,b->device_identity,16) &&
  a->controller_boot==b->controller_boot && a->controller_session==b->controller_session;
}
static bool first7_operation(const struct first_sample7 *g,const struct actryn_status *s)
{
 return first7_epoch(&g->epoch,s) && s->grant==g->operation.grant &&
  s->instance==g->operation.instance && s->operation==g->operation.operation &&
  s->stream==g->operation.stream;
}
static void first7_begin(struct first_sample7 *g,const struct actryn_status *s)
{ *g=(struct first_sample7){.enabled=true,.epoch=*s,.lost=s->events_lost}; }
static int first7_expect(struct first_sample7 *g,const struct actryn_request *r)
{
 if(!g->hello || g->expect_start || !r->grant || !r->instance || !r->operation || !r->stream ||
    memcmp(r->runtime_nonce,g->epoch.runtime_nonce,16)) return -1;
 g->operation=*r; g->expect_start=true; return 0;
}
static int first7_event(struct first_sample7 *g,const struct actryn_event *v)
{
 const struct actryn_status *s=&v->status;
 if(!g->enabled || memcmp(s->runtime_nonce,g->epoch.runtime_nonce,16)) return 0;
 if(s->events_lost!=g->lost || !v->sequence ||
    (g->last_event && (g->last_event==UINT64_MAX || v->sequence!=g->last_event+1))) return -1;
 g->last_event=v->sequence;
 if(s->state>=ACTRYN_FAULT_LATCHED) return -1;
 if(v->kind==(ACTRYN_EVENT_WIRE|AW_HELLO_ACK)) {
  static const unsigned char zero[16];
  if(g->hello || s->state!=ACTRYN_INHIBITED || !(s->flags&ACTRYN_STATUS_HANDSHAKEN) ||
     !s->controller_boot || !s->controller_session || !memcmp(s->device_identity,zero,16) ||
     v->captured_ns<10*A16_MS) return -1;
  g->epoch=*s; g->hello=true; g->hello_host=v->captured_ns; g->hello_ctl=s->controller_ns;
  g->hello_sequence=v->sequence;
 } else if(v->kind==(ACTRYN_EVENT_WIRE|AW_STARTED)) {
  if(!g->hello || !g->expect_start || g->started || !first7_operation(g,s) ||
     s->state!=ACTRYN_ACTIVE || s->operation_state!=ACTRYN_OP_RUNNING ||
     (s->flags&9)!=9 || s->sequence || s->left_permille || s->right_permille ||
     v->captured_ns<g->hello_host || s->controller_ns<g->hello_ctl) return -1;
  g->started=true; g->started_host=v->captured_ns; g->started_ctl=s->controller_ns;
  g->started_sequence=v->sequence;
 }
 return 0;
}
/* Identical outward rounding to robot-runtime Mapping::controller_lower.
 * HELLO capture is no earlier than the authority's private mapping anchor. */
static int first7_lower(const struct first_sample7 *g,uint64_t now,uint64_t *lower)
{
 uint64_t age,elapsed,drift,sum;
 if(!g->hello || now<g->hello_host) return -1;
 elapsed=now-g->hello_host;
 if(elapsed>UINT64_MAX-10*A16_MS) return -1;
 age=elapsed+10*A16_MS;
 if(age>=60000*A16_MS || g->hello_ctl>UINT64_MAX-elapsed) return -1;
 drift=age/10000+(age%10000!=0); sum=g->hello_ctl+elapsed;
 if(sum<drift) return -1;
 *lower=sum-drift; return 0;
}
static int first7_ready(const struct first_sample7 *g,const struct actryn_status *s,
                        uint64_t now,uint64_t *lower)
{
 if(!g->enabled || !g->hello || !g->expect_start || !first7_operation(g,s) ||
    s->state!=ACTRYN_ACTIVE || s->operation_state!=ACTRYN_OP_RUNNING ||
    (s->flags&9)!=9 || s->events_lost!=g->lost || first7_lower(g,now,lower)) return -1;
 if(!g->started) return 0;
 return *lower>=g->started_ctl && *lower-g->started_ctl>=100*A16_MS;
}
#endif
