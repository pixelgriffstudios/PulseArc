from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunnerSpec:
    runner_id: str
    kind: str
    executable: str
    arguments: tuple[str, ...]
    package: str


@dataclass(frozen=True)
class SystemSpec:
    system_id: str
    extensions: tuple[str, ...]
    primary: str
    fallbacks: tuple[str, ...]
    bios: tuple[str, ...]


class RuntimeRegistry:
    def __init__(self, runners: dict[str, RunnerSpec], systems: dict[str, SystemSpec]):
        self.runners = runners
        self.systems = systems

    @classmethod
    def load(cls, path: str | Path) -> "RuntimeRegistry":
        with Path(path).open("rb") as handle:
            document = tomllib.load(handle)
        runners = {
            runner_id: RunnerSpec(
                runner_id=runner_id,
                kind=str(value["kind"]),
                executable=str(value["executable"]),
                arguments=tuple(str(arg) for arg in value.get("arguments", [])),
                package=str(value.get("package", "")),
            )
            for runner_id, value in document.get("runners", {}).items()
        }
        systems = {
            system_id: SystemSpec(
                system_id=system_id,
                extensions=tuple(str(ext).lower().lstrip(".") for ext in value.get("extensions", [])),
                primary=str(value["primary"]),
                fallbacks=tuple(str(item) for item in value.get("fallbacks", [])),
                bios=tuple(str(item) for item in value.get("bios", [])),
            )
            for system_id, value in document.get("systems", {}).items()
        }
        for system in systems.values():
            for runner_id in (system.primary, *system.fallbacks):
                if runner_id not in runners:
                    raise ValueError(f"System {system.system_id} references unknown runner {runner_id}")
        return cls(runners, systems)

    def runner_candidates(self, system_id: str) -> tuple[RunnerSpec, ...]:
        system = self.systems[system_id]
        return tuple(self.runners[item] for item in (system.primary, *system.fallbacks))

