import os

import pytest

from bornal import daemon
from bornal.client import ClientError
from bornal.node import make_backend
from bornal.plugins import electrs
from bornal.plugins.bitcoind import BitcoindDaemon
from bornal.plugins.electrs import ElectrsClient, ElectrsCompiler, ElectrsDaemon


def test_register():
    registred = daemon.registry()
    assert "electrs" in registred
    assert isinstance(registred["electrs"], ElectrsCompiler)
    assert daemon.build_flag_for("electrs") == "--build-electrs"


def test_cargo_build_locked_release(paths, spy_build, electrs_compiler):
    paths.ensure()
    out = electrs_compiler.ensure(paths, revision="0.10.10")
    assert out == os.path.join(paths.binaries_dir, "electrs")
    assert os.path.exists(out)
    clone = next(c for c in spy_build if c[:2] == ["git", "clone"])
    assert "v0.10.10" in clone
    assert ["cargo", "build", "--locked", "--release"] in spy_build.calls


def test_is_latest(paths, spy_build, electrs_compiler):
    paths.ensure()
    electrs_compiler.ensure(paths)
    clone = next(c for c in spy_build if c[:2] == ["git", "clone"])
    assert "v0.10.10" in clone


def test_skip_rebuild(paths, spy_build, electrs_compiler):
    paths.ensure()
    electrs_compiler.ensure(paths, revision="0.10.10")
    built = len(spy_build.calls)
    electrs_compiler.ensure(paths, revision="0.10.10")
    assert len(spy_build.calls) == built


def test_cache_prefered(paths, spy_build, electrs_compiler, monkeypatch):
    paths.ensure()
    electrs_compiler.ensure(paths)

    def never_called():
        raise AssertionError("PATH lookup must not shadow the cache")

    monkeypatch.setattr(electrs, "_on_path", never_called)
    electrs_compiler.ensure(paths)


def test_from_path(paths, electrs_compiler, monkeypatch, tmp_path):
    fake = tmp_path / "electrs"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setattr(electrs, "_on_path", lambda: str(fake))
    out = electrs_compiler.ensure(paths)
    assert os.path.exists(out)
    assert electrs._read_build_meta(paths.binaries_dir) == {"revision": "path"}


def test_export_electrs_path(paths):
    env = daemon.get("electrs").env(paths)
    assert env["ELECTRS_PATH"] == paths.binaries_dir
    assert env["ELECTRS"] == os.path.join(paths.binaries_dir, "electrs")


def test_bitcoind_p2p_disabled(tmp_path):
    bitcoind = BitcoindDaemon("/bin", str(tmp_path), port=18443)
    assert bitcoind.p2p_port is None
    assert "-listen=0" in bitcoind.args()


def test_bitcoind_p2p_enabled(backend_daemon):
    argv = backend_daemon.args()
    assert backend_daemon.p2p_port == 18444
    assert "-listen=1" in argv
    assert "-bind=127.0.0.1:18444" in argv
    assert "-listen=0" not in argv


def test_require_bitcoind(tmp_path):
    electrsd = ElectrsDaemon("/bin", str(tmp_path), port=50001)
    with pytest.raises(RuntimeError, match="needs a bitcoind"):
        electrsd.start()


def test_require_p2p(tmp_path, electrs_daemon):
    no_p2p = BitcoindDaemon("/bin", str(tmp_path / "nop2p"), port=18443)
    assert electrs_daemon.attach_bitcoind(no_p2p) is electrs_daemon
    with pytest.raises(RuntimeError, match="p2p"):
        electrs_daemon.start()


def test_sttart_writes_conf(spy_popen, backend_daemon, electrs_daemon):
    electrs_daemon.start()
    assert spy_popen.processes[0].argv == [
        "/bin/electrs",
        "--conf",
        electrs_daemon.conf_file,
    ]
    with open(electrs_daemon.conf_file) as handle:
        conf = handle.read()
    assert 'daemon_dir = "%s"' % backend_daemon.datadir in conf
    assert 'auth = "bitcoin-core:bitcoin-core"' in conf
    assert 'daemon_rpc_addr = "127.0.0.1:18443"' in conf
    assert 'daemon_p2p_addr = "127.0.0.1:18444"' in conf
    assert 'network = "regtest"' in conf
    assert 'electrum_rpc_addr = "127.0.0.1:50001"' in conf
    assert 'monitoring_addr = "127.0.0.1:%d"' % electrs_daemon.monitoring_port in conf


def test_client(electrs_client, spy_electrum):
    assert electrs_client.url == "tcp://127.0.0.1:50001"
    assert electrs_client.is_up()
    assert "server.ping" in spy_electrum.calls


def test_client_helper(electrs_client):
    assert electrs_client.server_version() == ["electrs/0.10.10", "1.4"]
    assert electrs_client.banner() == "mocked electrs"
    assert electrs_client.get_tip() == {"height": 0, "hex": "00" * 80}
    assert electrs_client.block_header(0) == "00" * 80
    assert electrs_client.estimate_fee() == 0.0001


def test_unknown_method(electrs_client):
    with pytest.raises(ClientError, match="unknown method"):
        electrs_client.call("blockchain.not.a.method")


def test_client_down(electrs_client, spy_electrum):
    spy_electrum.down = True
    with pytest.raises(ClientError, match="unreachable"):
        electrs_client.call("server.ping")
    assert not electrs_client.is_up()


def test_connection_closed(electrs_client, spy_electrum):
    spy_electrum.raw_response = b""
    with pytest.raises(ClientError, match="connection closed"):
        electrs_client.call("server.ping")


def test_invalid_response(electrs_client, spy_electrum):
    spy_electrum.raw_response = b"not json\n"
    with pytest.raises(ClientError, match="invalid response"):
        electrs_client.call("server.ping")


def test_make_node_electrs(spy_popen, spy_electrum, tmp_path):
    backend = make_backend("bitcoin-core", "/bin", str(tmp_path / "b"), p2p_port=18444)
    node = make_backend("electrs", "/bin", str(tmp_path / "e"), bitcoind=backend.daemon)
    assert isinstance(node.daemon, ElectrsDaemon)
    assert isinstance(node.client, ElectrsClient)
    node.start()
    try:
        assert spy_popen.processes[0].argv[0] == "/bin/electrs"
        assert node.client.get_tip()["height"] == 0
    finally:
        node.stop()
    assert "stop" in spy_electrum.calls
    assert spy_popen.processes[0].terminated
