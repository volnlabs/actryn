/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef ACTRYN_A16_PROTOCOL_H
#define ACTRYN_A16_PROTOCOL_H
#include "engine.h"
#define A16_SOCKET "/run/actryn-a16.sock"
enum a16_action { A16_BIND=1,A16_REQUEST,A16_STATUS,A16_EVENT };
struct a16_command { uint32_t action,reserved; struct actryn_request request; };
struct a16_reply { int32_t error; uint32_t reserved;
 union { struct actryn_request request; struct actryn_status status; struct actryn_event event; } data; };
_Static_assert(sizeof(struct a16_command)==200,"fixed A16 command ABI");
_Static_assert(sizeof(struct a16_reply)==224,"fixed A16 reply ABI");
#endif
