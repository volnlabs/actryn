/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef ACTRYN_A16_ENGINE_H
#define ACTRYN_A16_ENGINE_H
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include "../../include/uapi/linux/actryn_authority.h"
#include "../../actryn_wire.h"
#include "../../actryn_control.h"
#define A16_MS UINT64_C(1000000)
#define A16_EVENTS 256
#define A16_RX 32
struct a16_engine {
 struct actryn_status status;
 struct actryn_request observation,allocation,sample,tx_observation;
 struct actryn_frame tx_frame,awaited,mailbox,rx[A16_RX];
 struct actryn_event events[A16_EVENTS];
 struct actryn_close close;
 uint64_t now,grant_deadline,health_deadline,operation_deadline,close_deadline;
 uint64_t receipt_deadline,sync_deadline,resync_after,hello_sent,map_host,map_ctl;
 uint64_t tx_deadline,awaited_deadline,last_applied_ctl,observation_sequence;
 uint64_t next_operation,next_transaction,event_sequence,close_serial,parser_started;
 unsigned event_head,event_tail,event_count,rx_head,rx_tail,rx_count;
 unsigned char tx[ACTRYN_ENCODED_MAX+1],parser[ACTRYN_ENCODED_MAX];
 size_t tx_len,tx_off,parser_len;
 bool owner,handshaken,authorized,tx_busy,awaiting,mailbox_valid,quiesce,discard;
};
typedef ptrdiff_t (*a16_writer)(void *,const unsigned char *,size_t);
void a16_init(struct a16_engine *e);
void a16_time(struct a16_engine *e,uint64_t now);
void a16_owner_lost(struct a16_engine *e);
int a16_request(struct a16_engine *e,unsigned role,struct actryn_request *r,
 const unsigned char fresh_nonce[16]);
void a16_receive(struct a16_engine *e,const unsigned char *p,size_t n);
void a16_tick(struct a16_engine *e,a16_writer writer,void *opaque);
int a16_event(struct a16_engine *e,struct actryn_event *event);
struct actryn_status a16_status(struct a16_engine *e);
#endif
