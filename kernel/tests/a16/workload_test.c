/* SPDX-License-Identifier: GPL-2.0-only */
#define main a16_workload_main
#include "workload.c"
#undef main
int main(void)
{
 struct actryn_status s={.state=2,.operation_state=4,.reason=1,.flags=9,.grant=3,.operation=4,.stream=5};
 struct actryn_request r={.opcode=9,.grant=3,.operation=4,.stream=5};
 assert(terminal_matches(&s,&r));
 r.opcode=10; assert(!terminal_matches(&s,&r));
 s.reason=2; assert(terminal_matches(&s,&r));
 for(unsigned i=0;i<10;i++) {
  struct actryn_status bad=s;
  switch(i) {
   case 0: bad.state=1; break;
   case 1: bad.reason=3; break;
   case 2: bad.flags=1; break;
   case 3: bad.left_permille=1; break;
   case 4: bad.right_permille=-1; break;
   case 5: bad.grant++; break;
   case 6: bad.operation++; break;
   case 7: bad.stream++; break;
   case 8: bad.runtime_nonce[0]=1; break;
   case 9: bad.flags=8; break;
  }
  assert(!terminal_matches(&bad,&r));
 }
 puts("PASS fixed A16 normal/cancel terminal contract"); return 0;
}
