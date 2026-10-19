/* SPDX-License-Identifier: GPL-2.0-only */
/* Force the precise accepted-but-not-configured window, without a UART. */
#define A16_GATEWAY_TEST
#include "passcred10-gateway.c"

int main(void)
{
 struct gateway g={.ownerfd=-1};
 const unsigned roles[]={ACTRYN_ADMIN,ACTRYN_RUNTIME,ACTRYN_EVENTS,ACTRYN_ACQUISITION};
 g.epoll=epoll_create1(EPOLL_CLOEXEC); assert(g.epoll>=0); a16_init(&g.engine);
 for(unsigned i=0;i<sizeof(roles)/sizeof(roles[0]);i++) {
  struct sockaddr_un address={.sun_family=AF_UNIX}; struct ucred peer;
  struct a16_command sent={.action=A16_BIND,.request={.version=1,.opcode=ACTRYN_BIND,.role=roles[i]}},got;
  struct client c={.fd=-1}; int listener=socket(AF_UNIX,SOCK_SEQPACKET|SOCK_NONBLOCK|SOCK_CLOEXEC,0),client,accepted,one=1;
  assert(listener>=0);
  snprintf(address.sun_path+1,sizeof(address.sun_path)-1,"actryn-passcred10-%ld-%u",(long)getpid(),i);
  if(bind(listener,(struct sockaddr *)&address,sizeof(address))) { perror("passcred10 bind"); return 2; }
  enable_listener_credentials(listener); assert(!listen(listener,1));
  client=socket(AF_UNIX,SOCK_SEQPACKET|SOCK_CLOEXEC,0); assert(client>=0);
  assert(!connect(client,(struct sockaddr *)&address,sizeof(address)));
  accepted=accept4(listener,NULL,NULL,SOCK_NONBLOCK|SOCK_CLOEXEC); assert(accepted>=0);
  /* The sender runs while the gateway is between accept4 and setsockopt. */
  assert(send(client,&sent,sizeof(sent),MSG_NOSIGNAL)==sizeof(sent));
  assert(!setsockopt(accepted,SOL_SOCKET,SO_PASSCRED,&one,sizeof(one)));
  assert(!receive_command(accepted,&got,&peer)); dispatch(&g,&c,&got,&peer);
  if(peer.pid!=getpid() || peer.uid!=geteuid() || peer.gid!=getegid() || c.reply.error) {
   fprintf(stderr,"BIND role=%u peer=%ld/%lu/%lu expected=%ld/%lu/%lu error=%d\n",
    roles[i],(long)peer.pid,(unsigned long)peer.uid,(unsigned long)peer.gid,
    (long)getpid(),(unsigned long)geteuid(),(unsigned long)getegid(),c.reply.error);
   return 1;
  }
  assert(c.role==roles[i]); close(accepted); close(client); close(listener);
 }
 close(g.ownerfd); close(g.epoll);
 puts("PASS all four BIND roles preserve credentials before accepted-socket configuration");
 return 0;
}
