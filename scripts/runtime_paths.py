"""Single source for immutable application resources and optional desktop state.

No directories are created on import/resolution. Omitting desktop environment
variables preserves the historical Web/CLI layout, including run archives.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import sys


@dataclass(frozen=True)
class RuntimePaths:
    resource_root: Path
    data_root: Path
    desktop: bool = False

    @classmethod
    def from_env(cls, environ=None):
        env = os.environ if environ is None else environ
        resource = Path(env.get('LISHUTTLE_RESOURCE_ROOT') or Path(__file__).resolve().parents[1]).expanduser().resolve()
        data = env.get('LISHUTTLE_DATA_DIR')
        return cls(resource, Path(data).expanduser().resolve() if data else resource, bool(data))

    @property
    def scripts_dir(self):
        return self.resource_root / 'scripts'

    @property
    def env_dir(self):
        return self.data_root / 'env'

    @property
    def env_file(self):
        return self.env_dir / 'local-win.env'

    @property
    def projects_file(self):
        return self.env_dir / 'projects.json'

    @property
    def jobs_dir(self):
        return self.data_root / 'jobs'

    @property
    def snapshots_dir(self):
        return self.env_dir / 'snapshots'

    @property
    def runs_dir(self):
        return self.data_root / ('runs' if self.desktop else '.lishuttle-runs')

    @property
    def maintenance_dir(self):
        return self.data_root / ('maintenance-archives' if self.desktop else 'docs/runtime-config-archives')

    @property
    def logs_dir(self):
        return self.data_root / 'logs'

    @property
    def cache_dir(self):
        return self.data_root / 'cache'

    @property
    def preferences_file(self):
        return self.data_root / 'desktop-preferences.json'


def resolve_paths(environ=None):
    return RuntimePaths.from_env(environ)


def python_executable(environ=None):
    env = os.environ if environ is None else environ
    return env.get('LISHUTTLE_PYTHON') or sys.executable
