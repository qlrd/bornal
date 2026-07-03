import logging

import pytest

from bornal import logger


def test_set_verbose_toggle_debug():
    logger.set_verbose(True)
    assert logger.LOG.level == logging.DEBUG


def test_set_verbose_toogle_info():
    logger.set_verbose(False)
    assert logger.LOG.level == logging.INFO


def test_fail_logs_and_exits(caplog):
    with pytest.raises(SystemExit) as exc:
        logger.fail("boom %s", "x")
    assert exc.value.code == 1
    assert "boom x" in caplog.text
