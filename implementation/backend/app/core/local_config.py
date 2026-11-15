"""Validated local port identity shared with Vite; explicit overrides stay local."""
from dataclasses import dataclass
import json
from pathlib import Path
from collections.abc import Mapping

CONFIG_PATH = Path(__file__).resolve().parents[3] / 'config' / 'local-development.json'


@dataclass(frozen=True)
class LocalDevelopment:
    backend_host: str
    backend_port: int
    frontend_port: int
    cors_hosts: tuple[str, ...]

    @property
    def backend_origin(self) -> str:
        return f'http://{self.backend_host}:{self.backend_port}'

    @property
    def frontend_origin(self) -> str:
        return f'http://127.0.0.1:{self.frontend_port}'

    @property
    def cors_origins(self) -> str:
        return ','.join(f'http://{host}:{self.frontend_port}' for host in self.cors_hosts)


def local_development(environment: Mapping[str, str] | None = None) -> LocalDevelopment:
    env = environment or {}
    raw = json.loads(CONFIG_PATH.read_text())
    def port(name: str) -> int:
        value = env.get('VCC_' + name.upper(), raw[name])
        if isinstance(value, bool) or not str(value).isdigit() or not 1024 <= int(value) <= 65535:
            raise ValueError('Local development ports must be unprivileged integers')
        return int(value)
    host = env.get('VCC_BACKEND_HOST', raw['backend_host'])
    hosts = tuple(raw['cors_hosts'])
    if host not in {'localhost', '127.0.0.1'} or set(hosts) != {'localhost', '127.0.0.1'}:
        raise ValueError('Local development hosts must use explicit loopback origins')
    return LocalDevelopment(host, port('backend_port'), port('frontend_port'), hosts)
