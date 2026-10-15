// SPDX-License-Identifier: GPL-2.0-only
#include "actryn_wire.h"
#ifdef __KERNEL__
#include <linux/string.h>
#else
#include <string.h>
#endif

static void put32(unsigned char *p, actryn_u32 v)
{ unsigned int i; for (i=0;i<4;i++) p[i]=(unsigned char)(v>>(8*i)); }
static void put64(unsigned char *p, actryn_u64 v)
{ unsigned int i; for (i=0;i<8;i++) p[i]=(unsigned char)(v>>(8*i)); }
static actryn_u32 get32(const unsigned char *p)
{ unsigned int i; actryn_u32 v=0; for (i=0;i<4;i++) v|=(actryn_u32)p[i]<<(8*i); return v; }
static actryn_u64 get64(const unsigned char *p)
{ unsigned int i; actryn_u64 v=0; for (i=0;i<8;i++) v|=(actryn_u64)p[i]<<(8*i); return v; }
actryn_u32 actryn_crc32(const unsigned char *p, size_t n)
{
 actryn_u32 c=0xffffffffU; unsigned int i;
 while (n--) { c^=*p++; for(i=0;i<8;i++) c=(c>>1)^((0U-(c&1U))&0xedb88320U); }
 return c^0xffffffffU;
}
void actryn_pack(const struct actryn_frame *f, unsigned char p[ACTRYN_WIRE_SIZE])
{
 memset(p,0,ACTRYN_WIRE_SIZE); p[0]=2; p[2]=(unsigned char)f->kind;
 memcpy(p+8,f->device,16); put64(p+24,f->boot); put64(p+32,f->session);
 memcpy(p+40,f->nonce,16); put64(p+56,f->grant); put64(p+64,f->operation);
 put64(p+72,f->stream); put64(p+80,f->sequence); put64(p+88,f->transaction);
 put64(p+96,f->expiry); put64(p+104,f->controller_ns);
 put32(p+112,(actryn_u32)f->left); put32(p+116,(actryn_u32)f->right);
 put64(p+120,(actryn_u64)f->left_encoder); put64(p+128,(actryn_u64)f->right_encoder);
 put64(p+136,f->context); put32(p+144,f->status);
 put32(p+152,actryn_crc32(p,152));
}
size_t actryn_encode(const struct actryn_frame *f, unsigned char out[ACTRYN_ENCODED_MAX])
{
 unsigned char p[ACTRYN_WIRE_SIZE]; size_t i, n=1, code_at=0; unsigned int code=1;
 actryn_pack(f,p);
 for(i=0;i<sizeof(p);i++) {
  if(p[i]) { out[n++]=p[i]; code++; }
  else { out[code_at]=(unsigned char)code; code_at=n++; code=1; }
 }
 out[code_at]=(unsigned char)code; out[n++]=0; return n;
}
int actryn_decode(const unsigned char *p, size_t n, struct actryn_frame *f)
{
 unsigned char raw[ACTRYN_WIRE_SIZE]; size_t i=0,o=0,j; unsigned int code;
 if(!n || n>=ACTRYN_ENCODED_MAX) return -1;
 while(i<n) {
  code=p[i++]; if(!code || i+code-1>n) return -1;
  for(j=1;j<code;j++) { if(o>=sizeof(raw)||!p[i]) return -1; raw[o++]=p[i++]; }
  if(code<255 && i<n) { if(o>=sizeof(raw)) return -1; raw[o++]=0; }
 }
 if(o!=sizeof(raw)||raw[0]!=2||raw[1]||raw[3]||raw[2]<1||raw[2]>12||
    get32(raw+4)||get32(raw+148)||get32(raw+152)!=actryn_crc32(raw,152)) return -1;
 memset(f,0,sizeof(*f)); f->kind=raw[2]; memcpy(f->device,raw+8,16);
 f->boot=get64(raw+24); f->session=get64(raw+32); memcpy(f->nonce,raw+40,16);
 f->grant=get64(raw+56); f->operation=get64(raw+64); f->stream=get64(raw+72);
 f->sequence=get64(raw+80); f->transaction=get64(raw+88); f->expiry=get64(raw+96);
 f->controller_ns=get64(raw+104); f->left=(actryn_s32)get32(raw+112);
 f->right=(actryn_s32)get32(raw+116); f->left_encoder=(actryn_s64)get64(raw+120);
 f->right_encoder=(actryn_s64)get64(raw+128); f->context=get64(raw+136);
 f->status=get32(raw+144); return f->status<=8?0:-1;
}
int actryn_window(actryn_u64 now, actryn_u64 deadline, actryn_u64 max_delta)
{ return deadline>now && deadline-now<=max_delta ? 0 : -1; }
int actryn_slew(actryn_s32 previous, actryn_s32 next, actryn_u64 applied_ns,
               actryn_u64 now_ns)
{
 actryn_s64 delta=(actryn_s64)next-previous; actryn_u64 dt;
 if(next < -200 || next > 200 || now_ns<applied_ns) return -1;
 if(delta<0) delta=-delta;
 dt=now_ns-applied_ns; if(dt>100000000ULL) dt=100000000ULL;
 return (actryn_u64)delta<=dt/1000000ULL?0:-1;
}
