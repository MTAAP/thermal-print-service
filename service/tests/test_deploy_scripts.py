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
