# bornal

This work is mainly inspired by [getfloresta/Floresta](https://github.com/getfloresta/Floresta)
integration test framework supported by the following idea: use a imagery
proposition of a [bornal/embornal](https://pt.wikipedia.org/wiki/Bornal) -- a
brazilian heavy-duty, water-resitant tatic-like bag belt used by camp workers
with meals ("boia"), bottles of water and working tools.

It scaffolds some test structure in a jekyll-like style and lets `pytest` knows
how to builds bitcoin daemons (plural: WIP on implement `utreexod`, `florestad`,
and `lianda`) from source, runs them on `regtest` (plan to add `signet`), and
hands your tests a ready JSON-RPC client — so you write your integration tests,
hacking through your preferred bitcoin lib, not plumbing through it.

> The philosophy is not to rely on pre-built binaries for bitcoin reference and
community implemenations (not because we cannot verify them locally on on CI,
but because **is a choice is to rely on our bitcoin compilation**).

## Getting Started

Install:

```bash
uv add --dev git+https://github.com/qlrd/bornal.git
```

> I do not pretend yet add to `pip`

**Scaffold**

Scaffold an example test, then run it through the pytest plugin:

```bash
uv bornal create <feature> --template <template>
```

`bornal create <feature>` only scaffolds some files into your project.

**Run tests**

This is the fun part: you skip the main coding setup and just let `pytest` know
it through their plugin system:

```bash
INTEGRATION_TEMP_DIR=<.cache> uv pytest tests/integration/test_<feature>.py
```

Where `<.cache>` is **your pre-built | compiled** bitcoin implementation.

*build fresh bitcoin nodes*

```bash
uv pytest --build-bitcoin latest tests/integration/test_<feature>.py
```

*run with wallet support*

```bash
uv pytest --wallet tests/integration/test_<wallet_feat>.py 
```

- Each daemon is a `pytest` plugin
- each plugin that can be added through a `--build-<name>` flag

I.e., `pytest --build-bitcoin 30.2` (or `latest` for the newest release) makes
`bitcoind` available in the cache and have some additional flags and environment
variables:

- reused unless `--force-build`), wipes its `data/` and `logs/`
- (unless `--preserve-data` is used)
- exports `BINARIES_DIR`
- exports `INTEGRATION_TEMP_DIR`
- exports  `BITCOIN_CORE_PATH`
- `--wallet` to build with wallet support.
- `--nproc N` sets the compile parallelism (the build's `-j`).

and then runs your `tests/integration`. If you choose the "compilation-path",
the next time you will not need to use `--build-*`.

## Writing Tests

This is for writing test on **your project**. Once you have your `tests/integration`
build (or already built and bought the idea), `bornal` registers this plugin as
a pytest plugin and its fixtures are available on `pytest` runtime:

```python
from bornal.testing import assert_wallet_roundtrip


def test_wallet(bitcoind_node):
    assert_wallet_roundtrip(bitcoind_node)
```

Or subclass the `IntegrationTest` (an `ABC` derived class), which mirrors
[getfloresta/Floresta](https://github.com/getfloresta/Floresta) integration
test framework:

```python
from bornal.node import IntegrationTest


class MyTest(IntegrationTest):
    def set_test_params(self):
        self.add_node("bitcoin-core")

    def run_test(self):
        assert self.nodes[0].cli.get_block_count() == 0
```

## Plugins

Daemons are entry-point plugins (group them by `bornal.daemons`). One plugin
wires three classes:

- `Compiler` (build the binary)
- `Daemon` (the implementation daemon on regtest)
- `Cli` (talk JSON-RPC like)
— and declares the the pytest build flag it contributes (e.g.,
`--<bitcoin-impl>` → `--build-<bitcoin-impl>`)

For example:

```toml
[project.entry-points."bornal.daemons"]
<bitcoin-impl> = "bornal.plugins.<bitcoin-impl>:CoreCompiler"
```

also you need to register fixtures on `src/bornal/fixtures.py` so it can be
found by:

```toml
[project.entry-points.pytest11]
bornal = "bornal.fixtures"
```

## Development

`bornal` need `pytest` as `dep` and not `dev-dep`.

### Fetch the code

```bash
git clone https://github.com/qlrd/bornal
cd bornal
```

### Install dev tools

```bash
uv sync --group dev
uv run poe hooks
```

### Format code

```bash
uv run poe format-check
```

### Lint code

```bash
uv run poe lint
```

### Examples

If you add some plugin, is really important to add some **examples** on `examples/`.
They're real-bitcoind integration tests demos.

# Motivation

A previously contribution to the [getfloresta/Floresta](https://github.com/getfloresta/Floresta)
test framework taught on how to follow some already coded principles of Bitcoin-Core
test framework and thus I helped to improve it to support both `bitcoind`, `utreexod`,
`florestad`.

While it almost-work (in the sense with random failures in CI), this was fixed by
[@joaozinhom](https://github.com/joaozinhom) using `pytest`. The idea is that
`pytest` already deals with threading and plubimg could be made by fixtures.

This work is just a glue of his work as `pytest` registered plugin plus a
scaffolding and self-tests.

## Contributing

Branch off `main` and open a PR; reviews scan `git diff main...HEAD`. Keep the
gates green (`uv run poe lint`, `format-check`, `test-cov`) and use
[Conventional Commits](https://www.conventionalcommits.org) — the `commit-msg`
hook enforces them.
