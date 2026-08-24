# These tests drive a real ``Node/Client```; only the process and
# the JSON-RPC transport are spied
import pytest

from bornal.client import ClientError
from bornal.testing import assert_wallet_roundtrip


def test_assert_wallet_roundtrip_cli(run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    assert_wallet_roundtrip(node)

    assert "createwallet" in spy_rpc.calls
    assert "generatetoaddress" in spy_rpc.calls
    assert "getbalance" in spy_rpc.calls


def test_assert_wallet_roundtrip_error(run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")

    def create_wallet(*args, **kwargs):
        raise ClientError("not implemented")

    node.client.create_wallet = create_wallet

    with pytest.raises(AssertionError, match="not implemented"):
        assert_wallet_roundtrip(node)
