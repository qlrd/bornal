# These tests drive areal ``Node/Cli```; only the process and
# the JSON-RPC transport are spied
import pytest

from bornal.cli import CliError
from bornal.testing import assert_wallet_roundtrip


def test_assert_wallet_roundtrip_cli(run_daemon, spy_popen, spy_rpc):
    node = run_daemon("bitcoin-core")
    assert_wallet_roundtrip(node)

    assert "createwallet" in spy_rpc.calls
    assert "generatetoaddress" in spy_rpc.calls
    assert "getbalance" in spy_rpc.calls


def test_assert_wallet_roundtrip_error(run_daemon, spy_popen, spy_rpc):
    node = run_daemon("bitcoin-core")

    def create_wallet(*args, **kwargs):
        raise CliError("not implemented")

    node.cli.create_wallet = create_wallet

    with pytest.raises(AssertionError, match="not implemented"):
        assert_wallet_roundtrip(node)
