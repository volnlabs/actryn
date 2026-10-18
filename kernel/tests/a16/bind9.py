# SPDX-License-Identifier: GPL-2.0-only
"""Pure diagnostic9 workload derivation; never builds, writes or runs anything."""
import hashlib

BASE_SHA256='c94c29729272ef19ed94d7777ea0fd3ddea5b162b44344eefa1e53c550ef6b32'

REPLY = r'''  assert(!connect(fd,(struct sockaddr *)&addr,sizeof(addr)));
  struct a16_reply reply=exchange(fd,&c);
  if(reply.error) {
   char trial_json[16];
   if(!strcmp(scope,"trial_setup")) snprintf(trial_json,sizeof(trial_json),"%u",trial);
   else strcpy(trial_json,"null");
   emit("{\"type\":\"bind_failure\",\"diagnostic\":9,\"phase\":\"userspace_bind_reply\",\"scope\":\"%s\",\"trial\":%s,\"role\":%u,\"reply_error\":%d}\n",
    scope,trial_json,role,(int)reply.error);
  }
  assert(!reply.error);'''


def render(source):
    """Return new C text only for the exact frozen amendment7/C03 workload."""
    if hashlib.sha256(source.encode()).hexdigest()!=BASE_SHA256:
        raise ValueError('exact frozen amendment7/C03 workload required')
    changes=(
        ('static int bind_role(unsigned role)', 'static int bind_role(unsigned role,const char *scope)'),
        ('  assert(!connect(fd,(struct sockaddr *)&addr,sizeof(addr))); assert(!exchange(fd,&c).error);', REPLY),
        (' int admin=bind_role(ACTRYN_ADMIN),runtime=bind_role(ACTRYN_RUNTIME),events=bind_role(ACTRYN_EVENTS);\n'
         ' int acquisition=bind_role(ACTRYN_ACQUISITION);',
         ' int admin=bind_role(ACTRYN_ADMIN,"trial_setup"),runtime=bind_role(ACTRYN_RUNTIME,"trial_setup"),events=bind_role(ACTRYN_EVENTS,"trial_setup");\n'
         ' int acquisition=bind_role(ACTRYN_ACQUISITION,"trial_setup");'),
        (' admin=bind_role(ACTRYN_ADMIN); events=bind_role(ACTRYN_EVENTS);',
         ' admin=bind_role(ACTRYN_ADMIN,"parent_setup"); events=bind_role(ACTRYN_EVENTS,"parent_setup");'))
    for old,new in changes:
        if source.count(old)!=1:
            raise ValueError('frozen bind9 edit count differs')
        source=source.replace(old,new)
    return source
