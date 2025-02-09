# mkdocs-extra-sass-mathshim

[![PyPI version](https://img.shields.io/pypi/v/mkdocs-extra-sass-mathshim.svg)](https://pypi.org/project/mkdocs-extra-sass-mathshim)
[![PyPI downloads](https://img.shields.io/pypi/dm/mkdocs-extra-sass-mathshim.svg)](https://pypi.org/project/mkdocs-extra-sass-mathshim)

---

This plugin adds stylesheets to your MkDocs site from `Sass`/`SCSS` and includes shims for:

- math functions—such as `math.round()` and `math.div()`
- colour functions
- svg-load functions

so you can use modern module syntax while using non‑Dart Sass (i.e. LibSass).

See example use in [`page-dewarp` docs](https://github.com/lmmx/page-dewarp) for reference (`.scss` files).

## Features

* Uses [LibSass][LibSass] with [libsass-python][libsass-python].
* Provides math function shims to translate calls like `math.round()` to the older, supported equivalents.

## How to use

### Installation

1. Install the package with pip:

    ```sh
    pip install mkdocs-extra-sass-mathshim
    ```

2. Enable the plugin in your `mkdocs.yml`:

    ```yaml
    plugins:
      - extra-sass
    ```

    > **Note**: If you have no `plugins` entry in your config file yet, you'll likely also want to add the `search` plugin. MkDocs enables it by default if there is no `plugins` entry set, but now you have to enable it explicitly.

3. Create an `extra_sass` directory in your working directory (usually the same directory as `mkdocs.yml`), and create an **entry point file** named either `style.css.sass` or `style.css.scss`:

    ```none
    (top)
    ├── docs
    │   ...snip...
    │   └── index.md
    ├── extra_sass
    │   ...snip...
    │   └── style.css.scss  # Compiler entry point file.
    └── mkdocs.yml
    ```

More information about MkDocs plugins is available in the [MkDocs documentation][mkdocs-plugins].

## Contributing

Every contribution is appreciated—whether you're reporting a bug, asking a question, or submitting a pull request. Please report bugs or request features via [Github issues][github-issues].  
If you want to contribute code, please read the [Contribution Guidelines][contributing].

[LibSass]: https://sass-lang.com/libsass
[libsass-python]: https://github.com/sass/libsass-python
[mkdocs-plugins]: https://www.mkdocs.org/user-guide/plugins/
[github-issues]: https://github.com/lmmx/mkdocs-extra-sass-mathshim/issues
[contributing]: https://github.com/lmmx/mkdocs-extra-sass-mathshim/blob/master/CONTRIBUTING.md
