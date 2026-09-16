# Kbuild reads this through DKMS (make -C <kernel build> M=<this dir>). A plain
# `make` here builds against the running kernel for development.
obj-m := imac5k_xhci_d0.o

KDIR ?= /usr/lib/modules/$(shell uname -r)/build

all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) modules

clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
