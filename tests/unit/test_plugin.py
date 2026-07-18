import os

from bornal import fixtures


def test_default_options(pytestconfig):
    assert pytestconfig.getoption("bornal_wallet") is False
    assert pytestconfig.getoption("bornal_force_build") is False
    assert pytestconfig.getoption("bornal_preserve_data") is False
    assert pytestconfig.getoption("bornal_nproc") is None
    assert pytestconfig.getoption("bornal_build_bitcoin_core") is None
    assert fixtures._build_dest("bitcoin-core") == "bornal_build_bitcoin_core"


def test_latest(prepare_run_minimal):
    calls, tmp, paths = prepare_run_minimal("latest")
    assert calls[0]["daemons"] == ["bitcoin-core"]
    assert calls[0]["options"]["bitcoin-core"]["revision"] == "latest"
    assert os.environ["INTEGRATION_TEMP_DIR"] == tmp
    assert os.environ["BINARIES_DIR"] == os.path.join(tmp, "binaries")
    assert os.environ["BITCOIN_CORE_PATH"] == paths.binaries_dir


def test_other_version(prepare_run_minimal):
    calls, tmp, paths = prepare_run_minimal("30.0")
    assert calls[0]["daemons"] == ["bitcoin-core"]
    assert calls[0]["options"]["bitcoin-core"]["revision"] == "30.0"
    assert os.environ["INTEGRATION_TEMP_DIR"] == tmp
    assert os.environ["BINARIES_DIR"] == os.path.join(tmp, "binaries")
    assert os.environ["BITCOIN_CORE_PATH"] == paths.binaries_dir


def test_with_wallet(prepare_run_minimal):
    calls, _tmp, _paths = prepare_run_minimal("latest", wallet=True, force=True)
    assert calls[0]["force"] is True
    assert calls[0]["options"]["bitcoin-core"]["wallet"] is True
    assert "n_proc" not in calls[0]["options"]["bitcoin-core"]


def test_nproc(prepare_run_minimal):
    calls, _tmp, _paths = prepare_run_minimal("30.2", nproc=8)
    assert calls[0]["options"]["bitcoin-core"]["n_proc"] == 8


def test_wipes_state_by_default(prepare_run_minimal, tmp_path):
    data = tmp_path / "out" / "data"
    data.mkdir(parents=True)
    (data / "notawallet.dat").touch()
    _, _, paths = prepare_run_minimal("30.2")
    assert os.path.isdir(paths.data_dir)
    assert os.listdir(paths.data_dir) == []


def test_preserve_keeps_state(prepare_run_minimal, tmp_path):
    keep = tmp_path / "out" / "data" / "mock.dat"
    keep.parent.mkdir(parents=True)
    keep.touch()
    prepare_run_minimal("30.2", preserve=True)
    assert keep.exists()
