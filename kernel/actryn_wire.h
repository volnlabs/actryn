/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef ACTRYN_WIRE_H
#define ACTRYN_WIRE_H
#ifdef __KERNEL__
#include <linux/types.h>
typedef u64 actryn_u64;
typedef u32 actryn_u32;
typedef s64 actryn_s64;
typedef s32 actryn_s32;
#else
#include <stdint.h>
#include <stddef.h>
typedef uint64_t actryn_u64;
typedef uint32_t actryn_u32;
typedef int64_t actryn_s64;
typedef int32_t actryn_s32;
#endif
#define ACTRYN_WIRE_SIZE 156
#define ACTRYN_ENCODED_MAX 158
enum actryn_wire_kind { AW_HELLO=1, AW_HELLO_ACK, AW_REARM, AW_BASELINE,
 AW_START, AW_STARTED, AW_SAMPLE, AW_APPLIED, AW_QUIESCE, AW_QUIESCED,
 AW_FAULT, AW_OBSERVATION };
struct actryn_frame {
 unsigned short kind;
 unsigned char device[16], nonce[16];
 actryn_u64 boot, session, grant, operation, stream, sequence, transaction;
 actryn_u64 expiry, controller_ns;
 actryn_s32 left, right;
 actryn_s64 left_encoder, right_encoder;
 actryn_u64 context;
 actryn_u32 status;
};
actryn_u32 actryn_crc32(const unsigned char *p, size_t len);
void actryn_pack(const struct actryn_frame *f, unsigned char out[ACTRYN_WIRE_SIZE]);
size_t actryn_encode(const struct actryn_frame *f, unsigned char out[ACTRYN_ENCODED_MAX]);
int actryn_decode(const unsigned char *p, size_t n, struct actryn_frame *f);
int actryn_window(actryn_u64 now, actryn_u64 deadline, actryn_u64 max_delta);
int actryn_slew(actryn_s32 previous, actryn_s32 next, actryn_u64 applied_ns,
               actryn_u64 now_ns);
#endif
