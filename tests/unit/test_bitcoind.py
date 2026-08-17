from bornal.plugins import bitcoind
from bornal.plugins.bitcoind import CoreCompiler


def test_cached_build_wins_over_path(
    paths, spy_build, mock_bitcoind_cache, mock_bitcoind_bin_path
):
    dest = mock_bitcoind_cache()
    mock_bitcoind_bin_path("elsewhere")

    assert CoreCompiler().ensure(paths) == dest
    with open(dest) as handle:
        assert handle.read() == "cached"
    assert list(spy_build) == []


def test_cached_build_matching_meta_skips_rebuild(
    paths, spy_build, mock_bitcoind_cache
):
    dest = mock_bitcoind_cache("30.2", True)

    assert CoreCompiler().ensure(paths, revision="30.2", wallet=True) == dest
    assert list(spy_build) == []


def test_cached_build_mismatched_meta_rebuilds(paths, spy_build, mock_bitcoind_cache):
    mock_bitcoind_cache("1.0", False)

    CoreCompiler().ensure(paths, revision="30.2")
    assert any(c[:2] == ["git", "clone"] for c in spy_build)
    assert bitcoind._read_build_meta(paths.binaries_dir) == {
        "revision": "30.2",
        "wallet": False,
    }


def test_force_rebuilds_over_matching_cache(paths, spy_build, mock_bitcoind_cache):
    mock_bitcoind_cache("30.2", False)

    CoreCompiler().ensure(paths, revision="30.2", force=True)
    assert any(c[:2] == ["git", "clone"] for c in spy_build)


def test_path_binary_adopted_when_no_cache(paths, spy_build, mock_bitcoind_bin_path):
    mock_bitcoind_bin_path("elsewhere")

    dest = CoreCompiler().ensure(paths)
    with open(dest) as handle:
        assert handle.read() == "mockuo"
    assert bitcoind._read_build_meta(paths.binaries_dir) == {
        "revision": "path",
        "wallet": None,
    }
    assert list(spy_build) == []
