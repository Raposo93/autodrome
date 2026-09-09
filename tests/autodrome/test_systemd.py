from configparser import ConfigParser
from pathlib import Path


def test_systemd_service_uses_foreground_production_and_bounded_shutdown():
    unit = ConfigParser(interpolation=None)
    unit.read('deploy/autodrome.service')
    service = unit['Service']
    assert service['User'] != 'root'
    assert service['Type'] == 'simple'
    assert service['WorkingDirectory'].startswith('/')
    assert service['ExecStart'].endswith('start_autodrome.sh --production')
    assert service['EnvironmentFile'].endswith('/.env')
    assert service['Restart'] == 'on-failure'
    assert int(service['RestartSec']) >= 5
    assert service['KillMode'] == 'mixed'
    assert int(service['TimeoutStopSec']) <= 120
    assert unit['Install']['WantedBy'] == 'multi-user.target'
