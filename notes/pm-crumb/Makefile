obj-m += imac_pm_crumb.o

KDIR ?= /usr/lib/modules/$(shell uname -r)/build
# ACPICA's internal headers are not packaged with the kernel headers; use the
# matching 7.2.3 source tree the 5K driver build already unpacked.
ACPICA ?= /home/markpronkin/.cache/kernel-5k-build/linux-7.2.3/drivers/acpi/acpica
ccflags-y += -I$(ACPICA) -D_LINUX -DBUILDING_ACPICA -DACPI_DEBUG_OUTPUT

all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) W=1 modules

clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
