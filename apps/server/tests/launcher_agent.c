/* Reviewed disposable software test entrypoint, packaged through the real OCI importer. */
#include <assert.h>
#include <stdio.h>
#include <unistd.h>
int main(void) {
    assert(getuid()==65532 && getgid()==65532);
    pid_t child=fork();assert(child>=0);
    if(child==0){sleep(30);return 0;}
    puts("AGENT_STARTED");fflush(stdout);sleep(30);return 0;
}
