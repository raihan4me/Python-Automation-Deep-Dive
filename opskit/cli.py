"""Single entry point: opskit <command> [options]."""
import sys

from opskit import __version__

USAGE = """usage: opskit <command> [options]

commands:
  logs     summarise nginx access logs           (opskit.logparse)
  sys      disk, services, processes, archiving  (opskit.sysutil)
  api      inventory API client                  (opskit.api_client)
  docker   build/run/inspect lab containers      (opskit.dockerops)
  render   render, test and deploy nginx configs (opskit.render)
  fleet    SSH checks and file push              (opskit.remote)

run 'opskit <command> -h' for command help"""


def _commands():
    from opskit import api_client, dockerops, logparse, remote, render, sysutil
    return {"logs": logparse.main, "sys": sysutil.main, "api": api_client.main,
            "docker": dockerops.main, "render": render.main, "fleet": remote.main}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    if argv[0] == "--version":
        print(f"opskit {__version__}")
        return 0
    commands = _commands()
    if argv[0] not in commands:
        print(f"opskit: unknown command {argv[0]!r}\n\n{USAGE}", file=sys.stderr)
        return 1
    return commands[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main())
