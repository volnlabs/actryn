/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <stdio.h>
#include "capture/prefix.h"
int main(void)
{
 unsigned copied;
 for(unsigned accepted=0;accepted<=159;accepted++)
  assert(!a16_prefix(159,accepted,&copied) && copied==accepted);
 assert(a16_prefix(160,1,&copied)==A16_OVER_CAP && !copied);
 assert(a16_prefix(159,160,&copied)==A16_BAD_RETURN && !copied);
 assert(a16_prefix(159,-5,&copied)==A16_WRITE_ERROR && !copied);
 assert(a16_prefix(0,1,&copied)==A16_BAD_RETURN && !copied);
 puts("PASS ABI7 full159/every accepted prefix/zero/error/over-cap/invalid return");
 return 0;
}
