"""Render per-environment nginx configs from YAML + Jinja2, validate, test and deploy them."""
import argparse
import logging
import sys
import time
from pathlib import Path

import requests
import yaml
from docker.errors import ContainerError, DockerException
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from opskit.dockerops import LABEL, NETWORK, get_client, remove_if_exists
from opskit.logconf import setup_logging

log = logging.getLogger("opskit.render")
ROOT = Path(__file__).resolve().parent.parent
NGINX_IMAGE = "nginx:1.25.5-alpine"
CONF_PATH = "/etc/nginx/conf.d/default.conf"
REQUIRED = {"host_port": int, "server_name": str, "rate_limit_rps": int,
            "upstream_host": str, "upstream_port": int}


def load_config(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def merged_env(cfg, name):
    if name not in cfg.get("environments", {}):
        raise KeyError(f"unknown environment {name!r}")
    data = dict(cfg.get("defaults", {}))
    data.update(cfg["environments"][name])
    data["env_name"] = name
    return data


def validate(data):
    """Return a list of human-readable errors (empty list = valid)."""
    errors = []
    for key, typ in REQUIRED.items():
        if key not in data:
            errors.append(f"missing key: {key}")
            continue
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, typ):
            errors.append(f"{key} must be {typ.__name__}, got {type(value).__name__}")
    for key in ("host_port", "upstream_port"):
        value = data.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and not 1 <= value <= 65535:
            errors.append(f"{key} out of range: {value}")
    rps = data.get("rate_limit_rps")
    if isinstance(rps, int) and not isinstance(rps, bool) and rps <= 0:
        errors.append("rate_limit_rps must be > 0")
    return errors


def render(data, template_dir, template_name="nginx.conf.j2"):
    env = Environment(loader=FileSystemLoader(str(template_dir)), undefined=StrictUndefined,
                      trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    return env.get_template(template_name).render(**data)


def write_if_changed(path, text):
    """Write only when content differs. Returns True if the file changed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def nginx_test(client, conf_path):
    """Run 'nginx -t' against the rendered file in a throwaway container on the app network."""
    try:
        out = client.containers.run(
            NGINX_IMAGE, ["nginx", "-t"], remove=True, stdout=True, stderr=True,
            volumes={str(conf_path): {"bind": CONF_PATH, "mode": "ro"}},
            network=NETWORK, environment={"NGINX_ENTRYPOINT_QUIET_LOGS": "1"},
        )
        return True, out.decode(errors="replace")
    except ContainerError as exc:
        return False, exc.stderr.decode(errors="replace") if exc.stderr else str(exc)


def deploy_proxy(client, env_name, conf_path, host_port):
    name = f"opskit-proxy-{env_name}"
    remove_if_exists(client, name)
    client.containers.run(
        NGINX_IMAGE, name=name, detach=True, ports={"80/tcp": host_port},
        volumes={str(conf_path): {"bind": CONF_PATH, "mode": "ro"}},
        network=NETWORK, labels={**LABEL, "opskit.env": env_name},
        environment={"NGINX_ENTRYPOINT_QUIET_LOGS": "1"},
        restart_policy={"Name": "unless-stopped"},
    )
    url = f"http://127.0.0.1:{host_port}/health"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            if requests.get(url, timeout=2).status_code == 200:
                log.info("%s: proxy live on %s", env_name, url)
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    log.error("%s: proxy did not become ready at %s", env_name, url)
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(prog="opskit render", description="Render/test/deploy nginx configs")
    parser.add_argument("envs", nargs="+")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "environments.yaml")
    parser.add_argument("--out", type=Path, default=ROOT / "build")
    parser.add_argument("--test", action="store_true", help="run nginx -t in a throwaway container")
    parser.add_argument("--deploy", action="store_true", help="(re)create the proxy; implies --test")
    args = parser.parse_args(argv)
    setup_logging()

    cfg = load_config(args.config)
    client, failed = None, False
    for name in args.envs:
        try:
            data = merged_env(cfg, name)
        except KeyError as exc:
            log.error("%s", exc.args[0])
            failed = True
            continue
        errors = validate(data)
        if errors:
            for err in errors:
                log.error("%s: %s", name, err)
            failed = True
            continue
        conf = (args.out / name / "default.conf").resolve()
        changed = write_if_changed(conf, render(data, ROOT / "templates"))
        log.info("%s: %s %s", name, "updated" if changed else "unchanged", conf)
        if not (args.test or args.deploy):
            continue
        if client is None:
            try:
                client = get_client()
            except DockerException as exc:
                log.error("cannot talk to Docker: %s", exc)
                return 1
        ok, msg = nginx_test(client, conf)
        if not ok:
            log.error("%s: nginx -t failed:\n%s", name, msg.strip())
            failed = True
            continue
        log.info("%s: nginx -t passed", name)
        if args.deploy and not deploy_proxy(client, name, conf, data["host_port"]):
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
