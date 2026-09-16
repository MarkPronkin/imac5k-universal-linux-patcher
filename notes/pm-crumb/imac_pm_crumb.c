// SPDX-License-Identifier: GPL-2.0
/*
 * Temporary iMac18,3 diagnostic: leave the last suspend/resume step in the
 * battery-backed RTC, the only storage that has survived the second-sleep
 * reset (the boot-mapped trace buffer did not, and a 20 s EFI timer never ran).
 *
 * Every PM step (device callback start/end, suspend phase begin/end, PM
 * notifier, helper marker) overwrites the RTC date/time registers with
 *
 *   v = dev + 1021 * (phase + 16 * (cycle + 3 * kind))
 *
 * as year 2000..2024, month, day 1..28 and hour, with minutes and seconds set
 * to zero. The next boot's "PM: RTC time" line therefore names the step, and
 * its minutes:seconds show how long passed until that boot read the clock.
 *
 * While the RTC alarm interrupt is disabled, three alarm registers add:
 *   0x01  heartbeat: half-seconds since the current cycle began (255 = more)
 *   0x03  hash of the ACPI method most recently begun since that PM step
 *   0x05  ACPI method/region events since that PM step (255 = more)
 *
 * A debugfs log keeps every step, method and operation-region access of
 * completed cycles, so a later reset can be mapped onto the same sequence.
 * No device power state is changed; nothing panics or reboots. Unload writes
 * the system time back to the RTC and restores the three alarm registers.
 *
 * Side effect: with the RTC marked unusable, s2idle time is not added to the
 * system clock (this Mac measures sleep with the RTC), so wall time falls
 * behind by each real sleep until time sync corrects it.
 */
#include <linux/debugfs.h>
#include <linux/dmi.h>
#include <linux/hrtimer.h>
#include <linux/kprobes.h>
#include <linux/mc146818rtc.h>
#include <linux/module.h>
#include <linux/pci.h>
#include <linux/pm-trace.h>
#include <linux/rtc.h>
#include <linux/seq_file.h>
#include <linux/suspend.h>
#include <linux/timekeeping.h>
#include <linux/tracepoint.h>
#include <linux/vmalloc.h>
#include <acpi/acpi.h>
#include "accommon.h"

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("RTC breadcrumbs for an iMac18,3 suspend reset");

#define DEVHASH 1021
#define NPHASE 16
#define NCYCLE 3
#define PH_MISC 15		/* notifier (dev < 16), marker (16..), rare phases (1000..) */
#define MISC_MARKER 16
#define MISC_CONSOLE 1000
#define MISC_ACPI_SUSPEND 1001
#define MISC_CPU_OFF 1002
#define MISC_CPU_ON 1003
#define MISC_OTHER 1004
#define LOG_ENTRIES 131072
#define REGION_LOG_LIMIT 2048	/* region accesses logged per PM step */
#define ALARM_SECONDS 0x01
#define ALARM_MINUTES 0x03
#define ALARM_HOURS 0x05

enum kind { K_CB_START, K_CB_END, K_PHASE_BEGIN, K_PHASE_END,
	    L_NOTIFY, L_MARKER, L_METHOD, L_METHOD_END, L_REGION };

static const char *const phase_names[] = {
	[1] = "suspend_enter", [2] = "sync_filesystems", [3] = "freeze_processes",
	[4] = "dpm_prepare", [5] = "dpm_suspend", [6] = "dpm_suspend_late",
	[7] = "dpm_suspend_noirq", [8] = "machine_suspend", [9] = "timekeeping_freeze",
	[10] = "dpm_resume_noirq", [11] = "dpm_resume_early", [12] = "dpm_resume",
	[13] = "dpm_complete", [14] = "thaw_processes",
};

struct crumb {
	u64 ns;
	u32 step;		/* PM steps so far in this cycle */
	u16 cycle;
	u8 kind, phase;
	u16 code;		/* device hash, method hash, or misc code */
	u16 acpi_seq;
	u8 space, write, width, depth;
	int value32;		/* callback error, notifier event, marker */
	u64 address, value;
	char name[64], info[40];
};

static bool arm;
module_param(arm, bool, 0444);
MODULE_PARM_DESC(arm, "record PM steps into the RTC (N only reads registers)");
static unsigned int cycle_base;
module_param(cycle_base, uint, 0444);
MODULE_PARM_DESC(cycle_base, "suspend attempts this boot already made before loading");
/*
 * Causality test: from this suspend attempt on, keep the PCH xHCI (00:14.0)
 * out of D3. The PCI core then skips its native D3hot and \_SB.PCI0.XHC1._PS3,
 * and ACPI skips _PS0 on resume (no _PSC). Nothing else changes. 0 = off.
 */
static unsigned int xhci_d0_from;
module_param(xhci_d0_from, uint, 0444);
MODULE_PARM_DESC(xhci_d0_from, "keep 00:14.0 in D0 from this suspend attempt on (0 = never)");
static bool xhci_d0_active;
module_param(xhci_d0_active, bool, 0444);
static struct pci_dev *xhci;

static DEFINE_RAW_SPINLOCK(log_lock);
static struct crumb *log_buf;
static unsigned int log_count, log_dropped, region_logged;
static unsigned int cycle, step, cur_phase, acpi_seq;
static u8 method_hash;
static u64 cycle_start_ns;
static unsigned int rtc_writes, rtc_busy, alarm_skipped, bad_objects;
static bool armed, set_abused, alarms_saved;
static u8 saved_alarm[3];
static unsigned int last_value;
static struct dentry *dir;
static struct hrtimer heartbeat;

module_param(armed, bool, 0444);
module_param(cycle, uint, 0444);
module_param(log_count, uint, 0444);
module_param(log_dropped, uint, 0444);
module_param(rtc_writes, uint, 0444);
module_param(rtc_busy, uint, 0444);
module_param(alarm_skipped, uint, 0444);
module_param(bad_objects, uint, 0444);
module_param(last_value, uint, 0444);

static unsigned int hash_string(unsigned int seed, const char *s, unsigned int mod)
{
	unsigned char c;

	while ((c = *s++))
		seed = (seed << 16) + (seed << 6) - seed + c;
	return seed % mod;
}

static void acpi_name4(const struct acpi_namespace_node *node, char *out)
{
	unsigned int i;

	for (i = 0; i < 4; i++) {
		char c = node ? node->name.ascii[i] : '?';

		out[i] = (c >= 0x20 && c < 0x7f) ? c : '?';
	}
	out[4] = '\0';
}

static bool named(const struct acpi_namespace_node *node)
{
	return node && node->descriptor_type == ACPI_DESC_TYPE_NAMED;
}

/* "PCI0.XHC1._PS3": up to three levels, enough to name the device. */
static void acpi_path3(const struct acpi_namespace_node *node, char *out, size_t size)
{
	const struct acpi_namespace_node *parts[3];
	char name[5];
	int n = 0, len = 0;

	while (n < 3 && named(node) && node->parent) {
		parts[n++] = node;
		node = node->parent;
	}
	out[0] = '\0';
	while (n--) {
		acpi_name4(parts[n], name);
		len += scnprintf(out + len, size - len, "%s%s", len ? "." : "", name);
	}
}

static unsigned int log_add(const struct crumb *entry)
{
	unsigned int index = UINT_MAX;
	unsigned long flags;

	raw_spin_lock_irqsave(&log_lock, flags);
	if (log_buf && log_count < LOG_ENTRIES) {
		index = log_count;
		log_buf[index] = *entry;
		log_buf[index].ns = ktime_get_mono_fast_ns();
		log_count++;
	} else {
		log_dropped++;
	}
	raw_spin_unlock_irqrestore(&log_lock, flags);
	return index;
}

/* Caller holds rtc_lock. */
static void write_time_locked(unsigned int value)
{
	unsigned char control = CMOS_READ(RTC_CONTROL);
	unsigned int hour, mday, mon, year;

	hour = value % 24;
	value /= 24;
	mday = value % 28 + 1;
	value /= 28;
	mon = value % 12 + 1;
	year = value / 12;
	if (!(control & RTC_DM_BINARY)) {
		hour = bin2bcd(hour);
		mday = bin2bcd(mday);
		mon = bin2bcd(mon);
		year = bin2bcd(year);
	}
	CMOS_WRITE(control | RTC_SET, RTC_CONTROL);
	CMOS_WRITE(year, RTC_YEAR);
	CMOS_WRITE(mon, RTC_MONTH);
	CMOS_WRITE(mday, RTC_DAY_OF_MONTH);
	CMOS_WRITE(hour, RTC_HOURS);
	CMOS_WRITE(0, RTC_MINUTES);
	CMOS_WRITE(0, RTC_SECONDS);
	CMOS_WRITE(control & ~RTC_SET, RTC_CONTROL);
}

/* Caller holds rtc_lock. Never touch alarms while an alarm could fire. */
static void write_alarm_locked(u8 reg, u8 value)
{
	if (CMOS_READ(RTC_CONTROL) & RTC_AIE) {
		alarm_skipped++;
		return;
	}
	CMOS_WRITE(value, reg);
}

/* PM step: date/time registers, and clear the ACPI detail. */
static void pm_step(enum kind kind, unsigned int phase, unsigned int code)
{
	unsigned int c = min(cycle, (unsigned int)NCYCLE - 1);
	unsigned int value = code % DEVHASH + DEVHASH * (phase + NPHASE * (c + NCYCLE * kind));
	unsigned long flags;

	step++;
	acpi_seq = 0;
	method_hash = 0;
	region_logged = 0;
	last_value = value;
	/*
	 * Wait rather than skip: no PM tracepoint, notifier or probed ACPICA
	 * function runs while this CPU holds rtc_lock, so this cannot deadlock,
	 * and a skipped write could hide the very step before a reset.
	 */
	spin_lock_irqsave(&rtc_lock, flags);
	pm_trace_rtc_abused = true;	/* pm_trace's own notifier clears it after resume */
	set_abused = true;
	write_time_locked(value);
	write_alarm_locked(ALARM_MINUTES, 0);
	write_alarm_locked(ALARM_HOURS, 0);
	rtc_writes++;
	spin_unlock_irqrestore(&rtc_lock, flags);
}

static unsigned int phase_index(const char *action, unsigned int *misc)
{
	unsigned int i;

	for (i = 1; i < ARRAY_SIZE(phase_names); i++)
		if (!strcmp(action, phase_names[i]))
			return i;
	if (!strcmp(action, "console_resume_all"))
		*misc = MISC_CONSOLE;
	else if (!strcmp(action, "acpi_suspend"))
		*misc = MISC_ACPI_SUSPEND;
	else if (!strcmp(action, "CPU_OFF"))
		*misc = MISC_CPU_OFF;
	else if (!strcmp(action, "CPU_ON"))
		*misc = MISC_CPU_ON;
	else
		*misc = MISC_OTHER;
	return PH_MISC;
}

static void on_callback_start(void *unused, struct device *dev, const char *ops, int event)
{
	struct crumb e = { .kind = K_CB_START, .value32 = event };

	if (!READ_ONCE(armed))
		return;
	e.code = hash_string(7919, dev_name(dev), DEVHASH);
	strscpy(e.name, dev_name(dev));
	scnprintf(e.info, sizeof(e.info), "%s %s", dev_driver_string(dev), ops ?: "");
	pm_step(K_CB_START, cur_phase, e.code);
	e.cycle = cycle;
	e.step = step;
	e.phase = cur_phase;
	log_add(&e);
}

static void on_callback_end(void *unused, struct device *dev, int error)
{
	struct crumb e = { .kind = K_CB_END, .value32 = error };

	if (!READ_ONCE(armed))
		return;
	e.code = hash_string(7919, dev_name(dev), DEVHASH);
	strscpy(e.name, dev_name(dev));
	pm_step(K_CB_END, cur_phase, e.code);
	e.cycle = cycle;
	e.step = step;
	e.phase = cur_phase;
	log_add(&e);
}

static void on_phase(void *unused, const char *action, int val, bool begin)
{
	struct crumb e = { .kind = begin ? K_PHASE_BEGIN : K_PHASE_END, .value32 = val };
	unsigned int misc = 0, phase;

	if (!READ_ONCE(armed))
		return;
	phase = phase_index(action, &misc);
	if (phase == 1 && begin) {
		cycle++;
		step = 0;
		cycle_start_ns = ktime_get_mono_fast_ns();
		/* Before dpm_prepare: the controller is still in D0 here. */
		if (xhci && xhci_d0_from && cycle >= xhci_d0_from && !xhci_d0_active) {
			xhci->dev_flags |= PCI_DEV_FLAGS_NO_D3;
			WRITE_ONCE(xhci_d0_active, true);
		}
	}
	if (phase != PH_MISC && begin)
		cur_phase = phase;
	e.code = phase == PH_MISC ? misc : 0;	/* a CPU number stays in the log */
	strscpy(e.name, action);
	if (phase == 1 && begin)
		strscpy(e.info, READ_ONCE(xhci_d0_active) ? "xhci kept in D0" : "");
	pm_step(e.kind, phase, e.code);
	e.cycle = cycle;
	e.step = step;
	e.phase = phase;
	log_add(&e);
}

static int on_pm_notify(struct notifier_block *nb, unsigned long event, void *unused)
{
	struct crumb e = { .kind = L_NOTIFY, .value32 = event };

	if (!READ_ONCE(armed))
		return NOTIFY_DONE;
	e.code = event & 0xf;
	scnprintf(e.name, sizeof(e.name), "pm_notifier %lu", event);
	pm_step(K_CB_START, PH_MISC, e.code);
	e.cycle = cycle;
	e.step = step;
	e.phase = PH_MISC;
	log_add(&e);
	return NOTIFY_DONE;
}

static struct notifier_block pm_nb = {
	.notifier_call = on_pm_notify,
	.priority = INT_MAX,
};

static void acpi_detail(u8 hash)
{
	unsigned long flags;

	if (acpi_seq < 0xffff)
		acpi_seq++;
	if (hash)
		method_hash = hash;
	spin_lock_irqsave(&rtc_lock, flags);
	if (hash)
		write_alarm_locked(ALARM_MINUTES, hash);
	write_alarm_locked(ALARM_HOURS, min(acpi_seq, 255U));
	spin_unlock_irqrestore(&rtc_lock, flags);
}

static int on_method_begin(struct kprobe *p, struct pt_regs *regs)
{
	struct acpi_namespace_node *node = (void *)regs->di;
	struct crumb e = { .kind = L_METHOD };
	u8 hash;

	if (!READ_ONCE(armed))
		return 0;
	if (!named(node)) {
		bad_objects++;
		return 0;
	}
	acpi_path3(node, e.name, sizeof(e.name));
	hash = hash_string(31, e.name, 255) + 1;
	acpi_detail(hash);
	e.code = hash;
	e.cycle = cycle;
	e.step = step;
	e.phase = cur_phase;
	e.acpi_seq = acpi_seq;
	log_add(&e);
	return 0;
}

static int on_method_end(struct kprobe *p, struct pt_regs *regs)
{
	union acpi_operand_object *method = (void *)regs->di;
	struct crumb e = { .kind = L_METHOD_END };

	if (!READ_ONCE(armed))
		return 0;
	if (!method || method->common.descriptor_type != ACPI_DESC_TYPE_OPERAND ||
	    method->common.type != ACPI_TYPE_METHOD ||
	    !named((struct acpi_namespace_node *)method->method.node)) {
		bad_objects++;
		return 0;
	}
	acpi_path3((struct acpi_namespace_node *)method->method.node, e.name, sizeof(e.name));
	acpi_detail(0);
	e.cycle = cycle;
	e.step = step;
	e.phase = cur_phase;
	e.acpi_seq = acpi_seq;
	log_add(&e);
	return 0;
}

struct region_call {
	unsigned int index;
	u64 *value;
};

/* Plain integer spaces only; SMBus and serial buses pass buffer structures. */
static bool integer_space(u8 space)
{
	return space <= ACPI_ADR_SPACE_EC || space == ACPI_ADR_SPACE_CMOS;
}

static int on_region(struct kretprobe_instance *ri, struct pt_regs *regs)
{
	struct region_call *call = (void *)ri->data;
	union acpi_operand_object *region = (void *)regs->di;
	union acpi_operand_object *field = (void *)regs->si;
	u32 function = regs->dx, offset = regs->cx, width = regs->r8;
	u64 *value = (void *)regs->r9;
	struct crumb e = { .kind = L_REGION };
	unsigned int index;
	char name[5];

	call->index = UINT_MAX;
	if (!READ_ONCE(armed))
		return 0;
	if (!region || region->common.descriptor_type != ACPI_DESC_TYPE_OPERAND ||
	    region->common.type != ACPI_TYPE_REGION) {
		bad_objects++;
		return 0;
	}
	acpi_detail(0);
	if (region_logged >= REGION_LOG_LIMIT)
		return 0;
	region_logged++;
	e.space = region->region.space_id;
	e.address = region->region.address + offset;
	e.width = width;
	e.write = (function & ACPI_IO_MASK) == ACPI_WRITE;
	if (e.write && value && integer_space(e.space))
		e.value = *value;
	acpi_path3(region->region.node, e.info, sizeof(e.info));
	if (field && field->common.descriptor_type == ACPI_DESC_TYPE_OPERAND &&
	    (field->common.type == ACPI_TYPE_LOCAL_REGION_FIELD ||
	     field->common.type == ACPI_TYPE_LOCAL_BANK_FIELD ||
	     field->common.type == ACPI_TYPE_LOCAL_INDEX_FIELD) &&
	    named(field->common_field.node)) {
		acpi_name4(field->common_field.node, name);
		strscpy(e.name, name);
	}
	e.cycle = cycle;
	e.step = step;
	e.phase = cur_phase;
	e.acpi_seq = acpi_seq;
	index = log_add(&e);
	if (!e.write && value && integer_space(e.space)) {
		call->index = index;
		call->value = value;
	}
	return 0;
}

static int on_region_return(struct kretprobe_instance *ri, struct pt_regs *regs)
{
	struct region_call *call = (void *)ri->data;

	if (call->index < LOG_ENTRIES && regs_return_value(regs) == AE_OK)
		log_buf[call->index].value = *call->value;
	return 0;
}

static struct kprobe kp_method = { .symbol_name = "acpi_ds_begin_method_execution",
				   .pre_handler = on_method_begin };
static struct kprobe kp_method_end = { .symbol_name = "acpi_ds_terminate_control_method",
				       .pre_handler = on_method_end };
static struct kretprobe krp_region = {
	.kp.symbol_name = "acpi_ev_address_space_dispatch",
	.entry_handler = on_region,
	.handler = on_region_return,
	.data_size = sizeof(struct region_call),
	.maxactive = 64,
};
static struct kprobe *kprobes[] = { &kp_method, &kp_method_end };

struct probe {
	const char *name;
	void *callback;
	struct tracepoint *tp;
	bool registered;
};

static struct probe probes[] = {
	{ .name = "device_pm_callback_start", .callback = on_callback_start },
	{ .name = "device_pm_callback_end", .callback = on_callback_end },
	{ .name = "suspend_resume", .callback = on_phase },
};

static void find_probe(struct tracepoint *tp, void *unused)
{
	unsigned int i;

	for (i = 0; i < ARRAY_SIZE(probes); i++)
		if (!strcmp(tp->name, probes[i].name))
			probes[i].tp = tp;
}

static enum hrtimer_restart on_heartbeat(struct hrtimer *timer)
{
	unsigned long flags;
	u64 half_seconds;

	if (READ_ONCE(armed) && cycle && spin_trylock_irqsave(&rtc_lock, flags)) {
		half_seconds = div_u64(ktime_get_mono_fast_ns() - cycle_start_ns, NSEC_PER_SEC / 2);
		write_alarm_locked(ALARM_SECONDS, min_t(u64, half_seconds, 255));
		spin_unlock_irqrestore(&rtc_lock, flags);
	}
	hrtimer_forward_now(timer, ms_to_ktime(500));
	return HRTIMER_RESTART;
}

static const char *const kind_names[] = {
	"CB_START", "CB_END", "PHASE_BEGIN", "PHASE_END", "NOTIFY", "MARKER",
	"METHOD", "METHOD_END", "REGION",
};

static int crumbs_show(struct seq_file *m, void *unused)
{
	unsigned int i, count = READ_ONCE(log_count);

	seq_printf(m, "# entries=%u dropped=%u cycle=%u rtc_writes=%u rtc_busy=%u alarm_skipped=%u bad_objects=%u\n",
		   count, log_dropped, cycle, rtc_writes, rtc_busy, alarm_skipped, bad_objects);
	seq_puts(m, "# ns cycle step phase kind code acpi_seq value32 | name | info | space write width address value\n");
	for (i = 0; i < count; i++) {
		const struct crumb *e = &log_buf[i];

		seq_printf(m, "%llu %u %u %u %s %u %u %d | %s | %s",
			   e->ns, e->cycle, e->step, e->phase, kind_names[e->kind], e->code,
			   e->acpi_seq, e->value32, e->name, e->info);
		if (e->kind == L_REGION)
			seq_printf(m, " | %u %u %u 0x%llx 0x%llx", e->space, e->write, e->width,
				   e->address, e->value);
		seq_putc(m, '\n');
	}
	return 0;
}
DEFINE_SHOW_ATTRIBUTE(crumbs);

static int rtc_show(struct seq_file *m, void *unused)
{
	static const u8 regs[] = { 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,
				   0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x32 };
	u8 values[ARRAY_SIZE(regs)];
	unsigned long flags;
	unsigned int i;

	spin_lock_irqsave(&rtc_lock, flags);
	for (i = 0; i < ARRAY_SIZE(regs); i++)
		values[i] = regs[i] == 0x0c ? 0 : CMOS_READ(regs[i]);	/* reading C clears flags */
	spin_unlock_irqrestore(&rtc_lock, flags);
	for (i = 0; i < ARRAY_SIZE(regs); i++)
		seq_printf(m, "reg%02x=%02x\n", regs[i], values[i]);
	seq_printf(m, "saved_alarms=%02x,%02x,%02x valid=%d last_value=%u\n",
		   saved_alarm[0], saved_alarm[1], saved_alarm[2], alarms_saved, last_value);
	return 0;
}
DEFINE_SHOW_ATTRIBUTE(rtc);

/* Every method's short path and hash, to decode alarm register 0x03 later. */
static acpi_status list_method(acpi_handle handle, u32 level, void *context, void **ret)
{
	struct seq_file *m = context;
	char path[64];

	acpi_path3(handle, path, sizeof(path));
	seq_printf(m, "%u %s\n", hash_string(31, path, 255) + 1, path);
	return AE_OK;
}

static int methods_show(struct seq_file *m, void *unused)
{
	acpi_walk_namespace(ACPI_TYPE_METHOD, ACPI_ROOT_OBJECT, ACPI_UINT32_MAX,
			    list_method, NULL, m, NULL);
	return 0;
}
DEFINE_SHOW_ATTRIBUTE(methods);

static int marker_set(const char *val, const struct kernel_param *kp)
{
	struct crumb e = { .kind = L_MARKER };
	unsigned int marker;
	int ret = kstrtouint(val, 0, &marker);

	if (ret)
		return ret;
	if (!READ_ONCE(armed) || marker >= MISC_CONSOLE - MISC_MARKER)
		return -EINVAL;
	e.value32 = marker;
	e.code = MISC_MARKER + marker;
	scnprintf(e.name, sizeof(e.name), "marker %u", marker);
	pm_step(K_CB_START, PH_MISC, e.code);
	e.cycle = cycle;
	e.step = step;
	e.phase = PH_MISC;
	log_add(&e);
	return 0;
}
static const struct kernel_param_ops marker_ops = { .set = marker_set };
module_param_cb(marker, &marker_ops, NULL, 0200);

/* Refuse to load if the ACPICA layouts compiled in do not match this kernel. */
static int check_acpica_layout(void)
{
	struct acpi_namespace_node *node, *field;
	union acpi_operand_object *region;
	acpi_handle handle;
	char name[5];

	if (ACPI_FAILURE(acpi_get_handle(NULL, "\\_SB.PCI0.XHC1", &handle)))
		return -ENODEV;
	node = handle;
	acpi_name4(node, name);
	if (!named(node) || strcmp(name, "XHC1") || !named(node->parent))
		return -EPROTO;
	acpi_name4(node->parent, name);
	if (strcmp(name, "PCI0"))
		return -EPROTO;
	if (ACPI_FAILURE(acpi_get_handle(NULL, "\\PMST", &handle)))
		return -ENODEV;
	region = ((struct acpi_namespace_node *)handle)->object;
	if (!region || region->common.descriptor_type != ACPI_DESC_TYPE_OPERAND ||
	    region->common.type != ACPI_TYPE_REGION || region->region.space_id != 0 ||
	    region->region.address != 0xFE000000 || region->region.length != 0x350 ||
	    region->region.node != handle)
		return -EPROTO;
	if (ACPI_FAILURE(acpi_get_handle(NULL, "\\MPMC", &handle)))
		return -ENODEV;
	field = handle;
	if (!field->object || field->object->common.type != ACPI_TYPE_LOCAL_REGION_FIELD ||
	    field->object->common_field.node != field ||
	    field->object->common_field.region_obj != region ||
	    field->object->common_field.base_byte_offset != 0x20)
		return -EPROTO;
	return 0;
}

static void remove_tracepoints(void)
{
	unsigned int i;

	for (i = 0; i < ARRAY_SIZE(probes); i++)
		if (probes[i].registered)
			tracepoint_probe_unregister(probes[i].tp, probes[i].callback, NULL);
	tracepoint_synchronize_unregister();
}

static int __init crumb_init(void)
{
	unsigned long flags;
	unsigned int i;
	int ret;

	if (!dmi_match(DMI_PRODUCT_NAME, "iMac18,3") || !x86_platform.legacy.rtc)
		return -ENODEV;
	if (acpi_gbl_FADT.century != 0x32)
		return -ENODEV;
	ret = check_acpica_layout();
	if (ret) {
		pr_err("imac-pm-crumb: ACPICA layout check failed (%d); not loading\n", ret);
		return ret;
	}
	spin_lock_irqsave(&rtc_lock, flags);
	saved_alarm[0] = CMOS_READ(ALARM_SECONDS);
	saved_alarm[1] = CMOS_READ(ALARM_MINUTES);
	saved_alarm[2] = CMOS_READ(ALARM_HOURS);
	alarms_saved = true;
	ret = CMOS_READ(RTC_CONTROL);
	spin_unlock_irqrestore(&rtc_lock, flags);
	/* The encoding writes hours 0..23; a 12-hour RTC would mangle them. */
	if (arm && !(ret & RTC_24H))
		return -EOPNOTSUPP;

	dir = debugfs_create_dir("imac_pm_crumb", NULL);
	debugfs_create_file("rtc", 0400, dir, NULL, &rtc_fops);
	debugfs_create_file("methods", 0400, dir, NULL, &methods_fops);
	if (!arm) {
		pr_info("imac-pm-crumb: loaded read-only; alarms %02x %02x %02x\n",
			saved_alarm[0], saved_alarm[1], saved_alarm[2]);
		return 0;
	}

	if (xhci_d0_from) {
		xhci = pci_get_domain_bus_and_slot(0, 0, PCI_DEVFN(0x14, 0));
		if (!xhci || xhci->vendor != PCI_VENDOR_ID_INTEL ||
		    xhci->class != PCI_CLASS_SERIAL_USB_XHCI ||
		    (xhci->dev_flags & PCI_DEV_FLAGS_NO_D3) || xhci->current_state != PCI_D0) {
			ret = -ENODEV;
			goto fail;
		}
	}
	log_buf = vzalloc(array_size(LOG_ENTRIES, sizeof(*log_buf)));
	if (!log_buf) {
		ret = -ENOMEM;
		goto fail;
	}
	debugfs_create_file("log", 0400, dir, NULL, &crumbs_fops);
	for_each_kernel_tracepoint(find_probe, NULL);
	for (i = 0; i < ARRAY_SIZE(probes); i++) {
		if (!probes[i].tp) {
			ret = -ENOENT;
			goto fail_tracepoints;
		}
		ret = tracepoint_probe_register(probes[i].tp, probes[i].callback, NULL);
		if (ret)
			goto fail_tracepoints;
		probes[i].registered = true;
	}
	ret = register_kprobes(kprobes, ARRAY_SIZE(kprobes));
	if (ret)
		goto fail_tracepoints;
	ret = register_kretprobe(&krp_region);
	if (ret)
		goto fail_kprobes;
	ret = register_pm_notifier(&pm_nb);
	if (ret)
		goto fail_kretprobe;
	hrtimer_setup(&heartbeat, on_heartbeat, CLOCK_MONOTONIC, HRTIMER_MODE_REL);
	cycle = cycle_base;
	WRITE_ONCE(armed, true);
	hrtimer_start(&heartbeat, ms_to_ktime(500), HRTIMER_MODE_REL);
	pr_info("imac-pm-crumb: armed; RTC now holds breadcrumbs until unload\n");
	return 0;

fail_kretprobe:
	unregister_kretprobe(&krp_region);
fail_kprobes:
	unregister_kprobes(kprobes, ARRAY_SIZE(kprobes));
fail_tracepoints:
	remove_tracepoints();
fail:
	debugfs_remove_recursive(dir);
	vfree(log_buf);
	pci_dev_put(xhci);
	return ret;
}

static void __exit crumb_exit(void)
{
	struct timespec64 now;
	struct rtc_time tm;
	unsigned long flags;

	if (log_buf) {
		WRITE_ONCE(armed, false);
		hrtimer_cancel(&heartbeat);
		unregister_pm_notifier(&pm_nb);
		unregister_kretprobe(&krp_region);
		unregister_kprobes(kprobes, ARRAY_SIZE(kprobes));
		remove_tracepoints();
	}
	if (xhci) {
		if (xhci_d0_active)
			xhci->dev_flags &= ~PCI_DEV_FLAGS_NO_D3;
		pci_dev_put(xhci);
	}
	debugfs_remove_recursive(dir);
	if (set_abused) {
		spin_lock_irqsave(&rtc_lock, flags);
		if (alarms_saved && !(CMOS_READ(RTC_CONTROL) & RTC_AIE)) {
			CMOS_WRITE(saved_alarm[0], ALARM_SECONDS);
			CMOS_WRITE(saved_alarm[1], ALARM_MINUTES);
			CMOS_WRITE(saved_alarm[2], ALARM_HOURS);
		}
		spin_unlock_irqrestore(&rtc_lock, flags);
		ktime_get_real_ts64(&now);
		rtc_time64_to_tm(now.tv_sec, &tm);
		if (mc146818_set_time(&tm))
			pr_err("imac-pm-crumb: could not restore the RTC; run hwclock --systohc\n");
		pm_trace_rtc_abused = false;
		pr_info("imac-pm-crumb: RTC restored to system time %ptRd %ptRt UTC\n", &tm, &tm);
	}
	vfree(log_buf);
}

module_init(crumb_init);
module_exit(crumb_exit);
