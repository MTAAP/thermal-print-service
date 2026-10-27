import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_install_script_creates_thermalprinter_user_before_usermod():
    script = (REPO_ROOT / "deploy" / "install.sh").read_text()

    assert 'SERVICE_USER="${SERVICE_USER:-thermalprinter}"' in script
    assert 'SERVICE_GROUP="${SERVICE_GROUP:-${SERVICE_USER}}"' in script
    assert 'getent group "${SERVICE_GROUP}"' in script
    assert 'id -u "${SERVICE_USER}"' in script
    assert "useradd" in script
    assert '--gid "${SERVICE_GROUP}"' in script
    assert script.index("useradd") < script.index("usermod -aG lp")
    assert "s|User=thermalprinter|User=${SERVICE_USER}|g" in script
    assert "s|/home/thermalprinter/thermal-print-service|${APP_DIR}|g" in script


def test_sync_script_uses_remote_dir_inside_remote_install_step():
    script = (REPO_ROOT / "deploy" / "sync.sh").read_text()

    assert "REMOTE_DIR_ESCAPED" in script
    assert 'cd "${REMOTE_DIR_ESCAPED}"' in script


GUARD = REPO_ROOT / "deploy" / "wifi-profile-guard.sh"
WIFI_SOURCE = (
    "network:\n  version: 2\n  wifis:\n    wlan0:\n      dhcp4: true\n"
    '      access-points:\n        "test-ssid":\n          password: "test-password"\n'
)


def _run_guard(tmp_path, *, source_text=WIFI_SOURCE, generate_exit=0, generate_stderr=""):
    netplan = tmp_path / "netplan"
    netplan.mkdir(exist_ok=True)
    source = tmp_path / "network-config"
    if source_text is not None:
        source.write_text(source_text)
    marker = tmp_path / "generated"
    fake_generate = tmp_path / "fake-generate"
    fake_generate.write_text(
        f"#!/bin/sh\ntouch '{marker}'\necho '{generate_stderr}' >&2\nexit {generate_exit}\n"
    )
    fake_generate.chmod(0o755)
    env = {
        "PATH": os.environ["PATH"],
        "WIFI_GUARD_NETPLAN_DIR": str(netplan),
        "WIFI_GUARD_SOURCE": str(source),
        "WIFI_GUARD_GENERATE": str(fake_generate),
    }
    proc = subprocess.run(
        ["bash", str(GUARD)], env=env, capture_output=True, text=True, check=False,
    )
    return proc, netplan / "50-cloud-init.yaml", marker


def test_wifi_guard_restores_profile_when_only_empty_files_remain(tmp_path):
    (tmp_path / "netplan").mkdir()
    (tmp_path / "netplan" / "90-NM-0000.yaml").write_text("")

    proc, target, marker = _run_guard(tmp_path)

    assert proc.returncode == 0
    assert target.read_text() == WIFI_SOURCE
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert marker.exists()
    assert "restored" in proc.stdout
    assert "test-password" not in proc.stdout
    assert not list((tmp_path / "netplan").glob("*.tmp.*"))


def test_wifi_guard_leaves_a_present_profile_alone(tmp_path):
    (tmp_path / "netplan").mkdir()
    existing = tmp_path / "netplan" / "90-NM-1111.yaml"
    existing.write_text(
        "network:\n  version: 2\n  wifis:\n    NM-1111:\n      dhcp4: true\n"
        '      access-points:\n        "test-ssid":\n          auth:\n'
        '            key-management: "psk"\n'
    )

    proc, target, marker = _run_guard(tmp_path)

    assert proc.returncode == 0
    assert not target.exists()
    assert not marker.exists()
    assert "nothing to do" in proc.stdout


def test_wifi_guard_without_source_is_a_logged_no_op(tmp_path):
    proc, target, marker = _run_guard(tmp_path, source_text=None)

    assert proc.returncode == 0
    assert not target.exists()
    assert not marker.exists()
    assert "no usable source" in proc.stdout


def test_wifi_guard_does_not_count_a_profile_without_wifi(tmp_path):
    # Known-bad input: a non-empty netplan file with only ethernets must not
    # satisfy the check, and a source without wifis must not be restored.
    (tmp_path / "netplan").mkdir()
    (tmp_path / "netplan" / "10-eth.yaml").write_text(
        "network:\n  version: 2\n  ethernets:\n    eth0:\n      dhcp4: true\n"
    )

    proc, target, marker = _run_guard(
        tmp_path, source_text="network:\n  version: 2\n  ethernets: {}\n",
    )

    assert proc.returncode == 0
    assert not target.exists()
    assert not marker.exists()
    assert "no usable source" in proc.stdout


def test_wifi_guard_exits_zero_when_generate_fails(tmp_path):
    proc, target, marker = _run_guard(
        tmp_path, generate_exit=1, generate_stderr='password: "test-password"',
    )

    assert proc.returncode == 0
    assert target.read_text() == WIFI_SOURCE
    assert marker.exists()
    assert "ERROR" in proc.stdout
    assert "test-password" not in proc.stdout + proc.stderr


def test_wifi_guard_restores_over_a_wifi_section_without_networks(tmp_path):
    (tmp_path / "netplan").mkdir()
    (tmp_path / "netplan" / "90-NM-2222.yaml").write_text("network:\n  version: 2\n  wifis: {}\n")

    proc, target, marker = _run_guard(tmp_path)

    assert proc.returncode == 0
    assert target.read_text() == WIFI_SOURCE
    assert marker.exists()


def test_install_script_installs_and_enables_wifi_guard():
    script = (REPO_ROOT / "deploy" / "install.sh").read_text()
    unit = (REPO_ROOT / "deploy" / "wifi-profile-guard.service").read_text()

    assert "/usr/local/sbin/wifi-profile-guard.sh" in script
    assert "systemctl enable wifi-profile-guard.service" in script
    assert "ExecStart=/usr/local/sbin/wifi-profile-guard.sh" in unit
    assert "NetworkManager.service" in unit.split("Before=")[1].splitlines()[0]
    assert "TimeoutStartSec=" in unit
