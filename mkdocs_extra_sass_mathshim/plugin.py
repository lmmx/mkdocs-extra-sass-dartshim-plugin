"""
MkDocs Extra Sass MathShim Plugin

- Shims Dart Sass syntax (`math.div`, `color.channel`, `svg-load`, etc.) to work under python-libsass.
- Fetches & inlines remote SVGs at build-time, caching them via platformdirs, so repeated builds are faster.
"""

import base64
import hashlib
import io
import json
import logging
import os
import re
from abc import ABC
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Type, TypeVar

import requests
import sass
from bs4 import BeautifulSoup
from livereload import Server
from mkdocs.config import Config, config_options
from mkdocs.plugins import BasePlugin
from mkdocs.structure.pages import Page
from mkdocs.utils import normalize_url
from platformdirs import user_cache_dir

log = logging.getLogger("mkdocs.extra-sass")

_T_SassEntry = TypeVar("_T", bound="_SassEntry")

default_mdi = "https://raw.githubusercontent.com/lmmx/MaterialDesign-SVG/master/svg/"
default_oct = "https://raw.githubusercontent.com/primer/octicons/main/icons/"


class ExtraSassPlugin(BasePlugin):
    """
    A MkDocs plugin that:
      - Looks for a Sass/SCSS file in `extra_sass/` (e.g. style.scss).
      - Compiles to .css + .map, injecting <link> into all pages.
      - Shims new Dart Sass calls for compatibility with python-libsass.
      - Automatically fetches remote SVGs for `svg-load("...")` and caches them in user_cache_dir.
    """

    config_scheme = (
        ("mdi_base_url", config_options.Type(str, default=default_mdi)),
        ("octicons_base_url", config_options.Type(str, default=default_oct)),
    )

    def __init__(self):
        self.__entry_point = None
        self.__mdi_base_url = None
        self.__octicons_base_url = None

    def on_config(self, config: Config):
        """Capture user config from mkdocs.yml."""
        self.__entry_point = None
        self.__mdi_base_url = (
            self.config.get(
                "mdi_base_url",
                default_mdi,
            ).rstrip("/")
            or self.__mdi_base_url
        )
        self.__octicons_base_url = (
            self.config.get(
                "octicons_base_url",
                default_oct,
            ).rstrip("/")
            or self.__octicons_base_url
        )

    def on_serve(self, server: Server, config: Config, builder, **kwargs):
        """Watch extra_sass directory during mkdocs serve (live reload)."""
        self._entry_point(config).on_serve(server, builder)
        return server

    def on_post_page(self, output_content: str, page: Page, config: Config) -> str:
        """
        After each page is rendered, inject our compiled CSS via <link rel="stylesheet">.
        """
        relative_path = self._entry_point(config).relative_path
        if not relative_path:
            return output_content

        href = normalize_url(relative_path, page=page)
        soup = BeautifulSoup(output_content, "html.parser")

        link_tag = soup.new_tag("link", rel="stylesheet", href=href)
        soup.head.append(link_tag)

        log.debug("[SASS] on_page: %s -> %s", page.url, link_tag)
        return str(soup)

    # ---------------------------------------------------------------------

    def _entry_point(self, config: Config) -> _T_SassEntry:
        """
        We cache the discovered Sass entry so we don't re-scan each time.
        """
        if self.__entry_point is None:
            self.__entry_point = self._build_entry(config)
        return self.__entry_point

    def _build_entry(self, config: Config) -> _T_SassEntry:
        """
        If we find a file like `extra_sass/style.scss`, compile it and store the final path for injection.
        """
        entry_point = _SassEntry.search_entry_point()
        if entry_point.is_available:
            # Pass relevant base URLs so we can download icons from them
            entry_point.set_mdi_base_url(self.__mdi_base_url)
            entry_point.set_octicons_base_url(self.__octicons_base_url)

            try:
                site_dir = config["site_dir"]
                dest_dir = os.path.join("assets", "stylesheets")
                info = entry_point.save_to(site_dir, dest_dir)
                log.info('[SASS] Build CSS "%s" from "%s"', info["dst"], info["src"])
            except Exception as ex:
                log.exception("[SASS] Failed to build CSS: %s", ex)
                if config.get("strict", False):
                    raise ex
        return entry_point


# =========================================
# Internal classes for Sass handling
# =========================================


class _SassEntry(ABC):
    _styles_dir = "extra_sass"
    _style_filenames = [
        "style.css.sass",
        "style.sass",
        "style.css.scss",
        "style.scss",
    ]

    def __init__(self):
        pass

    @classmethod
    def search_entry_point(cls: Type[_T_SassEntry]) -> _T_SassEntry:
        """
        Look in `extra_sass/` for a potential Sass/SCSS file.
        """
        d = cls._styles_dir
        if os.path.isdir(d):
            for f in cls._style_filenames:
                path = os.path.join(d, f)
                if os.path.isfile(path):
                    return _AvailableSassEntry(d, f)
        return _NoSassEntry()

    @property
    def is_available(self) -> bool:
        return False

    @property
    def relative_path(self) -> str:
        return ""

    def on_serve(self, server: Server, builder) -> None:
        pass

    def save_to(self, site_dir: str, dest_dir: str) -> dict:
        raise NotImplementedError()

    # Extra "setter" stubs so we can pass base URLs
    def set_mdi_base_url(self, url: str):
        pass

    def set_octicons_base_url(self, url: str):
        pass


class _NoSassEntry(_SassEntry):
    pass


class _AvailableSassEntry(_SassEntry):
    """
    If we found a scss/sass file in `extra_sass/`, we compile it.
    """

    def __init__(self, dirname: str, filename: str):
        super().__init__()
        self._dirname = dirname
        self._filename = filename
        self._relative_path = None

        # Optionally store base URLs from plugin config
        self._mdi_base_url = ""
        self._octicons_base_url = ""

    @property
    def is_available(self) -> bool:
        return True

    @property
    def relative_path(self) -> str:
        return self._relative_path or ""

    def on_serve(self, server: Server, builder) -> None:
        """
        Watch the directory for changes (live reload).
        """
        source_path = os.path.join(self._dirname, self._filename)
        if os.path.isfile(source_path):
            server.watch(self._dirname, builder)

    def set_mdi_base_url(self, url: str):
        self._mdi_base_url = url or ""

    def set_octicons_base_url(self, url: str):
        self._octicons_base_url = url or ""

    def save_to(self, site_dir: str, dest_dir: str) -> dict:
        """
        1) Read the SCSS from `extra_sass/...`
        2) Shim new Sass syntax
        3) Download any remote SVGs and inline them
        4) Compile to CSS + sourcemap
        5) Return final file info
        """
        source_path = os.path.join(self._dirname, self._filename)

        with io.open(source_path, "r", encoding="utf-8") as f:
            scss_source = f.read()

        # 1) SHIM math.* calls
        scss_source = re.sub(r"math\.round\(", "round(", scss_source)
        scss_source = re.sub(
            r"math\.div\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)", r"(\1 / \2)", scss_source
        )
        scss_source = re.sub(r"math\.unit\(\s*([^)]+?)\s*\)", r"unit(\1)", scss_source)

        # 2) SHIM color.channel(...) calls
        scss_source = re.sub(
            r"color\.channel\s*\(\s*([^\)]+),\s*['\"]hue['\"].*?\)",
            r"hue(\1)",
            scss_source,
            flags=re.IGNORECASE,
        )
        scss_source = re.sub(
            r"color\.channel\s*\(\s*([^\)]+),\s*['\"]saturation['\"].*?\)",
            r"saturation(\1)",
            scss_source,
            flags=re.IGNORECASE,
        )
        scss_source = re.sub(
            r"color\.channel\s*\(\s*([^\)]+),\s*['\"]lightness['\"].*?\)",
            r"lightness(\1)",
            scss_source,
            flags=re.IGNORECASE,
        )

        # 3) SHIM svg-load(...) calls
        scss_source = self._inline_svg_loads(scss_source)

        # 4) Write the updated SCSS to a temporary .scss file
        output_dir = os.path.join(site_dir, dest_dir)
        os.makedirs(output_dir, exist_ok=True)

        from tempfile import NamedTemporaryFile

        with NamedTemporaryFile(
            prefix="temp-sass-",
            suffix=".scss",
            dir=output_dir,
            delete=False,
            mode="w",
            encoding="utf-8",
            newline="",
        ) as tmp_scss:
            tmp_scss.write(scss_source)
            tmp_scss_path = tmp_scss.name

        # 5) Compile -> final CSS (+ sourcemap)

        def fix_umask(temp_file):
            umask = os.umask(0o666)
            os.umask(umask)
            os.chmod(temp_file.name, 0o666 & ~umask)

        with NamedTemporaryFile(
            prefix="extra-style.",
            suffix=".min.css",
            dir=output_dir,
            delete=False,
            mode="w",
            encoding="utf-8",
            newline="",
        ) as css_file:
            fix_umask(css_file)
            _, filename = os.path.split(css_file.name)
            source_map_filename = filename + ".map"

            css, source_map = sass.compile(
                filename=tmp_scss_path,
                output_style="compressed",
                source_map_filename=source_map_filename,
                source_map_contents=True,
                omit_source_map_url=False,
                output_filename_hint=filename,
            )

            css_file.write(css)

            map_file = os.path.join(output_dir, source_map_filename)
            with io.open(map_file, "w", encoding="utf-8", newline="") as f:
                f.write(source_map)

            # Done!
            self._relative_path = os.path.join(dest_dir, filename)
            return {"src": source_path, "dst": self._relative_path}

    # ---------------------------------------------------------------------
    # SVG LOAD LOGIC (fetch from web, cache with platformdirs)
    # ---------------------------------------------------------------------

    def _inline_svg_loads(self, scss_text: str) -> str:
        """
        Replaces `svg-load("something.svg")` with
        `/* svg-load("something.svg") => inlined */ url('data:image/svg+xml;base64,....')`
        or a comment if we can’t find/fetch the file.
        """
        pattern = re.compile(r'svg-load\s*\(\s*(["\'])([^"\']+)\1\s*\)')

        def replacer(match):
            full_text = match.group(0)
            svg_path = match.group(2).strip()

            # If this is an absolute URL (http...), fetch directly
            if svg_path.startswith("http://") or svg_path.startswith("https://"):
                fetched = self._fetch_and_cache(svg_path)
                if not fetched:
                    return f"/* {full_text} => FAILED to fetch */"
                return f"/* {full_text} => inlined */ url('data:image/svg+xml;base64,{fetched}')"

            # If it's an MDI reference like "@mdi/svg/svg/github.svg" and we have a base URL
            if self._mdi_base_url and svg_path.startswith("@mdi/svg/svg/"):
                # e.g. ".../github.svg"
                subfile = os.path.basename(svg_path)
                remote_url = f"{self._mdi_base_url}/{subfile}"
                fetched = self._fetch_and_cache(remote_url)
                if not fetched:
                    return f"/* {full_text} => MDI fetch failed: {remote_url} */"
                return f"/* {full_text} => inlined */ url('data:image/svg+xml;base64,{fetched}')"

            # If it's an Octicons reference like "@primer/octicons/build/svg/git-commit-24.svg"
            if self._octicons_base_url and "octicons" in svg_path:
                # e.g. we might do something like:
                subfile = os.path.basename(svg_path)
                remote_url = f"{self._octicons_base_url}/{subfile}"
                fetched = self._fetch_and_cache(remote_url)
                if not fetched:
                    return f"/* {full_text} => Octicons fetch failed: {remote_url} */"
                return f"/* {full_text} => inlined */ url('data:image/svg+xml;base64,{fetched}')"

            # Otherwise, unknown path. We can't fetch or parse it.
            # Just comment it out to avoid compile error.
            return f"/* {full_text} => no known base URL or not an http link */"

        return pattern.sub(replacer, scss_text)

    def _fetch_and_cache(self, remote_url: str) -> str:
        """
        Downloads an .svg from `remote_url` if not already cached,
        then returns a base64-encoded string of its contents.
        """
        cache_dir = Path(user_cache_dir("mkdxs-mathshim"))
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Use a simple hash as the cache filename
        h = hashlib.sha256(remote_url.encode("utf-8")).hexdigest()
        cache_file = cache_dir / f"{h}.svg"

        # If cached, read & return
        if cache_file.is_file():
            try:
                with io.open(cache_file, "r", encoding="utf-8") as f:
                    svg_data = f.read()
                return base64.b64encode(svg_data.encode("utf-8")).decode("utf-8")
            except Exception as e:
                log.warning(
                    "Could not read cached %s, will re-download. Error: %s",
                    cache_file,
                    e,
                )
                cache_file.unlink(missing_ok=True)

        # Not cached or unreadable -> fetch
        log.info("[SASS] Downloading %s -> %s", remote_url, cache_file)
        try:
            r = requests.get(remote_url, timeout=10)
            r.raise_for_status()
            svg_data = r.text
        except Exception as e:
            log.warning("Failed to fetch %s: %s", remote_url, e)
            return ""  # signal failure

        # Cache
        try:
            cache_file.write_text(svg_data, encoding="utf-8")
        except Exception as e:
            log.warning("Could not write cache file %s: %s", cache_file, e)

        # Return base64
        return base64.b64encode(svg_data.encode("utf-8")).decode("utf-8")
