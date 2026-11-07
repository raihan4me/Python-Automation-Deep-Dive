"""Manage opskit containers with the Docker SDK for Python."""
import argparse
import json
import logging
import sys
import time
from pathlib import Path

import docker
from docker.errors import APIError, BuildError, DockerException, NotFound

from opskit.logconf import setup_logging

log = logging.getLogger("opskit.docker")
ROOT = Path(__file__).resolve().parent.parent
LABEL = {"opskit.managed": "true"}
NETWORK = "opskit-net"
API_IMAGE = "opskit/mockapi:1.0"
API_NAME = "opskit-mockapi"


def get_client():
    return docker.from_env()


def ensure_network(client, name=NETWORK):
    existing = [n for n in client.networks.list() if n.name == name]
    if existing:
        return existing[0]
    log.info("creating network %s", name)
    return client.networks.create(name, driver="bridge", labels=LABEL)


def build_image(client, path, tag):
    log.info("building %s from %s", tag, path)
    image, logs = client.images.build(path=str(path), tag=tag, rm=True, labels=LABEL)
    for chunk in logs:
        line = chunk.get("stream", "").strip()
        if line:
            log.debug(line)
    return image


def remove_if_exists(client, name):
    try:
        container = client.containers.get(name)
    except NotFound:
        return False
    log.info("removing existing container %s", name)
    container.remove(force=True)
    return True


def wait_healthy(container, timeout=60):
    """Poll Docker's health status until healthy."""
    start = time.monotonic()
    deadline = start + timeout
    while time.monotonic() < deadline:
        container.reload()
        state = container.attrs["State"]
        if state.get("Health", {}).get("Status") == "healthy":
            return int(time.monotonic() - start)
        if state["Status"] in ("exited", "dead"):
            raise RuntimeError(f"container {container.name} stopped: {state['Status']}")
        time.sleep(2)
    raise TimeoutError(f"{container.name} not healthy after {timeout}s")


def deploy_mockapi(client, host_port=8081, flaky_every=0):
    """Converge on one running container. Returns (container, changed)."""
    ensure_network(client)
    image = build_image(client, ROOT / "mockapi", API_IMAGE)
    try:
        current = client.containers.get(API_NAME)
        env = current.attrs["Config"]["Env"] or []
        binds = current.ports.get("5000/tcp") or []
        if (current.status == "running" and current.image.id == image.id
                and f"FLAKY_EVERY={flaky_every}" in env
                and any(b["HostPort"] == str(host_port) for b in binds)):
            log.info("%s: unchanged", API_NAME)
            return current, False
    except NotFound:
        pass
    remove_if_exists(client, API_NAME)
    container = client.containers.run(
        API_IMAGE, name=API_NAME, detach=True,
        ports={"5000/tcp": host_port},
        environment={"FLAKY_EVERY": str(flaky_every)},
        network=NETWORK, labels=LABEL,
        restart_policy={"Name": "unless-stopped"},
    )
    log.info("started %s (%s), waiting for health", container.name, container.short_id)
    waited = wait_healthy(container)
    log.info("%s is healthy after %ss", container.name, waited)
    return container, True


def status(client):
    rows = []
    for c in client.containers.list(all=True, filters={"label": "opskit.managed=true"}):
        health = c.attrs["State"].get("Health", {}).get("Status", "n/a")
        ports = ", ".join(f"{binds[0]['HostPort']}->{cport}"
                          for cport, binds in (c.ports or {}).items() if binds)
        rows.append({"name": c.name, "image": c.image.tags[0] if c.image.tags else c.image.short_id,
                     "status": c.status, "health": health, "ports": ports})
    return sorted(rows, key=lambda r: r["name"])


def destroy(client):
    for c in client.containers.list(all=True, filters={"label": "opskit.managed=true"}):
        log.info("removing container %s", c.name)
        c.remove(force=True)
    for n in client.networks.list(filters={"label": "opskit.managed=true"}):
        log.info("removing network %s", n.name)
        n.remove()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="opskit docker", description="Manage opskit containers")
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("deploy-api", help="build and (re)start the inventory API container")
    d.add_argument("--port", type=int, default=8081)
    d.add_argument("--flaky", type=int, default=0)
    sub.add_parser("status", help="list opskit-managed containers")
    lg = sub.add_parser("logs", help="show container logs")
    lg.add_argument("name")
    lg.add_argument("--tail", type=int, default=20)
    sub.add_parser("destroy", help="remove all opskit-managed containers and networks")
    args = parser.parse_args(argv)
    setup_logging()

    try:
        client = get_client()
        if args.cmd == "deploy-api":
            deploy_mockapi(client, args.port, args.flaky)
            print(json.dumps(status(client), indent=2, sort_keys=True))
        elif args.cmd == "status":
            print(json.dumps(status(client), indent=2, sort_keys=True))
        elif args.cmd == "logs":
            print(client.containers.get(args.name).logs(tail=args.tail).decode(errors="replace"), end="")
        else:
            destroy(client)
    except NotFound as exc:
        log.error("not found: %s", exc.explanation)
        return 1
    except (BuildError, APIError, TimeoutError, RuntimeError) as exc:
        log.error("%s: %s", type(exc).__name__, exc)
        return 1
    except DockerException as exc:
        log.error("cannot talk to Docker: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
