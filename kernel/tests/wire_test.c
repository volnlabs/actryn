// SPDX-License-Identifier: GPL-2.0-only
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include "../actryn_wire.h"
#include "../actryn_control.h"
#include "../include/uapi/linux/actryn_authority.h"
int main(int argc,char **argv)
{
 struct actryn_frame a = { .kind = 7, .boot = 2, .session = 3,
  .grant = 4, .operation = 5, .stream = 6, .sequence = 7,
  .transaction = 8, .expiry = 1000, .left = -100, .right = 100,
  .context = 1 }, b;
 unsigned char raw[ACTRYN_WIRE_SIZE], enc[ACTRYN_ENCODED_MAX];
 size_t n, cut;
 struct actryn_close slot={0}; actryn_u64 serial=0, old_revision;
 _Static_assert(sizeof(struct actryn_request) == 192, "request ABI");
 _Static_assert(sizeof(struct actryn_status) == 192, "status ABI");
 _Static_assert(sizeof(struct actryn_event) == 216, "event ABI");
 _Static_assert(offsetof(struct actryn_request, deadline_ns) == 80, "deadline ABI");
 assert(ACTRYN_IOCTL_REQUEST == 0xc0c04101UL);
 a.device[0] = 1; a.nonce[0] = 2;
 n = actryn_encode(&a, enc);
 if(argc==2 && !strcmp(argv[1],"--vector")) {
  for(cut=0;cut<n;cut++) printf("%02x",enc[cut]);
  puts(""); return 0;
 }
 assert(n <= sizeof(enc) && enc[n-1] == 0);
 assert(actryn_decode(enc, n-1, &b) == 0);
 assert(b.left == -100 && b.right == 100 && b.transaction == 8);
 for (cut = 0; cut < n-1; cut++) assert(actryn_decode(enc, cut, &b) < 0);
 enc[n/2] ^= 0x80;
 assert(actryn_decode(enc, n-1, &b) < 0);
 actryn_pack(&a, raw);
 assert(actryn_crc32((const unsigned char *)"123456789", 9) == 0xcbf43926U);
 assert(raw[0] == 2 && raw[112] == 0x9c && raw[115] == 0xff);
 assert(actryn_window(100, 100, 1000) < 0);
 assert(actryn_window(100, 110, 10) == 0);
 assert(actryn_window(~(actryn_u64)0-5, 4, 10) < 0);
 assert(actryn_slew(0, 101, 1000000000ULL, 1001000000ULL) < 0);
 assert(actryn_slew(0, 100, 1000000000ULL, 1100000000ULL) == 0);
 assert(actryn_slew(0, 101, 1000000000ULL, 9000000000ULL) < 0);
 assert(!actryn_merge_close(&slot,1,1,3,4,3,4,&serial));
 old_revision=slot.revision;
 assert(!actryn_merge_close(&slot,1,2,3,4,3,4,&serial));
 assert(slot.reason==1 && slot.revision==old_revision);
 assert(actryn_merge_close(&slot,2,3,2,4,3,4,&serial)==-1);
 assert(!actryn_merge_close(&slot,2,3,3,4,3,4,&serial));
 actryn_clear_close(&slot,old_revision); assert(slot.rank==2);
 assert(!actryn_merge_close(&slot,3,7,0,0,3,4,&serial));
 assert(!actryn_merge_close(&slot,1,2,3,4,3,4,&serial)); assert(slot.rank==3);
 assert(!actryn_merge_close(&slot,4,9,0,0,3,4,&serial)); assert(slot.rank==4);
 actryn_clear_close(&slot,slot.revision); assert(!slot.rank);
 serial=~(actryn_u64)0;
 assert(actryn_merge_close(&slot,1,1,3,4,3,4,&serial)==-2);
 actryn_clear_close(&slot,0); assert(slot.rank==3);
 assert(actryn_merge_close(&slot,4,9,0,0,3,4,&serial)==-2); assert(slot.rank==4);
 puts("wire: codec, CRC, truncation, ABI, deadline, slew and urgent closure checks passed");
 return 0;
}
