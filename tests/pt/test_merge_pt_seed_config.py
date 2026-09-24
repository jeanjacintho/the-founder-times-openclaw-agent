"""runtime/config.yaml reaches the seed whole; the seed keeps what we don't set."""
import yaml

from conftest import ROOT, load_module

merge = load_module("pt_merge_seed", "image/merge_pt_seed_config.py")

# The base seed's shape (base-ef00193): glm default, loud plow_chat, its own
# disabled toolsets and keys runtime/config.yaml never mentions.
BASE_SEED = {
    "agent": {"disabled_toolsets": ["clarify", "browser"], "api_max_retries": 9},
    "cron": {"model_drift_guard": False},
    "model": {"default": "z-ai/glm-5.2", "provider": "plow"},
    "providers": {"plow": {"name": "plow", "models": {"z-ai/glm-5.2": {}}}},
    "display": {
        "memory_notifications": "on",
        "platforms": {"plow_chat": {"tool_progress": "off", "long_running_notifications": True}},
    },
    "terminal": {"backend": "local", "cwd": "/var/lib/hermes"},
}


def test_every_runtime_key_lands_on_the_seed(tmp_path):
    seed = tmp_path / "config.yaml"
    seed.write_text(yaml.safe_dump(BASE_SEED))
    merge.main([str(seed), str(ROOT / "runtime" / "config.yaml")])
    out = yaml.safe_load(seed.read_text())

    assert out["model"]["default"] == "anthropic/claude-opus-5"
    assert set(out["providers"]["plow"]["models"]) == {"z-ai/glm-5.2", "anthropic/claude-opus-5"}
    assert out["context_file_max_chars"] == 40000
    assert out["cron"] == {"model_drift_guard": False, "wrap_response": False}
    assert out["agent"] == {"disabled_toolsets": ["clarify", "web", "search", "browser"],
                            "api_max_retries": 9}
    assert out["terminal"] == {"backend": "local", "cwd": "/var/lib/hermes"}
    pc = out["display"]["platforms"]["plow_chat"]
    assert out["display"]["memory_notifications"] == "on"
    assert out["display"]["tool_progress"] == "off" and pc["tool_progress"] == "off"
    assert out["display"]["live_status"] == "off" and pc["live_status"] == "off"
    assert pc["interim_assistant_messages"] is False
    assert pc["long_running_notifications"] is False
