// SPDX-License-Identifier: GPL-2.0
/* Temporary iMac18,3 diagnostic. No panic, reboot, or device power changes.
 * A non-freezable worker snapshots an overdue SECOND suspend transition.
 * At most four 1024-byte EFI variables are written under our dedicated GUID.
 * The metadata is saved before attempting the best-effort remote task stack.
 */
#include <linux/device.h>
#include <linux/dmi.h>
#include <linux/efi.h>
#include <linux/init.h>
#include <linux/jiffies.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/sched/task.h>
#include <linux/slab.h>
#include <linux/spinlock.h>
#include <linux/stacktrace.h>
#include <linux/suspend.h>
#include <linux/tracepoint.h>
#include <linux/workqueue.h>

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("One-shot EFI snapshot of an overdue second iMac suspend");
MODULE_IMPORT_NS("EFIVAR");

#define PART_SIZE 1024
#define PARTS 4
#define ATTRS (EFI_VARIABLE_NON_VOLATILE | EFI_VARIABLE_BOOTSERVICE_ACCESS | \
	      EFI_VARIABLE_RUNTIME_ACCESS)
/* Apple's VSS data-checksum flag is returned by this iMac's GetVariable.
 * See LongSoft/UEFITool common/nvram.h, NVRAM_VSS_VARIABLE_APPLE_DATA_CHECKSUM.
 * Accept this one read-back addition; writes still request ordinary ATTRS.
 */
#define APPLE_DATA_CHECKSUM 0x80000000U
static efi_guid_t capture_guid = EFI_GUID(0x173f51a7, 0x82a5, 0x4e0a,
					0x92, 0xc4, 0x38, 0xa4, 0xb8, 0x49, 0xc5, 0xe1);
static char run_id[33];
static unsigned int timeout_seconds = 20;
static unsigned int seen_cycles, writes;
static int capture_error;
static unsigned long last_efi_status;
static unsigned int test_attrs;
static bool ready, storage_ready, armed;
static char test_result[160] = "not-run";
module_param_string(run_id, run_id, sizeof(run_id), 0444);
module_param(timeout_seconds, uint, 0444);
module_param(seen_cycles, uint, 0444);
module_param(writes, uint, 0444);
module_param(capture_error, int, 0444);
module_param(last_efi_status, ulong, 0444);
module_param(test_attrs, uint, 0444);
module_param(ready, bool, 0444);
module_param(storage_ready, bool, 0444);
module_param(armed, bool, 0444);
module_param_string(test_result, test_result, sizeof(test_result), 0444);

static DEFINE_SPINLOCK(state_lock);
static DEFINE_MUTEX(storage_lock);
static struct task_struct *sleep_task;
static struct workqueue_struct *capture_wq;
static struct delayed_work capture_work;
static char *record_buf, *stack_buf;

struct progress {
	char phase[64], device[96], driver[64], ops[64];
	bool phase_begin, callback_active;
	int event, error;
	pid_t callback_pid;
};
static struct progress progress;

struct probe {
	const char *name;
	void *callback;
	struct tracepoint *tp;
	bool registered;
};

static void varname(efi_char16_t *wide, const char *name)
{
	do {
		*wide++ = *name;
	} while (*name++);
}

static int set_record(const char *name, const void *data, unsigned long length)
{
	efi_char16_t wide[32];
	efi_status_t status;

	if (strlen(name) >= ARRAY_SIZE(wide) || length > PART_SIZE)
		return -EINVAL;
	varname(wide, name);
	/* Keep the ordinary EFI checks/lock. Legacy EFI cannot report free space. */
	status = efivar_set_variable(wide, &capture_guid, ATTRS, length, (void *)data);
	WRITE_ONCE(last_efi_status, status);
	if (status != EFI_SUCCESS)
		return efi_status_to_err(status);
	return 0;
}

static int get_record(const char *name, void *data, unsigned long *length, u32 *attrs)
{
	efi_char16_t wide[32];
	efi_status_t status;
	int ret;

	varname(wide, name);
	ret = efivar_lock();
	if (ret)
		return ret;
	status = efivar_get_variable(wide, &capture_guid, attrs, length, data);
	efivar_unlock();
	WRITE_ONCE(last_efi_status, status);
	return status == EFI_SUCCESS ? 0 : efi_status_to_err(status);
}

static int put_part(unsigned int part, const char *text, size_t length)
{
	char name[32];
	int prefix, ret;

	if (part >= PARTS)
		return -EINVAL;
	snprintf(name, sizeof(name), "ImacSleepCapture%u", part);
	prefix = scnprintf(record_buf, PART_SIZE,
		"IMAC_PM_CAPTURE v1 run=%s part=%u\n", run_id, part);
	if (length > PART_SIZE - prefix)
		return -E2BIG;
	memcpy(record_buf + prefix, text, length);
	ret = set_record(name, record_buf, prefix + length);
	if (!ret)
		writes++;
	return ret;
}

static int storage_test_set(const char *value, const struct kernel_param *kp)
{
	char expected[160], actual[160];
	unsigned long length = sizeof(actual);
	u32 attrs = 0;
	bool requested;
	int ret, cleanup;

	ret = kstrtobool(value, &requested);
	if (ret || !requested)
		return -EINVAL;
	if (!READ_ONCE(ready) || READ_ONCE(seen_cycles))
		return -EBUSY;
	mutex_lock(&storage_lock);
	snprintf(expected, sizeof(expected), "IMAC_PM_CAPTURE selftest run=%s\n", run_id);
	ret = set_record("ImacSleepTest", expected, strlen(expected));
	if (ret) {
		snprintf(test_result, sizeof(test_result), "write failed: errno=%d EFI=0x%lx",
			 ret, READ_ONCE(last_efi_status));
		goto out;
	}
	ret = get_record("ImacSleepTest", actual, &length, &attrs);
	WRITE_ONCE(test_attrs, attrs);
	if (ret) {
		snprintf(test_result, sizeof(test_result), "read failed: errno=%d EFI=0x%lx",
			 ret, READ_ONCE(last_efi_status));
	} else if (length != strlen(expected) || (attrs & ~APPLE_DATA_CHECKSUM) != ATTRS ||
		   memcmp(actual, expected, length)) {
		snprintf(test_result, sizeof(test_result),
			 "read-back mismatch: expected_bytes=%zu actual_bytes=%lu attrs=0x%x",
			 strlen(expected), length, attrs);
		ret = -EIO;
	}
	/* Delete only the temporary variable we just wrote, after reading it back. */
	cleanup = set_record("ImacSleepTest", NULL, 0);
	if (cleanup) {
		pr_err("imac-pm-capture: selftest deletion failed: errno=%d EFI=0x%lx\n",
		       cleanup, READ_ONCE(last_efi_status));
		if (!ret)
			snprintf(test_result, sizeof(test_result), "delete failed: errno=%d EFI=0x%lx",
				 cleanup, READ_ONCE(last_efi_status));
	} else {
		length = sizeof(actual);
		cleanup = get_record("ImacSleepTest", actual, &length, &attrs);
		if (cleanup == -ENOENT) {
			cleanup = 0;
		} else {
			pr_err("imac-pm-capture: selftest deletion not confirmed: errno=%d EFI=0x%lx\n",
			       cleanup, READ_ONCE(last_efi_status));
			if (!ret)
				snprintf(test_result, sizeof(test_result),
					 "delete read-back failed: errno=%d EFI=0x%lx",
					 cleanup, READ_ONCE(last_efi_status));
			cleanup = cleanup ?: -EIO;
		}
	}
	if (!ret)
		ret = cleanup;
	if (!ret) {
		strscpy(test_result, expected);
		WRITE_ONCE(storage_ready, true);
		pr_info("imac-pm-capture: EFI write/read/delete selftest passed, run=%s\n", run_id);
	}
out:
	if (ret)
		pr_err("imac-pm-capture: selftest: %s\n", test_result);
	mutex_unlock(&storage_lock);
	return ret;
}
static const struct kernel_param_ops storage_test_ops = { .set = storage_test_set };
module_param_cb(storage_test, &storage_test_ops, NULL, 0200);

static void callback_start(void *unused, struct device *dev, const char *ops, int event)
{
	unsigned long flags;

	spin_lock_irqsave(&state_lock, flags);
	if (armed) {
		strscpy(progress.device, dev_name(dev));
		strscpy(progress.driver, dev_driver_string(dev));
		strscpy(progress.ops, ops ?: "");
		progress.event = event;
		progress.callback_active = true;
		progress.callback_pid = task_pid_nr(current);
	}
	spin_unlock_irqrestore(&state_lock, flags);
}

static void callback_end(void *unused, struct device *dev, int error)
{
	unsigned long flags;

	spin_lock_irqsave(&state_lock, flags);
	if (armed && !strcmp(progress.device, dev_name(dev))) {
		progress.callback_active = false;
		progress.error = error;
	}
	spin_unlock_irqrestore(&state_lock, flags);
}

static void phase_event(void *unused, const char *action, int value, bool begin)
{
	unsigned long flags;

	spin_lock_irqsave(&state_lock, flags);
	if (armed) {
		strscpy(progress.phase, action);
		progress.phase_begin = begin;
	}
	spin_unlock_irqrestore(&state_lock, flags);
}

static struct probe probes[] = {
	{ .name = "device_pm_callback_start", .callback = callback_start },
	{ .name = "device_pm_callback_end", .callback = callback_end },
	{ .name = "suspend_resume", .callback = phase_event },
};

static void timed_capture(struct work_struct *work)
{
	struct progress saved;
	unsigned long flags, frames[32];
	unsigned int count, i, part;
	size_t length, offset;
	char metadata[768];
	bool active;
	int ret;

	spin_lock_irqsave(&state_lock, flags);
	active = armed;
	saved = progress;
	spin_unlock_irqrestore(&state_lock, flags);
	if (!active)
		return;
	mutex_lock(&storage_lock);
	length = scnprintf(metadata, sizeof(metadata),
		"timeout_seconds=%u cycle=%u\nphase=%s %s\n"
		"callback_active=%u driver=%s device=%s ops=%s event=%d error=%d callback_pid=%d\n"
		"sleep_pid=%d sleep_task=%s\n",
		timeout_seconds, seen_cycles, saved.phase, saved.phase_begin ? "begin" : "end",
		saved.callback_active, saved.driver, saved.device, saved.ops,
		saved.event, saved.error, saved.callback_pid, task_pid_nr(sleep_task), sleep_task->comm);
	pr_emerg("imac-pm-capture: %s", metadata);
	/* Preserve the last callback even if reading the other task's stack stalls. */
	ret = put_part(0, metadata, length);
	if (ret)
		goto out;
	count = stack_trace_save_tsk(sleep_task, frames, ARRAY_SIZE(frames), 0);
	length = scnprintf(stack_buf, PART_SIZE * 3, "best_effort_task_stack frames=%u\n", count);
	for (i = 0; i < count; i++)
		length += scnprintf(stack_buf + length, PART_SIZE * 3 - length,
				    "%pS\n", (void *)frames[i]);
	/* Keep room for each part's identifying header. */
	for (part = 1, offset = 0; offset < length && part < PARTS; part++) {
		size_t amount = min_t(size_t, length - offset, PART_SIZE - 96);

		ret = put_part(part, stack_buf + offset, amount);
		if (ret)
			goto out;
		offset += amount;
	}
	if (offset < length)
		pr_warn("imac-pm-capture: stack snapshot truncated to three parts\n");
out:
	capture_error = ret;
	pr_emerg("imac-pm-capture: EFI snapshot run=%s writes=%u result=%d\n", run_id, writes, ret);
	mutex_unlock(&storage_lock);
}

static int pm_event(struct notifier_block *nb, unsigned long event, void *unused)
{
	unsigned long flags;
	bool start = false, stop = false;

	spin_lock_irqsave(&state_lock, flags);
	if (event == PM_SUSPEND_PREPARE) {
		seen_cycles++;
		if (seen_cycles == 2 && storage_ready) {
			sleep_task = current;
			get_task_struct(sleep_task);
			memset(&progress, 0, sizeof(progress));
			strscpy(progress.phase, "PM_SUSPEND_PREPARE");
			progress.phase_begin = true;
			armed = true;
			start = true;
		}
	} else if (event == PM_POST_SUSPEND && armed) {
		armed = false;
		stop = true;
	}
	spin_unlock_irqrestore(&state_lock, flags);
	if (start)
		queue_delayed_work(capture_wq, &capture_work, timeout_seconds * HZ);
	if (stop)
		cancel_delayed_work(&capture_work);
	return NOTIFY_DONE;
}
static struct notifier_block pm_nb = { .notifier_call = pm_event };

static void find_probe(struct tracepoint *tp, void *unused)
{
	unsigned int i;

	for (i = 0; i < ARRAY_SIZE(probes); i++)
		if (!strcmp(tp->name, probes[i].name))
			probes[i].tp = tp;
}

static void remove_probes(void)
{
	unsigned int i;

	for (i = 0; i < ARRAY_SIZE(probes); i++)
		if (probes[i].registered)
			tracepoint_probe_unregister(probes[i].tp, probes[i].callback, NULL);
	tracepoint_synchronize_unregister();
}

static int __init capture_init(void)
{
	unsigned int i;
	char name[32], byte;
	unsigned long length;
	int ret;

	if (!dmi_match(DMI_PRODUCT_NAME, "iMac18,3") || !efivar_supports_writes() ||
	    timeout_seconds < 15 || timeout_seconds > 40 || strlen(run_id) != 32)
		return -EINVAL;
	for (i = 0; i < PARTS + 1; i++) {
		if (i == PARTS)
			strscpy(name, "ImacSleepTest");
		else
			snprintf(name, sizeof(name), "ImacSleepCapture%u", i);
		length = 1;
		ret = get_record(name, &byte, &length, NULL);
		if (ret != -ENOENT)
			return ret ? ret : -EEXIST; /* Never overwrite an earlier record. */
	}
	record_buf = kmalloc(PART_SIZE, GFP_KERNEL);
	stack_buf = kmalloc(PART_SIZE * 3, GFP_KERNEL);
	capture_wq = alloc_workqueue("imac-pm-capture", WQ_UNBOUND | WQ_HIGHPRI | WQ_MEM_RECLAIM, 1);
	if (!record_buf || !stack_buf || !capture_wq) {
		ret = -ENOMEM;
		goto fail;
	}
	INIT_DELAYED_WORK(&capture_work, timed_capture);
	for_each_kernel_tracepoint(find_probe, NULL);
	for (i = 0; i < ARRAY_SIZE(probes); i++) {
		if (!probes[i].tp) {
			ret = -ENOENT;
			goto fail_probes;
		}
		ret = tracepoint_probe_register(probes[i].tp, probes[i].callback, NULL);
		if (ret)
			goto fail_probes;
		probes[i].registered = true;
	}
	ret = register_pm_notifier(&pm_nb);
	if (ret)
		goto fail_probes;
	ready = true;
	pr_info("imac-pm-capture: loaded, run=%s; EFI selftest required before second-cycle capture\n", run_id);
	return 0;
fail_probes:
	remove_probes();
fail:
	if (capture_wq)
		destroy_workqueue(capture_wq);
	kfree(record_buf);
	kfree(stack_buf);
	return ret;
}

static void __exit capture_exit(void)
{
	WRITE_ONCE(ready, false);
	unregister_pm_notifier(&pm_nb);
	remove_probes();
	cancel_delayed_work_sync(&capture_work);
	destroy_workqueue(capture_wq);
	if (sleep_task)
		put_task_struct(sleep_task);
	kfree(record_buf);
	kfree(stack_buf);
}
module_init(capture_init);
module_exit(capture_exit);
