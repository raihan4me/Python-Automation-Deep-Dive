from opskit.render import ROOT, load_config, merged_env, render, validate

CFG = load_config(ROOT / "config" / "environments.yaml")


def test_valid_environments_pass():
    for name in ("staging", "prod"):
        assert validate(merged_env(CFG, name)) == []


def test_invalid_environment_reports_errors():
    data = merged_env(CFG, "staging")
    data["host_port"] = 70000
    del data["server_name"]
    errors = validate(data)
    assert "missing key: server_name" in errors
    assert any("host_port out of range" in e for e in errors)


def test_render_contains_headers_and_upstream():
    text = render(merged_env(CFG, "prod"), ROOT / "templates")
    assert 'add_header X-OpsKit-Env "prod" always;' in text
    assert "server opskit-mockapi:5000;" in text
