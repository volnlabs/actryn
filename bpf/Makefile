CLANG ?= clang
ARCH_INCLUDE ?= /usr/include/x86_64-linux-gnu

observer.bpf.o: observer.bpf.c
	$(CLANG) -target bpfel -D__TARGET_ARCH_x86 -O2 -g -Wall -Werror -I$(ARCH_INCLUDE) -c $< -o $@

.PHONY: clean
clean:
	rm -f observer.bpf.o
