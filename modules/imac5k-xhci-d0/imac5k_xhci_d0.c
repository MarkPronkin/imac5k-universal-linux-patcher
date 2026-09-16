// SPDX-License-Identifier: GPL-2.0
/*
 * Stop Linux from running Apple's power methods on the Retina 5K iMac's PCH
 * USB 3 controller, while still letting the controller sleep and wake.
 *
 * Apple's \_SB.PCI0.XHC1._PS3 (SSDT "Xhci") sets D3HE, which lets the PCH
 * power-gate the controller in D3hot, and then goes on accessing the
 * controller's config space. On the iMac18,3 the first D3 entry of a boot
 * survives that; the second resets the machine at the first access after
 * D3HE is set. That is why every second suspend of a boot rebooted it.
 *
 * Holding the controller in D0 avoided the reset but lost USB wake: the
 * controller raises PME only from D3. Instead this clears the ACPI companion's
 * power_manageable flag. The PCI core then puts the controller into D3hot
 * natively (PMCSR, target state from its PME support) and back to D0 on
 * resume, without evaluating _PS3 or _PS0, so D3HE is never set. Wakeup is
 * separate: _PRW's GPE 0x6D is still armed through the ACPI wakeup path.
 */
#include <linux/acpi.h>
#include <linux/dmi.h>
#include <linux/module.h>
#include <linux/pci.h>
#include <linux/pm_runtime.h>

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Keep Apple's XHC1._PS3/_PS0 off the Retina 5K iMac's PCH xHCI");

static bool force;
module_param(force, bool, 0444);
MODULE_PARM_DESC(force, "also bind on an Apple model not yet verified to need this");

static bool acpi_pm_skipped;
module_param(acpi_pm_skipped, bool, 0444);
MODULE_PARM_DESC(acpi_pm_skipped, "Y while XHC1's ACPI power methods are kept from running");

/* Models whose second XHC1._PS3 was observed to reset the machine. */
static const struct dmi_system_id affected[] = {
	{ .matches = { DMI_MATCH(DMI_SYS_VENDOR, "Apple Inc."),
		       DMI_MATCH(DMI_PRODUCT_NAME, "iMac18,3") } },
	{ }
};

static struct pci_dev *xhci;
static struct acpi_device *companion;

static int __init xhci_acpi_pm_init(void)
{
	int ret = -ENODEV;

	if (!dmi_check_system(affected) && !(force && dmi_match(DMI_SYS_VENDOR, "Apple Inc.")))
		return -ENODEV;

	xhci = pci_get_domain_bus_and_slot(0, 0, PCI_DEVFN(0x14, 0));
	if (!xhci || xhci->vendor != PCI_VENDOR_ID_INTEL ||
	    xhci->class != PCI_CLASS_SERIAL_USB_XHCI || !xhci->pm_cap)
		goto fail;
	companion = ACPI_COMPANION(&xhci->dev);
	if (!companion || !acpi_has_method(companion->handle, "_PS3") ||
	    !companion->flags.power_manageable)
		goto fail;

	/*
	 * Change the flag only in D0, with runtime suspend held off, so the
	 * ACPI and PCI views of the power state agree when it takes effect.
	 */
	pm_runtime_get_sync(&xhci->dev);
	if (xhci->current_state != PCI_D0 || companion->power.state != ACPI_STATE_D0) {
		pci_err(xhci, "not in D0; leaving its ACPI power methods alone\n");
		pm_runtime_put(&xhci->dev);
		ret = -EIO;
		goto fail;
	}
	companion->flags.power_manageable = 0;
	WRITE_ONCE(acpi_pm_skipped, true);
	pm_runtime_put(&xhci->dev);
	pci_info(xhci, "native D3hot only: Apple's XHC1._PS3 resets this iMac on a second D3 entry\n");
	return 0;

fail:
	pci_dev_put(xhci);
	return ret;
}

static void __exit xhci_acpi_pm_exit(void)
{
	pm_runtime_get_sync(&xhci->dev);
	companion->flags.power_manageable = 1;
	WRITE_ONCE(acpi_pm_skipped, false);
	pm_runtime_put(&xhci->dev);
	pci_info(xhci, "ACPI power methods restored\n");
	pci_dev_put(xhci);
}

module_init(xhci_acpi_pm_init);
module_exit(xhci_acpi_pm_exit);
