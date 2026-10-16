/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef A16_PREFIX_H
#define A16_PREFIX_H
#define A16_FRAME_MAX 158U
#define A16_OVER_CAP 1U
#define A16_BAD_RETURN 2U
#define A16_WRITE_ERROR 4U
#define A16_READ_FAILURE 8U
static inline unsigned a16_prefix(unsigned long long requested, long long result,
                                  unsigned *copied)
{
 unsigned flags=0;
 *copied=0;
 if(requested>A16_FRAME_MAX) flags|=A16_OVER_CAP;
 if(result<0) flags|=A16_WRITE_ERROR;
 else if((unsigned long long)result>requested) flags|=A16_BAD_RETURN;
 if(!flags) *copied=(unsigned)result;
 return flags;
}
#endif
