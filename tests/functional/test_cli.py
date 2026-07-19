import ast
import os
import pytest


def test_requires_a_subcommand(git_repo, run_cli):
    with pytest.raises(SystemExit):
        run_cli("--proj-path", str(git_repo))


def test_create_default(integrate):
    dest = integrate("test_bitcoin_core.py")
    assert os.path.exists(dest)
    body = open(dest).read()
    assert "def test_bitcoin_core(node):" in body
    assert 'node("bitcoin-core")' in body


def test_create_and_run(integrate):
    dest = integrate("test_bitcoin_core.py")
    body = open(dest).read()
    assert "pytest --build-bitcoin latest" in body
    assert "bornal run" not in body


def test_create_scaffold(integrate):
    dest = integrate("test_myfeat.py", "myfeat")
    assert os.path.exists(dest)

    body = open(dest).read()
    print(body)
    assert "def test_myfeat(node):" in body
    assert "assert cli.get_blockchain_info()" in body
    # a second run without --force
    with pytest.raises(SystemExit):
        integrate("test_myfeat.py", "myfeat")

    # with --force it overwrites
    dest = integrate("test_myfeat.py", "myfeat", "--force")
    assert os.path.exists(dest)


def test_create_custom_default(integrate):
    dest = integrate("test_simple_test.py", "simple-test")
    assert os.path.exists(dest)
    body = open(dest).read()
    assert "def test_simple_test(node):" in body
    ast.parse(body)


def test_create_fail(integrate):
    with pytest.raises(SystemExit):
        integrate("test_.py", "*%@")


def test_create_default_template(integrate):
    dest = integrate("test_bitcoin_core.py")
    body = open(dest).read()
    assert 'cli.get_blockchain_info()["chain"] == "regtest"' in body
    assert "assert_wallet_roundtrip" not in body


def test_create_wallet_roundtrip_template(integrate):
    dest = integrate("test_bitcoin_core.py", "--template", "wallet-roundtrip")
    body = open(dest).read()
    assert "from bornal.testing import assert_wallet_roundtrip" in body
    assert 'assert_wallet_roundtrip(node("bitcoin-core"))' in body
    assert "pytest --build-bitcoin latest --wallet" in body


def test_create_fail_unknown_template(integrate):
    with pytest.raises(SystemExit):
        integrate("test_bitcoin_core.py", "--template", "nope")
