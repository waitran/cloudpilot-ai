import logging


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # Driver/engine exceptions can contain connection details; log only safe application events.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
