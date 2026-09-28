import ast
import os
import pytest

# Warning
#
# > Note that successfully parsing source code into an AST object doesn’t
# guarantee that the source code provided is valid Python code that can be
# executed as the compilation step can raise further SyntaxError exceptions.
# >
# > For instance, the source return 42 generates a valid AST node for a return
# statement, but it cannot be compiled alone (it needs to be inside a function
# node).
#
# docs.python.org/3/library/ast.html#ast.parse
#
# The tests below using ast is just to check if the gernerated code is acceptable,
# not if is correct when executed.


def test_requires_a_subcommand(git_repo, run_cli):
    with pytest.raises(SystemExit):
        run_cli("--proj-path", str(git_repo))


def test_create_default(integrate):
    dest = integrate("test_bitcoin_core.py")
    assert os.path.exists(dest)
    body = open(dest).read()
    assert "def test_000_connect(alice, bob):" in body
    assert "connect_p2p(alice, bob)" in body


def test_create_and_run(integrate):
    dest = integrate("test_bitcoin_core.py")
    body = open(dest).read()
    assert "pytest --build-bitcoin latest" in body
    assert "bornal run" not in body


def test_create_scaffold(integrate):
    dest = integrate("test_myfeat.py", "myfeat")
    assert os.path.exists(dest)

    body = open(dest).read()
    assert "def test_000_connect(alice, bob):" in body
    assert "assert_block_count(alice, 0)" in body
    assert "assert_block_count(bob, 0)" in body

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
    assert "def test_000_connect(alice, bob):" in body
    ast.parse(body)


def test_create_fail(integrate):
    with pytest.raises(SystemExit):
        integrate("test_.py", "*%@")


def test_create_default_template(integrate):
    dest = integrate("test_bitcoin_core.py")
    body = open(dest).read()
    assert 'assert_chain(alice, "regtest")' in body
    assert "assert_wallet_roundtrip" not in body


def test_create_wallet_roundtrip_template(integrate):
    dest = integrate("test_bitcoin_core.py", "--template", "wallet-roundtrip")
    body = open(dest).read()
    assert "connect_p2p" in body
    assert "sync_blocks" in body
    assert "assert_block_count" in body
    assert "assert_chain" in body
    assert "assert_wallet_roundtrip(alice)" in body
    assert "pytest --build-bitcoin latest --wallet" in body
    ast.parse(body)


def test_create_fail_unknown_template(integrate):
    with pytest.raises(SystemExit):
        integrate("test_bitcoin_core.py", "--template", "nope")


def test_create_electrs_template(integrate):
    dest = integrate("test_electrs.py", "--template", "electrs")
    body = open(dest).read()
    assert "target: bitcoin-core, electrs on regtest" in body
    assert "pytest --build-bitcoin latest --build-electrs latest tests/" in body
    assert "def test_000_index(alice, electrs):" in body
    assert "assert_electrs_tip(electrs, COINBASE_MATURITY + 1)" in body
    ast.parse(body)

    conftest = open(os.path.join(os.path.dirname(dest), "conftest.py")).read()
    assert 'self.add_backend("bitcoin-core", p2p_port=free_port())' in conftest
    assert 'self.add_backend("electrs")' in conftest
    assert "def electrs(integration_test):" in conftest
    ast.parse(conftest)


def test_create_conftest_once(integrate):
    dest = integrate("test_bitcoin_core.py")
    conftest = os.path.join(os.path.dirname(dest), "conftest.py")
    body = open(conftest).read()
    assert 'self.add_backend("bitcoin-core", p2p_port=free_port())' in body
    assert "def bob(integration_test):" in body
    ast.parse(body)

    # a second test in the same dir keeps the conftest as is
    with open(conftest, "w") as handle:
        handle.write("# mine\n")
    integrate("test_other.py", "other")
    assert open(conftest).read() == "# mine\n"

    # --force rewrites it
    integrate("test_other.py", "other", "--force")
    assert "class BaseTest(IntegrationTest):" in open(conftest).read()
