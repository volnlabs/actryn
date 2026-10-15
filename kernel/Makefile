ifneq ($(KERNELRELEASE),)
ifneq ($(filter y m,$(CONFIG_ACTRYN_AUTHORITY)),)
obj-$(CONFIG_ACTRYN_AUTHORITY) += actryn_authority.o
else
obj-m += actryn_authority.o
endif
actryn_authority-y := actryn_driver.o actryn_wire.o
ccflags-y += -I$(src)/include/uapi
ifneq ($(filter y m,$(CONFIG_ACTRYN_AUTHORITY_KUNIT_TEST)),)
ccflags-y += -DACTRYN_KUNIT_ENABLED
actryn_authority-y += actryn_kunit.o
endif
else
KDIR ?= /lib/modules/$(shell uname -r)/build
.PHONY: all clean test
all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) modules
clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
test:
	sh tests/run.sh
endif
