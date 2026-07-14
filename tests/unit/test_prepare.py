def test_ensure_daemons_builds_selected(paths, spy_build):
    from bornal import prepare

    # Check if daemons are compliant with the name
    # and a revision preparing a force build
    out = prepare.ensure_daemons(
        paths,
        daemons=["bitcoin-core"],
        force=True,
        options={"bitcoin-core": {"revision": "30.2"}},
    )
    assert out == paths.binaries_dir
    clone = next(c for c in spy_build if c[:2] == ["git", "clone"])
    assert "v30.2" in clone


def test_ensure_daemons_defaults_to_all_installed(paths, spy_build):
    from bornal import prepare

    # Check if a smoked ``git clone``
    # was called during the build procedure (default one)
    prepare.ensure_daemons(paths)
    assert any(c[:2] == ["git", "clone"] for c in spy_build)
