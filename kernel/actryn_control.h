/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef ACTRYN_CONTROL_H
#define ACTRYN_CONTROL_H
#include "actryn_wire.h"
struct actryn_close {
 actryn_u64 revision, grant, operation;
 actryn_u32 rank, reason;
};
/* Caller serializes this fixed control slot independently of authority writes. */
static inline int actryn_merge_close(struct actryn_close *slot,
 actryn_u32 rank,actryn_u32 reason,actryn_u64 grant,actryn_u64 operation,
 actryn_u64 current_grant,actryn_u64 current_operation,actryn_u64 *serial)
{
 if(rank<3 && (grant!=current_grant || (rank==1 && operation!=current_operation))) return -1;
 if(rank>slot->rank) {
  if(*serial==~(actryn_u64)0) {
   slot->rank=rank>=3?rank:3; slot->reason=rank==4?reason:7;
   slot->revision=0; return -2;
  }
  slot->rank=rank; slot->reason=reason; slot->grant=grant;
  slot->operation=operation; slot->revision=++*serial;
 }
 return 0;
}
static inline void actryn_clear_close(struct actryn_close *slot,actryn_u64 processed_revision)
{ if(processed_revision && slot->revision==processed_revision) slot->rank=0; }
#endif
