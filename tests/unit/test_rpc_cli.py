import base64
import io
import json
import urllib.error

import pytest

from bornal.cli import CliError


def test_fail_basic_noauth_header(mocked_cli_noauth, mocked_rpc):
    with pytest.raises(CliError, match="Not authorized"):
        mocked_cli_noauth.call("getblockchaininfo")
    assert mocked_rpc.req is None


def test_basic_auth_header(mocked_cli, mocked_rpc):
    mocked_cli.call("getblockchaininfo")
    req, res = mocked_rpc.req, mocked_rpc.res
    assert req.method == "POST"
    assert req.full_url == "http://127.0.0.1:5555"
    auth = req.get_header("Authorization")
    assert auth == "Basic %s" % base64.b64encode(b"mocku:liar").decode()
    assert json.loads(req.data) == {
        "jsonrpc": "1.0",
        "id": "bornal",
        "method": "getblockchaininfo",
        "params": [],
    }
    assert res["result"]["chain"] == "mocktest"
    assert not res["error"]


def test_not_implemented(mocked_cli, mocked_rpc):
    with pytest.raises(CliError, match="not implemented"):
        mocked_cli.call("h")
    req, res = mocked_rpc.req, mocked_rpc.res
    assert req.method == "POST"
    assert req.full_url == "http://127.0.0.1:5555"
    assert json.loads(req.data) == {
        "jsonrpc": "1.0",
        "id": "bornal",
        "method": "h",
        "params": [],
    }
    assert res["result"] is None
    assert res["error"] == "not implemented"


def test_payload(mocked_cli, mocked_rpc):
    mocked_cli.call("getblockcount")
    req, res = mocked_rpc.req, mocked_rpc.res
    assert req.method == "POST"
    assert req.full_url == "http://127.0.0.1:5555"
    assert json.loads(req.data) == {
        "jsonrpc": "1.0",
        "id": "bornal",
        "method": "getblockcount",
        "params": [],
    }
    assert res["result"] == 21
    assert not res["error"]


def test_generatetoaddress(mocked_cli, mocked_rpc):
    hashes = mocked_cli.call("generatetoaddress", 101, "bcrt1qaddr")
    req, res = mocked_rpc.req, mocked_rpc.res
    assert req.method == "POST"
    assert req.full_url == "http://127.0.0.1:5555"
    assert json.loads(req.data) == {
        "jsonrpc": "1.0",
        "id": "bornal",
        "method": "generatetoaddress",
        "params": [101, "bcrt1qaddr"],
    }
    assert hashes == res["result"]
    assert len(hashes) == 101
    assert all(len(block_hash) == 64 for block_hash in hashes)
    assert not res["error"]


def test_error_response_raises(mocked_cli, mocked_rpc):
    with pytest.raises(CliError, match="need 2 or 3 params, provided 1"):
        mocked_cli.call("generatetoaddress", 101)


def test_clierror_internal(mocked_cli, monkeypatch):
    def rpc_error(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url,
            500,
            "Internal Server Error",
            {},
            io.BytesIO(json.dumps({"error": {"message": "rpc fail"}}).encode()),
        )

    monkeypatch.setattr("urllib.request.urlopen", rpc_error)
    with pytest.raises(CliError, match="rpc fail"):
        mocked_cli.call("getblockcount")


def test_httperror(mocked_cli, monkeypatch):
    def handle(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 503, "handle", {}, io.BytesIO(b"not json")
        )

    monkeypatch.setattr("urllib.request.urlopen", handle)
    with pytest.raises(CliError, match="HTTP 503"):
        mocked_cli.call("getblockcount")


def test_urlerror(mocked_cli, monkeypatch):
    def refused(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", refused)
    with pytest.raises(CliError, match="unreachable"):
        mocked_cli.call("getblockcount")


def test_is_up_(mocked_cli, monkeypatch):
    assert mocked_cli.is_up() is True

    def down(req, timeout=None):
        raise urllib.error.URLError("down")

    monkeypatch.setattr("urllib.request.urlopen", down)
    assert mocked_cli.is_up() is False


def test_wait_until_up(mocked_cli):
    mocked_cli.wait_until_up(timeout=1)


def test_timeout(mocked_cli, monkeypatch):
    def handle(req, timeout=None):
        raise urllib.error.URLError("mocku")

    monkeypatch.setattr("urllib.request.urlopen", handle)
    with pytest.raises(CliError, match="not up"):
        mocked_cli.wait_until_up(timeout=0)
