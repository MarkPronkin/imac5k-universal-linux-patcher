"""The two installers must ship the same default display and resume fixes."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PatchStackTests(unittest.TestCase):
    def stack(self, installer, stack="lean"):
        source = (ROOT / "scripts" / installer).read_text()
        if installer == "fedora-imac5k":
            start = source.index('case ${IMAC5K_STACK:-lean} in')
            code = source[start:source.index('    esac', start) + len('    esac')]
            output = 'printf "%s\\n" "${patches[@]}"'
        else:
            start = source.index('case "$IMAC5K_STACK" in')
            code = source[start:source.index('\nesac', start) + len('\nesac')]
            output = 'printf "%s\\n" "$PATCH_FILE" "${EXTRA_PATCHES[@]}"'
        result = subprocess.run(
            ["bash", "-c", 'set -euo pipefail\nSCRIPT_DIR=$1\nIMAC5K_STACK=$2\n' + code + '\n' + output,
             "test", str(ROOT / "scripts"), stack],
            text=True, capture_output=True, timeout=10, check=True)
        return [Path(line).name for line in result.stdout.splitlines()]

    def test_default_stack_is_identical_across_arch_and_fedora(self):
        arch = self.stack("patch-imac5k-amdgpu.sh")
        self.assertEqual(arch, self.stack("fedora-imac5k"))
        self.assertEqual(len(arch), len(set(arch)))
        for name in arch:
            self.assertTrue((ROOT / "patches" / name).is_file(), name)

    def test_imac_pro_followup_retains_the_resume_fixes_in_dependency_order(self):
        stack = self.stack("patch-imac5k-amdgpu.sh")
        required = ["5k-post-commit-link-recovery.patch", "5k-logical-modeset-guard.patch",
                    "5k-resume-drop-cached-peer.patch", "5k-resume-arm-link-health.patch",
                    "imacpro-slave-dp-panel-mode.patch", "dce120-enable-crtc-reset.patch",
                    "dce12-multisync-master-first.patch", "dce110-genlock-master-from-pipe0.patch",
                    "5k-resync-postpone-on-modeset.patch"]
        self.assertEqual([name for name in stack if name in required], required)
