import json

from focusblocks.config import CONFIG_VERSION, DEFAULT_CONFIG, TEST_OVERRIDES, ConfigStore, seed_test_config

from fakes import FakeNotifier


def test_first_load_writes_defaults(tmp_path):
    path = tmp_path / "config.json"
    cfg = ConfigStore(path, FakeNotifier()).load()
    assert cfg == dict(DEFAULT_CONFIG, config_version=CONFIG_VERSION)
    assert json.loads(path.read_text()) == cfg


def test_user_values_and_unknown_keys_are_kept(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"daily_goal": 4, "my_key": 1, "config_version": 2}))
    cfg = ConfigStore(path, FakeNotifier()).load()
    assert cfg["daily_goal"] == 4 and cfg["my_key"] == 1
    assert "block_minutes" in json.loads(path.read_text())


def test_v1_config_migrates_idle_seconds(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"idle_seconds": 120, "config_version": 1}))
    cfg = ConfigStore(path, FakeNotifier()).load()
    assert cfg["idle_seconds"] == DEFAULT_CONFIG["idle_seconds"]
    assert cfg["config_version"] == CONFIG_VERSION


def test_config_without_version_is_migrated_as_v1(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"idle_seconds": 120}))
    cfg = ConfigStore(path, FakeNotifier()).load()
    assert cfg["idle_seconds"] == DEFAULT_CONFIG["idle_seconds"]
    assert cfg["config_version"] == CONFIG_VERSION


def test_v1_migration_keeps_a_custom_idle_seconds(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"idle_seconds": 300, "config_version": 1}))
    assert ConfigStore(path, FakeNotifier()).load()["idle_seconds"] == 300


def test_broken_file_uses_defaults_and_is_not_overwritten(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ not json")
    notifier = FakeNotifier()
    cfg = ConfigStore(path, notifier).load()
    assert cfg["daily_goal"] == DEFAULT_CONFIG["daily_goal"]
    assert path.read_text() == "{ not json"
    assert notifier.titles == ["Settings not loaded"]


def test_reload_of_broken_file_returns_none_and_keeps_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ not json")
    notifier = FakeNotifier()
    assert ConfigStore(path, notifier).reload() is None
    assert path.read_text() == "{ not json"
    assert notifier.sent[0][0] == "Settings not reloaded"


def test_reload_returns_the_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"daily_goal": 4, "config_version": 2}))
    assert ConfigStore(path, FakeNotifier()).reload()["daily_goal"] == 4


def test_seed_test_config_inherits_work_sources(tmp_path):
    real, test = tmp_path / "real.json", tmp_path / "test" / "config.json"
    real.write_text(json.dumps({"work_apps": ["Code.exe"], "block_minutes": 50}))
    seed_test_config(test, real)
    cfg = json.loads(test.read_text())
    assert cfg["work_apps"] == ["Code.exe"]
    assert cfg["block_minutes"] == TEST_OVERRIDES["block_minutes"]


def test_seed_test_config_keeps_existing(tmp_path):
    test = tmp_path / "config.json"
    test.write_text("{}")
    seed_test_config(test, tmp_path / "missing.json")
    assert test.read_text() == "{}"


def test_wrong_types_fall_back_per_key(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"block_minutes": "25", "work_apps": "Code.exe", "daily_goal": 4,
                                "count_meetings": "yes", "config_version": 2}))
    notifier = FakeNotifier()
    cfg = ConfigStore(path, notifier).load()
    assert cfg["block_minutes"] == DEFAULT_CONFIG["block_minutes"]
    assert cfg["work_apps"] == DEFAULT_CONFIG["work_apps"]
    assert cfg["count_meetings"] is DEFAULT_CONFIG["count_meetings"]
    assert cfg["daily_goal"] == 4
    title, msg = notifier.sent[0]
    assert title == "Some settings were ignored"
    assert "block_minutes" in msg and "work_apps" in msg and "count_meetings" in msg


def test_out_of_range_values_fall_back(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"block_minutes": 0, "break_minutes": -1, "daily_goal": 0,
                                "break_mode": "popup", "config_version": 2}))
    cfg = ConfigStore(path, FakeNotifier()).load()
    for key in ("block_minutes", "break_minutes", "daily_goal", "break_mode"):
        assert cfg[key] == DEFAULT_CONFIG[key]


def test_ignored_values_stay_in_the_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"block_minutes": "25", "config_version": 2}))
    ConfigStore(path, FakeNotifier()).load()
    assert json.loads(path.read_text())["block_minutes"] == "25"   # left for the user to correct


def test_valid_numbers_are_kept(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"block_minutes": 50, "break_minutes": 0.5, "config_version": 2}))
    notifier = FakeNotifier()
    cfg = ConfigStore(path, notifier).load()
    assert (cfg["block_minutes"], cfg["break_minutes"]) == (50, 0.5)
    assert notifier.sent == []


def test_load_does_not_rewrite_an_up_to_date_file(tmp_path):
    path = tmp_path / "config.json"
    store = ConfigStore(path, FakeNotifier())
    cfg = store.load()
    path.write_text(json.dumps(cfg))            # same settings, the user's own formatting
    store.load()
    assert path.read_text() == json.dumps(cfg)


def test_lunch_time_must_be_hh_mm(tmp_path):
    for value, expected in (("12:30", "12:30"), ("", ""), ("25:00", ""), ("noon", ""), ("9:5", "")):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"lunch_time": value, "config_version": 2}))
        assert ConfigStore(path, FakeNotifier()).load()["lunch_time"] == expected, value


def test_v2_config_drops_the_camera_settings(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"camera_fallback": True, "camera_recheck_seconds": 120, "idle_seconds": 60,
                                "config_version": 2}))
    cfg = ConfigStore(path, FakeNotifier()).load()
    assert "camera_fallback" not in cfg and "camera_recheck_seconds" not in cfg
    assert cfg["idle_seconds"] == DEFAULT_CONFIG["idle_seconds"] == 180
    saved = json.loads(path.read_text())
    assert "camera_fallback" not in saved and saved["config_version"] == CONFIG_VERSION


def test_v2_migration_keeps_a_custom_idle_seconds(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"idle_seconds": 90, "config_version": 2}))
    assert ConfigStore(path, FakeNotifier()).load()["idle_seconds"] == 90
