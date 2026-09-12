from configparser import ConfigParser
from pathlib import Path


def test_systemd_service_uses_installed_entrypoint_and_bounded_shutdown():
    unit = ConfigParser(interpolation=None)
    unit.read('deploy/autodrome.service')
    service = unit['Service']
    assert service['User'] != 'root'
    assert service['Type'] == 'simple'
    assert service['WorkingDirectory'].startswith('/')
    assert service['ExecStart'].endswith('/.venv/bin/autodrome')
    assert 'start_autodrome.sh' not in service['ExecStart']
    assert service['EnvironmentFile'].endswith('/.env')
    assert service['Restart'] == 'on-failure'
    assert int(service['RestartSec']) >= 5
    assert service['KillMode'] == 'mixed'
    assert int(service['TimeoutStopSec']) <= 120
    assert unit['Install']['WantedBy'] == 'multi-user.target'


def test_checkout_launcher_is_development_only():
    launcher = Path("start_autodrome.sh").read_text(encoding="utf-8")

    assert "--production" not in launcher
    assert "autodrome.web:app" in launcher
