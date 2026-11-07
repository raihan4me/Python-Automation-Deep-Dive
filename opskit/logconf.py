"""Central logging configuration: JSON results on stdout, diagnostics on stderr."""
import logging
import os
import sys

FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def setup_logging(level=None):
    """Level comes from the argument, OPSKIT_LOG_LEVEL, or INFO."""
    level = (level or os.environ.get("OPSKIT_LOG_LEVEL", "INFO")).upper()
    logging.basicConfig(level=level, format=FORMAT, stream=sys.stderr, force=True)
