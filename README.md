# bornal

This work is mainly inspired by [getfloresta/Floresta](https://github.com/getfloresta/Floresta)
integration test framework supported by the following idea: use a imagery
proposition of a [bornal](https://pt.wikipedia.org/wiki/Bornal) -- a brazilian
heavy-duty, water-resitant tatic-like bag belt used today by fireman (not like
we cannot have bugs).

It builds bitcoin daemons from source, runs them on regtest, and hands your
tests a ready JSON-RPC client — so you write integration tests, not plumbing.

## Getting Started

Install:

```bash
uv add --dev git+https://github.com/qlrd/bornal.git
```

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

*build fresh bitcoin nodes*

```bash
uv pytest --build-bitcoin latest tests/integration/test_<feature>.py
```

*run with wallet support*

```bash
uv pytest --wallet tests/integration/test_<wallet_feat>.py 
```

- Each daemon is a `pytest` plugin, that can be added through a `--build-<name>`

- `pytest --build-bitcoin 30.2` (or `latest` for the newest release) makes
`bitcoind` available in the cache (reused unless `--force-build`), wipes its
`data/` and `logs/` (unless `--preserve-data` is used), exports `BINARIES_DIR`
,`INTEGRATION_TEMP_DIR` and `BITCOIN_CORE_PATH` environment , and runs your
`tests/integration`

- Add `--wallet` to build with wallet support.

- `--nproc N` sets the compile parallelism (the build's `-j`).

## Writing Tests

`bornal` registers as a pytest plugin and its fixtures are available on runtime:

```python
from bornal.testing import assert_wallet_roundtrip


def test_wallet(bitcoind_node):
    assert_wallet_roundtrip(bitcoind_node)
```

Or subclass the `IntegrationTest` ABC, which mirrors [getfloresta/Floresta](https://github.com/getfloresta/Floresta)
integration test framework:

```python
from bornal.node import IntegrationTest


class MyTest(IntegrationTest):
    def set_test_params(self):
        self.add_node("bitcoin-core")

    def run_test(self):
        assert self.nodes[0].cli.get_block_count() == 0
```

## Plugins

Daemons are entry-point plugins (group `bornal.daemons`). One plugin wires three
classes: `Compiler` (build the binary), `Daemon` (run it on regtest), `Cli` (talk
JSON-RPC) — and declares the pytest build flag it contributes
(`bitcoin-core` → `--build-bitcoin`):

```toml
[project.entry-points."bornal.daemons"]
bitcoin-core = "bornal.plugins.bitcoind:CoreCompiler"
```

## Development

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

- `examples/` are the real-bitcoind integration tests

# Motivation

I previously contributed to the [getfloresta/Floresta](https://github.com/getfloresta/Floresta)
test framework trying to follow same principles used by Bitcoin-Core's one. Some
issues faced when doing the same approach with
**3 different bitcoin node implementations** (bitcoin-core, utreexod, floresta):

- at least 2 different nodes should ran at same time
- thread concurrencing between those three processes
- plumb all test framework before do the first Floresta specific integration test

The first two, was buggy and fixed by [@joaozinhom](https://github.com/joaozinhom)
using `pytest`. The idea is that `pytest` already deals with threading and
plubimg could be made by fixtures. This work is just a glue of his work as
`pytest` registered plugin.

The imagery proposition of a [bornal](https://pt.wikipedia.org/wiki/Bornal) --
a brazilian heavy-duty, water-resistant tatic bag belt (not like we cannot have
bugs) -- but the idea is to have all on hand to make integration tests as `pytest` plugin.


## Contributing

Branch off `main` and open a PR; reviews scan `git diff main...HEAD`. Keep the
gates green (`uv run poe lint`, `format-check`, `test-cov`) and use
[Conventional Commits](https://www.conventionalcommits.org) — the `commit-msg`
hook enforces them.
