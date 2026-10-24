"""The service/storage CI contract, also used by the full sweep."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    name: str
    timeout: int = 1200
    exclusive: bool = False

    @property
    def script(self):
        return 'tools/' + self.name + '-check.' + ('sh' if self.name == 'qsys' else 'py')


CHECKS = tuple(Check(name, exclusive=name == 'portable-shutdown') for name in (
    'files-service', 'files-shutdown', 'kv-large', 'hosted-timers',
    'endpoint-state', 'editor-policy', 'editor-state', 'preferences',
    'portable-durable', 'portable-shutdown', 'qsys', 'qlog-routing',
    'block-lifecycle', 'storage-reliability', 'storage-types', 'baseline-compile',
))
