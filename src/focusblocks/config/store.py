"""Loading, migrating and saving config.json."""

from __future__ import annotations

import json
from pathlib import Path

from focusblocks.config.defaults import (
    CHOICES,
    CONFIG_VERSION,
    DEFAULT_CONFIG,
    POSITIVE_KEYS,
    TEST_INHERITED_KEYS,
    TEST_OVERRIDES,
)
from focusblocks.core.models import Config, parse_clock
from focusblocks.core.ports import Notifier

OLD_IDLE_SECONDS = {1: 120, 2: 60}         # idle_seconds default up to that config version
REMOVED_KEYS = ("camera_fallback", "camera_recheck_seconds")   # v3: the webcam check is gone


def migrate(cfg: Config, version: int) -> Config:
    """Bring a config written as `version` up to CONFIG_VERSION. Only touch values the user never changed."""
    if version < CONFIG_VERSION and cfg.get("idle_seconds") == OLD_IDLE_SECONDS.get(version):
        cfg["idle_seconds"] = DEFAULT_CONFIG["idle_seconds"]
    for key in REMOVED_KEYS:
        cfg.pop(key, None)
    cfg["config_version"] = CONFIG_VERSION
    return cfg


def _valid(key: str, value: object) -> bool:
    default = DEFAULT_CONFIG[key]
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, (int, float)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        return value > 0 if key in POSITIVE_KEYS else value >= 0
    if isinstance(default, list):
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    if key == "lunch_time":
        return value == "" or parse_clock(value) is not None
    if isinstance(default, str):
        return isinstance(value, str) and value in CHOICES.get(key, (value,))
    return True


def validate(cfg: Config) -> tuple[Config, list[str]]:
    """Swap any value of the wrong type or out of range for its default. Returns (fixed copy, bad keys)."""
    bad = [key for key in DEFAULT_CONFIG if not _valid(key, cfg[key])]
    return dict(cfg, **{key: DEFAULT_CONFIG[key] for key in bad}), bad


class ConfigStore:
    def __init__(self, path: Path, notifier: Notifier):
        self.path = path
        self._notifier = notifier

    def load(self) -> Config:
        """Defaults overlaid with the user's file. On a broken file, the defaults (the file is left alone)."""
        cfg, error = self._read()
        if cfg is None:
            self._notifier.notify("Settings not loaded", f"config.json has an error ({error}). Using defaults.")
            return dict(DEFAULT_CONFIG, config_version=CONFIG_VERSION)
        return cfg

    def reload(self) -> Config | None:
        """Like load, but None on a broken file so the running settings stay as they are."""
        cfg, error = self._read()
        if cfg is None:
            self._notifier.notify("Settings not reloaded",
                                  f"config.json has an error ({error}). Keeping current settings.")
        return cfg

    def _read(self) -> tuple[Config | None, Exception | None]:
        """Read, migrate and validate the file. (None, error) if it can't be parsed.

        The file is written back only when migration or new keys changed it, and bad values stay
        in it for the user to correct: only the returned settings use the defaults for those.
        """
        self.path.parent.mkdir(exist_ok=True)
        try:
            user = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(user, dict):
                raise ValueError("expected an object { ... }")
        except FileNotFoundError:
            user = {"config_version": CONFIG_VERSION}
        except Exception as e:
            return None, e                 # don't overwrite a file the user is editing
        cfg = migrate(dict(DEFAULT_CONFIG, **user), user.get("config_version", 1))
        if cfg != user:
            self.save(cfg)
        cfg, bad = validate(cfg)
        if bad:
            self._notifier.notify("Some settings were ignored",
                                  f"Using defaults for: {', '.join(bad)}. Check their values in config.json.")
        return cfg, None

    def save(self, cfg: Config) -> None:
        self.path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def seed_test_config(test_path: Path, real_path: Path) -> None:
    """Create the test-mode config once: fast timings, plus your real work sources."""
    if test_path.exists():
        return
    test_path.parent.mkdir(exist_ok=True)
    cfg = dict(DEFAULT_CONFIG, **TEST_OVERRIDES, config_version=CONFIG_VERSION)
    try:
        real = json.loads(real_path.read_text(encoding="utf-8"))
        for key in TEST_INHERITED_KEYS:
            if key in real:
                cfg[key] = real[key]
    except Exception:
        pass
    test_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
