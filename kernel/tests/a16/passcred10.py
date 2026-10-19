# SPDX-License-Identifier: GPL-2.0-only
"""Numbered gateway derivative; original comparison sources remain immutable."""
import hashlib

BASE_SHA256 = '5ca065e12366c020987fb6670fed0dba7661b50f51f7198c29e5cbd0f066803c'
SOCKET = 'socket(AF_UNIX,SOCK_SEQPACKET|SOCK_NONBLOCK|SOCK_CLOEXEC,0)'


def render(source):
    if hashlib.sha256(source.encode()).hexdigest() != BASE_SHA256:
        raise ValueError('exact frozen gateway source required')
    old = ('assert(!bind(g.listener,(struct sockaddr *)&addr,sizeof(addr))); '
           'assert(!listen(g.listener,CLIENTS));')
    marker = '#ifndef A16_GATEWAY_TEST'
    if source.count(old) != 1 or source.count(marker) != 1:
        raise ValueError('frozen listener edit count differs')
    helper = ('static inline void enable_listener_credentials(int fd)\n{\n'
              ' int one=1; assert(!setsockopt(fd,SOL_SOCKET,SO_PASSCRED,&one,sizeof(one)));\n'
              '}\n')
    new = ('assert(!bind(g.listener,(struct sockaddr *)&addr,sizeof(addr))); '
           'enable_listener_credentials(g.listener); assert(!listen(g.listener,CLIENTS));')
    return source.replace(old, new).replace(marker, helper + marker)
