/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <stdio.h>
#include "prefix.h"
int main(void)
{
 unsigned n;
 assert(a16_prefix(158,158,&n)==0 && n==158);
 assert(a16_prefix(158,3,&n)==0 && n==3);
 assert(a16_prefix(1,1,&n)==0 && n==1);
 assert(a16_prefix(158,0,&n)==0 && n==0);
 assert(a16_prefix(158,-5,&n)==A16_WRITE_ERROR && n==0);
 assert(a16_prefix(3,4,&n)==A16_BAD_RETURN && n==0);
 assert(a16_prefix(159,1,&n)==A16_OVER_CAP && n==0);
 assert(a16_prefix(0,1,&n)==A16_BAD_RETURN && n==0);
 puts("PASS accepted prefix, short/zero/error/over-cap/invalid-return boundaries");
 return 0;
}
