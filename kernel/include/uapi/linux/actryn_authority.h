/* SPDX-License-Identifier: GPL-2.0-only WITH Linux-syscall-note */
#ifndef _UAPI_LINUX_ACTRYN_AUTHORITY_H
#define _UAPI_LINUX_ACTRYN_AUTHORITY_H
#include <linux/types.h>
#include <linux/ioctl.h>

#define ACTRYN_UAPI_VERSION 1
#define ACTRYN_DEVICE "/dev/actryn-authority"
#define ACTRYN_EVENT_REQUEST 0x10000U
#define ACTRYN_EVENT_WIRE 0x20000U
#define ACTRYN_EVENT_CLOSURE 0x30000U
#define ACTRYN_STATUS_HANDSHAKEN 1U
#define ACTRYN_STATUS_TX_STARTED 2U
#define ACTRYN_STATUS_AWAITING 4U
#define ACTRYN_STATUS_GRANT_AUTHORIZED 8U
enum actryn_role { ACTRYN_ADMIN = 1, ACTRYN_RUNTIME, ACTRYN_ACQUISITION, ACTRYN_EVENTS };
enum actryn_opcode {
 ACTRYN_BIND = 1, ACTRYN_HANDSHAKE, ACTRYN_REARM, ACTRYN_GRANT,
 ACTRYN_ACTIVATE, ACTRYN_OBSERVE, ACTRYN_START, ACTRYN_SAMPLE,
 ACTRYN_FINISH, ACTRYN_CANCEL, ACTRYN_REVOKE, ACTRYN_RECOVER,
 ACTRYN_HEALTH, ACTRYN_ALLOCATE,
};
enum actryn_state { ACTRYN_INHIBITED, ACTRYN_READY, ACTRYN_ACTIVE,
 ACTRYN_REVOKING, ACTRYN_FAULT_LATCHED, ACTRYN_DETACHED };
enum actryn_operation_state { ACTRYN_OP_NONE, ACTRYN_OP_STARTING,
 ACTRYN_OP_RUNNING, ACTRYN_OP_CLOSING, ACTRYN_OP_RECONCILED,
 ACTRYN_OP_UNKNOWN, ACTRYN_OP_ALLOCATED };
enum actryn_reason { ACTRYN_REASON_NONE, ACTRYN_SKILL_FINISHED,
 ACTRYN_CANCELLED, ACTRYN_GRANT_REVOKED, ACTRYN_EXPIRED,
 ACTRYN_OWNER_LOST, ACTRYN_TRANSPORT, ACTRYN_PROTOCOL,
 ACTRYN_EVIDENCE_LOST, ACTRYN_DEVICE_REMOVED };

/* All unused fields are zero. Times are absolute CLOCK_BOOTTIME nanoseconds. */
struct actryn_request {
 __u32 version, opcode, flags, role;
 __u8 runtime_nonce[16];
 __u64 grant, instance, operation, stream, sequence, transaction;
 __u64 deadline_ns, observation, acquired_earliest_ns, acquired_latest_ns;
 __u64 valid_until_ns, context_revision;
 __s32 left_permille, right_permille;
 __u32 reason, reserved0;
 __u8 digest[32];
 __u8 reserved[16];
};

struct actryn_status {
 __u32 version, state, operation_state, reserved0;
 __u8 runtime_nonce[16], device_identity[16];
 __u64 controller_boot, controller_session, grant, instance;
 __u64 operation, stream, sequence, transaction, deadline_ns, now_ns;
 __u64 observation, context_revision, controller_ns;
 __s64 left_encoder, right_encoder;
 __s32 left_permille, right_permille;
 __u32 reason, events_lost, flags, reserved1;
};

/* read() returns complete event records; poll() signals records or detach. */
struct actryn_event {
 __u64 sequence, captured_ns;
 __u32 kind, reserved;
 struct actryn_status status;
};
#define ACTRYN_IOCTL_REQUEST _IOWR('A', 1, struct actryn_request)
#define ACTRYN_IOCTL_STATUS _IOR('A', 2, struct actryn_status)
#endif
