import json
import os

import pytest

from bornal import daemon
from bornal.daemon import CompilerError
from bornal.plugins import floresta
from bornal.node import IntegrationTest, make_backend
from bornal.plugins.floresta import (
    FlorestaClient,
    FlorestaCompiler,
    FlorestaDaemon,
    FlorestaElectrumClient,
)


def test_register():
    registred = daemon.registry()
    assert "floresta" in registred
    assert isinstance(registred["floresta"], FlorestaCompiler)
    assert daemon.build_flag_for("floresta") == "--build-floresta"


def test_cargo_build_locked_release_bin(paths, spy_build, floresta_compiler):
    paths.ensure()
    out = floresta_compiler.ensure(paths, revision="0.9.1")
    assert out == os.path.join(paths.binaries_dir, "florestad")
    assert os.path.exists(out)
    clone = next(c for c in spy_build if c[:2] == ["git", "clone"])
    assert "v0.9.1" in clone
    assert [
        "cargo",
        "build",
        "--locked",
        "--release",
        "--bin",
        "florestad",
    ] in spy_build.calls


def test_is_latest(paths, spy_build, floresta_compiler):
    paths.ensure()
    floresta_compiler.ensure(paths)
    clone = next(c for c in spy_build if c[:2] == ["git", "clone"])
    assert "v0.9.1" in clone
    assert floresta_compiler.read_build_meta(paths) == {"revision": "latest"}


def test_skip_rebuild(paths, spy_build, floresta_compiler):
    paths.ensure()
    floresta_compiler.ensure(paths, revision="0.9.1")
    built = len(spy_build.calls)
    floresta_compiler.ensure(paths, revision="0.9.1")
    assert len(spy_build.calls) == built


def test_rebuild_other_revision(paths, spy_build, floresta_compiler):
    paths.ensure()
    floresta_compiler.ensure(paths, revision="0.9.1")
    built = len(spy_build.calls)
    floresta_compiler.ensure(paths, revision="0.9.0")
    assert len(spy_build.calls) > built
    assert floresta_compiler.read_build_meta(paths) == {"revision": "0.9.0"}


def test_cache_prefered(paths, spy_build, floresta_compiler, monkeypatch):
    paths.ensure()
    floresta_compiler.ensure(paths)

    def never_called(self):
        raise AssertionError("PATH lookup must not shadow the cache")

    monkeypatch.setattr(FlorestaCompiler, "on_path", never_called)
    floresta_compiler.ensure(paths)


def test_from_path(paths, floresta_compiler, monkeypatch, tmp_path):
    fake = tmp_path / "florestad"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setattr(FlorestaCompiler, "on_path", lambda self: str(fake))
    out = floresta_compiler.ensure(paths)
    assert os.path.exists(out)
    assert floresta_compiler.read_build_meta(paths) == {"revision": "path"}


def test_export_floresta_path(paths):
    env = daemon.get("floresta").env(paths)
    assert env["FLORESTA_PATH"] == paths.binaries_dir
    assert env["FLORESTAD"] == os.path.join(paths.binaries_dir, "florestad")


def test_args(floresta_daemon):
    assert floresta_daemon.args() == [
        "--network=regtest",
        "--data-dir=%s" % floresta_daemon.datadir,
        "--rpc-address=127.0.0.1:18442",
        "--electrum-address=127.0.0.1:20001",
        "--disable-dns-seeds",
        "--log-to-file",
    ]
    assert floresta_daemon.connect is None


def test_args_connect(tmp_path):
    florestad = FlorestaDaemon("/bin", str(tmp_path), connect="127.0.0.1:18444")
    assert florestad.connect == "127.0.0.1:18444"
    assert florestad.args()[-1] == "--connect=127.0.0.1:18444"


def test_electrum_port_reserved(tmp_path):
    one = FlorestaDaemon("/bin", str(tmp_path / "a"))
    other = FlorestaDaemon("/bin", str(tmp_path / "b"))
    assert one.electrum_port not in (one.port, 20001)
    assert one.electrum_port != other.electrum_port


def test_client_without_auth(floresta_daemon, spy_floresta_rpc):
    client = floresta_daemon.make_client()
    assert isinstance(client, FlorestaClient)
    assert client.is_up()
    req = spy_floresta_rpc.req
    assert req.get_header("Authorization") is None
    assert req.full_url == "http://127.0.0.1:18442"
    assert json.loads(req.data)["jsonrpc"] == "2.0"


def test_client_helpers(floresta_daemon, spy_floresta_rpc):
    client = floresta_daemon.make_client()
    assert client.get_blockchain_info()["chain"] == "regtest"
    assert client.get_block_count() == 0
    assert client.get_best_block_hash() == "00" * 32
    assert client.get_block_hash(0) == "00" * 32
    assert client.get_block_header("00" * 32) == {"height": 0}
    assert client.get_block("00" * 32) == {"height": 0}
    assert client.get_roots() == []
    assert client.uptime() == 1
    assert client.ping() is None
    client.add_node("127.0.0.1:18444")
    assert json.loads(spy_floresta_rpc.req.data)["params"] == [
        "127.0.0.1:18444",
        "onetry",
        False,
    ]
    assert client.get_peer_info() == [{"id": 0, "addr": "127.0.0.1:18444"}]
    assert client.disconnect_node("127.0.0.1:18444") is None
    assert client.stop() == "Floresta stopping"


def test_make_backend(spy_popen, spy_floresta_rpc, tmp_path):
    node = make_backend("floresta", "/bin", str(tmp_path / "f"))
    assert isinstance(node.daemon, FlorestaDaemon)
    node.start()
    try:
        assert spy_popen.processes[0].argv[0] == "/bin/florestad"
    finally:
        node.stop()
    assert spy_popen.processes[0].terminated
    assert "stop" not in spy_floresta_rpc.calls


def test_integration_connect_kwarg(spy_popen, tmp_path):
    class CoreFloresta(IntegrationTest):
        def set_test_params(self):
            self.add_backend("bitcoin-core", p2p_port=18444)
            self.add_backend("floresta", connect="127.0.0.1:18444")

        def run_test(self):
            pass

    test = CoreFloresta("/bin", str(tmp_path))
    test._on_set_test_params()
    _, florestad = test.backends
    assert florestad.daemon.connect == "127.0.0.1:18444"
    assert "--connect=127.0.0.1:18444" in florestad.daemon.args()


def test_electrum_client(floresta_daemon, spy_floresta_electrum):
    electrum = floresta_daemon.make_electrum_client()
    assert isinstance(electrum, FlorestaElectrumClient)
    assert electrum.url == "tcp://127.0.0.1:20001"
    assert electrum.is_up()
    assert "server.ping" in spy_floresta_electrum.calls


def test_electrum_client_helpers(floresta_daemon, spy_floresta_electrum):
    electrum = floresta_daemon.make_electrum_client()
    scripthash = "ab" * 32
    assert electrum.server_version() == ["Floresta 0.9.1", "1.4"]
    assert electrum.banner() == "Welcome to Floresta's Electrum Server."
    assert electrum.features()["server_version"] == "Floresta 0.9.1"
    assert electrum.relay_fee() == 0.00001
    assert electrum.get_tip() == {"height": 0, "hex": "00" * 80}
    assert electrum.block_headers(0, 1)["count"] == 1
    assert spy_floresta_electrum.payloads[-1]["params"] == [0, 1]
    assert electrum.get_balance(scripthash) == {"confirmed": 0, "unconfirmed": 0}
    assert electrum.get_history(scripthash) == []
    assert electrum.list_unspent(scripthash) == []
    assert spy_floresta_electrum.payloads[-1]["params"] == [scripthash]
    assert electrum.get_transaction("11" * 32) == "02" * 10
    assert electrum.broadcast("02" * 10) == "11" * 32


def test_parse_revision():
    assert floresta.parse_revision("0.9.1") == (0, 9, 1)
    assert floresta.parse_revision("v0.10.0") == (0, 10, 0)
    assert floresta.parse_revision("master") is None
    assert floresta.parse_revision("e85b995") is None


def test_refuse_older_than_0_9_0(paths, spy_build, floresta_compiler):
    paths.ensure()
    with pytest.raises(SystemExit):
        floresta_compiler.ensure(paths, revision="0.8.1")
    assert not any(c[:2] == ["git", "clone"] for c in spy_build)
    assert not os.path.exists(floresta_compiler.dest(paths))


def test_check_revision(floresta_compiler):
    floresta_compiler.check_revision("0.9.0")
    floresta_compiler.check_revision("master")  # not a release: unchecked
    with pytest.raises(CompilerError, match=r"floresta >= 0.9.0 is required"):
        floresta_compiler.check_revision("0.7.0")


def test_ensure_builds_with_boost_env(paths, spy_build, floresta_compiler, monkeypatch):
    envs = []

    def spy_run(argv, cwd=None, env=None):
        envs.append(env)
        spy_build.run(argv, cwd=cwd, env=env)

    steered = {"CMAKE_TOOLCHAIN_FILE": "/tmp/bornal-boost.cmake"}
    monkeypatch.setattr(floresta, "run", spy_run)
    monkeypatch.setattr(
        FlorestaCompiler, "build_env", lambda self, rev, workdir: steered
    )
    paths.ensure()
    floresta_compiler.ensure(paths, revision="0.9.1")
    assert envs == [steered]


def test_boost_version(boost_prefixes, tmp_path):
    assert floresta.boost_version(boost_prefixes(tmp_path / "b", "1.85")) == (1, 85)
    assert floresta.boost_version(str(tmp_path / "missing")) is None
    garbage = tmp_path / "g" / "include" / "boost"
    garbage.mkdir(parents=True)
    (garbage / "version.hpp").write_text("// no version\n")
    assert floresta.boost_version(str(tmp_path / "g")) is None


def test_boost_roots_order(boost_prefixes, monkeypatch, tmp_path):
    brew = boost_prefixes.brew / "opt"
    default = boost_prefixes(brew / "boost", "1.92")
    old = boost_prefixes(brew / "boost@1.85", "1.85")
    older = boost_prefixes(brew / "boost@1.74", "1.74")
    # brew leaves stale aliases to the current keg
    os.symlink(default, brew / "boost@1.90")
    assert floresta.boost_roots() == [default, old, older]
    explicit = boost_prefixes(tmp_path / "explicit", "1.80")
    monkeypatch.setenv("BOOST_ROOT", explicit)
    assert floresta.boost_roots()[0] == explicit


def test_brew_prefix(monkeypatch):
    monkeypatch.setattr(floresta.shutil, "which", lambda name: None)
    assert floresta._brew_prefix() is None

    class Done:
        stdout = "/opt/homebrew\n"

    monkeypatch.setattr(floresta.shutil, "which", lambda name: "/bin/brew")
    monkeypatch.setattr(floresta.subprocess, "run", lambda *a, **k: Done())
    assert floresta._brew_prefix() == "/opt/homebrew"


def test_select_boost_default_is_fine(boost_prefixes, floresta_compiler):
    boost_prefixes(boost_prefixes.brew / "opt" / "boost", "1.85")
    assert floresta_compiler.select_boost("0.9.1") is None


def test_select_boost_steers_to_older_keg(boost_prefixes, floresta_compiler):
    brew = boost_prefixes.brew / "opt"
    boost_prefixes(brew / "boost", "1.92")
    old = boost_prefixes(brew / "boost@1.85", "1.85")
    assert floresta_compiler.select_boost("0.9.0") == old
    assert floresta_compiler.select_boost("0.9.1") == old


def test_select_boost_unknown_line(boost_prefixes, floresta_compiler):
    boost_prefixes(boost_prefixes.brew / "opt" / "boost", "1.92")
    assert floresta_compiler.select_boost("0.10.0") is None
    assert floresta_compiler.select_boost("master") is None


def test_select_boost_none_usable(boost_prefixes, floresta_compiler):
    boost_prefixes(boost_prefixes.brew / "opt" / "boost", "1.92")
    with pytest.raises(CompilerError, match=r"does not build with Boost >= 1.92") as e:
        floresta_compiler.select_boost("0.9.1")
    causes = [str(c) for c in e.value.exceptions]
    assert any("Boost 1.92 at" in c for c in causes)
    assert any("brew install boost@1.85" in c for c in causes)


def test_select_boost_missing(boost_prefixes, floresta_compiler):
    with pytest.raises(CompilerError, match="needs Boost headers"):
        floresta_compiler.select_boost("0.9.1")


def test_select_boost_explicit(
    boost_prefixes, floresta_compiler, monkeypatch, tmp_path
):
    boost_prefixes(boost_prefixes.brew / "opt" / "boost", "1.92")
    good = boost_prefixes(tmp_path / "good", "1.85")
    monkeypatch.setenv("BOOST_ROOT", good)
    # forced even when compatible: brew's lookup would override it on macOS
    assert floresta_compiler.select_boost("0.9.1") == good
    # an explicit incompatible root is refused, not silently replaced
    boost_prefixes(boost_prefixes.brew / "opt" / "boost@1.85", "1.85")
    bad = boost_prefixes(tmp_path / "bad", "1.92")
    monkeypatch.setenv("BOOST_ROOT", bad)
    with pytest.raises(CompilerError, match=r"\$BOOST_ROOT does not build"):
        floresta_compiler.select_boost("0.9.1")


def test_build_env_toolchain(boost_prefixes, floresta_compiler, tmp_path):
    brew = boost_prefixes.brew / "opt"
    boost_prefixes(brew / "boost", "1.92")
    old = boost_prefixes(brew / "boost@1.85", "1.85")
    env = floresta_compiler.build_env("0.9.1", str(tmp_path))
    toolchain = env["CMAKE_TOOLCHAIN_FILE"]
    assert toolchain == str(tmp_path / "bornal-boost.cmake")
    with open(toolchain) as handle:
        content = handle.read()
    assert "set(HOMEBREW_EXECUTABLE" in content
    assert 'list(PREPEND CMAKE_PREFIX_PATH "%s")' % old in content
    assert env["PATH"] == os.environ["PATH"]


def test_build_env_default(boost_prefixes, floresta_compiler, tmp_path):
    boost_prefixes(boost_prefixes.brew / "opt" / "boost", "1.85")
    assert floresta_compiler.build_env("0.9.1", str(tmp_path)) is None
    assert not (tmp_path / "bornal-boost.cmake").exists()
