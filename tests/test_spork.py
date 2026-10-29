"""End-to-end tests for the spork script.

Each test runs the real spork in a throwaway home folder, with a local drawer and
packages served from a local HTTP server, so nothing touches ~/.spork, ~/Applications
or the network. macOS only: spork relies on plutil, ditto, hdiutil and pkgutil.

    python3 -m unittest discover -s tests -v
"""

import functools
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path

SPORK = Path(__file__).resolve().parent.parent / "spork"

# Proxy settings from the developer's shell would route test downloads elsewhere.
PROXY_VARS = ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@unittest.skipUnless(sys.platform == "darwin", "spork only runs on macOS")
class SporkTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="spork-test-")
        root = Path(os.path.realpath(self._tmp.name))
        self.home = root / "home"
        self.spork_home = self.home / ".spork"
        self.appdir = self.home / "Applications"
        self.drawer = root / "drawer"          # linked as the "main" drawer
        self.www = root / "www"                # served over HTTP
        self.build = root / "build"            # scratch space for making packages
        for d in (self.home, self.drawer, self.www, self.build):
            d.mkdir()

        handler = functools.partial(QuietHandler, directory=str(self.www))
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

        self.env = {k: v for k, v in os.environ.items() if k not in PROXY_VARS}
        self.env.update(
            HOME=str(self.home),
            SPORK_HOME=str(self.spork_home),
            SPORK_APPDIR=str(self.appdir),
            SPORK_ARCH="arm64",
            SPORK_KEYCHAIN="0",
            SHELL="/bin/zsh",
            NO_PROXY="*",
        )
        self.env.pop("SPORK_MIRRORS_FILE", None)
        self.spork("drawer", "add", "main", str(self.drawer))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self._tmp.cleanup()

    # ------------------------------------------------------------ helpers

    def spork(self, *args, ok=True, env=None):
        """Run spork; fail the test if its exit status isn't what we expect."""
        p = subprocess.run(
            [str(SPORK), *args], env={**self.env, **(env or {})},
            capture_output=True, text=True, timeout=120,
        )
        p.output = p.stdout + p.stderr
        if ok and p.returncode != 0:
            self.fail(f"spork {' '.join(args)} failed ({p.returncode}):\n{p.output}")
        if not ok and p.returncode == 0:
            self.fail(f"spork {' '.join(args)} should have failed:\n{p.output}")
        return p

    def tree(self, name, files):
        """Create a folder under build/ from {relative path: text}. Paths under bin/ are executable."""
        d = self.build / name
        if d.exists():
            shutil.rmtree(d)
        for rel, text in files.items():
            f = d / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text)
            if rel.startswith("bin/") or "/MacOS/" in rel:
                f.chmod(0o755)
        return d

    def serve(self, path, as_name=None):
        """Copy a file into the web root; return (url, "sha256:…")."""
        dest = self.www / (as_name or Path(path).name)
        shutil.copy(path, dest)
        return f"{self.base_url}/{dest.name}", "sha256:" + sha256(dest)

    def tool_archive(self, name, version, extra=None, fmt="tar.gz", say=None):
        """A package with bin/<name> that prints "<name> <version>", inside "<name>-<version>/"."""
        top = f"{name}-{version}"
        files = {f"bin/{name}": f'#!/bin/sh\necho "{say or f"{name} {version}"}"\n'}
        files.update(extra or {})
        src = self.tree(top, files)
        out = self.build / f"{top}.{fmt}"
        if fmt == "tar.gz":
            with tarfile.open(out, "w:gz") as t:
                t.add(src, arcname=top)
        elif fmt == "zip":
            subprocess.run(["ditto", "-c", "-k", "--keepParent", src, out], check=True)
        else:
            raise ValueError(fmt)
        return out

    def manifest(self, name, where=None, **fields):
        path = (where or self.drawer) / f"{name}.json"
        fields = {k: v for k, v in fields.items() if v is not None}
        path.write_text(json.dumps(fields, indent=2))
        return path

    def publish_tool(self, name, version, where=None, extra=None, **fields):
        """Build, serve and write a manifest for a simple command-line tool."""
        url, digest = self.serve(self.tool_archive(name, version, extra))
        fields = {
            "version": version, "description": f"The {name} tool", "url": url, "hash": digest,
            "extract_dir": f"{name}-{version}", "bin": f"bin/{name}", **fields,
        }
        return self.manifest(name, where, **fields)

    def run_cmd(self, name):
        return subprocess.run([str(self.spork_home / "bin" / name)], capture_output=True,
                              text=True, check=True).stdout.strip()

    def installed(self, name):
        cur = self.spork_home / "apps" / name / "current"
        return os.readlink(cur) if cur.is_symlink() else None

    def receipt(self, name):
        info = self.spork_home / "apps" / name / "current" / ".spork" / "info"
        return dict(line.split("=", 1) for line in info.read_text().splitlines())

    # ------------------------------------------------------------ basics

    def test_version_and_help(self):
        self.assertRegex(self.spork("version").stdout, r"^spork \d+\.\d+\.\d+")
        self.assertIn("install <pkg>", self.spork("help").stdout)
        self.assertIn("unknown command", self.spork("frobnicate", ok=False).stderr)

    def test_install_list_which_uninstall(self):
        self.publish_tool("hello", "1.0")
        out = self.spork("install", "hello").output
        self.assertIn("hash ok", out)
        self.assertEqual(self.run_cmd("hello"), "hello 1.0")
        self.assertEqual(self.installed("hello"), "1.0")
        self.assertEqual(self.receipt("hello")["drawer"], "main")

        self.assertRegex(self.spork("list").stdout, r"hello\s+1\.0\s+main")
        self.assertIn("apps/hello/current/bin/hello  (hello)", self.spork("which", "hello").stdout)
        self.assertEqual(self.spork("prefix", "hello").stdout.strip(),
                         str(self.spork_home / "apps/hello/current"))
        info = self.spork("info", "hello").stdout
        self.assertIn("Installed:   1.0", info)
        self.assertIn("Commands:    hello", info)

        self.assertIn("already installed", self.spork("install", "hello").output)

        self.spork("uninstall", "hello")
        self.assertFalse((self.spork_home / "bin/hello").exists())
        self.assertFalse((self.spork_home / "apps/hello").exists())
        self.assertIn("Nothing installed", self.spork("list").stdout)
        self.assertIn("not installed", self.spork("uninstall", "hello", ok=False).stderr)

    def test_unknown_package(self):
        self.assertIn("couldn't find package", self.spork("install", "nope", ok=False).stderr)
        self.assertIn("no drawer named", self.spork("install", "nodrawer/x", ok=False).stderr)

    def test_invalid_manifest(self):
        (self.drawer / "broken.json").write_text("{ not json")
        self.assertIn("invalid JSON", self.spork("install", "broken", ok=False).stderr)
        self.manifest("noversion", url="http://x/y")
        self.assertIn('no "version"', self.spork("install", "noversion", ok=False).stderr)

    def test_hash_mismatch_installs_nothing(self):
        self.publish_tool("hello", "1.0", hash="sha256:" + "0" * 64)
        err = self.spork("install", "hello", ok=False).stderr
        self.assertIn("hash check failed", err)
        self.assertIsNone(self.installed("hello"))
        self.assertFalse(list((self.spork_home / "cache").glob("hello#*")), "bad download kept in cache")

    def test_sha512_and_uppercase_hash(self):
        archive = self.tool_archive("hello", "1.0")
        url, _ = self.serve(archive)
        digest = hashlib.sha512(archive.read_bytes()).hexdigest().upper()
        self.manifest("hello", version="1.0", url=url, hash=f"sha512:{digest}",
                      extract_dir="hello-1.0", bin="bin/hello")
        self.spork("install", "hello")
        self.assertEqual(self.run_cmd("hello"), "hello 1.0")

    def test_missing_hash_warns(self):
        self.publish_tool("hello", "1.0", hash=None)
        self.assertIn("was not verified", self.spork("install", "hello").stderr)

    # ------------------------------------------------------------ download formats

    def test_zip(self):
        url, digest = self.serve(self.tool_archive("zipped", "1.0", fmt="zip"))
        self.manifest("zipped", version="1.0", url=url, hash=digest,
                      extract_dir="zipped-1.0", bin="bin/zipped")
        self.spork("install", "zipped")
        self.assertEqual(self.run_cmd("zipped"), "zipped 1.0")

    def test_plain_binary_renamed_with_fragment(self):
        src = self.build / "raw"
        src.write_text('#!/bin/sh\necho raw\n')
        url, digest = self.serve(src, "raw-macos-arm64")
        self.manifest("raw", version="1.0", url=f"{url}#/raw", hash=digest, bin="raw")
        self.spork("install", "raw")
        self.assertEqual(self.run_cmd("raw"), "raw")

    def test_gz_single_file(self):
        src = self.build / "gzt"
        src.write_text('#!/bin/sh\necho gzt\n')
        subprocess.run(["gzip", "-k", src], check=True)
        url, digest = self.serve(self.build / "gzt.gz")
        self.manifest("gzt", version="1.0", url=url, hash=digest, bin="gzt")
        self.spork("install", "gzt")
        self.assertEqual(self.run_cmd("gzt"), "gzt")

    def test_multiple_urls(self):
        a = self.build / "a"; a.write_text('#!/bin/sh\necho a\n')
        b = self.build / "b"; b.write_text('#!/bin/sh\necho b\n')
        (ua, ha), (ub, hb) = self.serve(a), self.serve(b)
        self.manifest("multi", version="1.0", url=[ua, ub], hash=[ha, hb], bin=["a", "b"])
        self.spork("install", "multi")
        self.assertEqual((self.run_cmd("a"), self.run_cmd("b")), ("a", "b"))

    def test_dmg(self):
        src = self.tree("dmgsrc", {"bin/dmgtool": '#!/bin/sh\necho from dmg\n'})
        dmg = self.build / "dmgtool.dmg"
        subprocess.run(["hdiutil", "create", "-quiet", "-srcfolder", src, "-volname", "dmgtool",
                        "-format", "UDZO", dmg], check=True)
        url, digest = self.serve(dmg)
        self.manifest("dmgtool", version="1.0", url=url, hash=digest, bin="bin/dmgtool")
        self.spork("install", "dmgtool")
        self.assertEqual(self.run_cmd("dmgtool"), "from dmg")
        mounts = subprocess.run(["mount"], capture_output=True, text=True).stdout
        self.assertNotIn("spork.", mounts, "disk image left mounted")

    def test_pkg_payload_without_scripts(self):
        root = self.tree("pkgroot", {"bin/pkgtool": '#!/bin/sh\necho from pkg\n'})
        scripts = self.tree("pkgscripts", {"postinstall": f'#!/bin/sh\ntouch "{self.home}/RAN"\n'})
        (scripts / "postinstall").chmod(0o755)
        pkg = self.build / "pkgtool.pkg"
        subprocess.run(["pkgbuild", "--quiet", "--root", root, "--scripts", scripts,
                        "--identifier", "test.spork.pkgtool", "--version", "1.0",
                        "--install-location", "/usr/local", pkg], check=True)
        url, digest = self.serve(pkg)
        self.manifest("pkgtool", version="1.0", url=url, hash=digest, bin="bin/pkgtool")
        self.spork("install", "pkgtool")
        self.assertEqual(self.run_cmd("pkgtool"), "from pkg")
        self.assertFalse((self.home / "RAN").exists(), "pkg installer script was run")

    def test_missing_extract_dir(self):
        self.publish_tool("hello", "1.0", extract_dir="wrong")
        self.assertIn("extract_dir 'wrong' not found", self.spork("install", "hello", ok=False).stderr)

    # ------------------------------------------------------------ updates

    def test_update_keeps_links_and_removes_old_version(self):
        self.publish_tool("hello", "1.0")
        self.spork("install", "hello")
        self.assertIn("Everything is up to date", self.spork("status").stdout)

        self.publish_tool("hello", "2.0")
        self.assertRegex(self.spork("status").stdout, r"hello\s+1\.0 -> 2\.0")
        self.assertIn("Everything is up to date", self.spork("update", "--all").output)
        self.assertEqual(self.installed("hello"), "2.0")
        self.assertEqual(self.run_cmd("hello"), "hello 2.0")
        self.assertFalse((self.spork_home / "apps/hello/1.0").exists())
        self.assertIn("up to date", self.spork("update", "hello").stdout)

    def test_hold(self):
        self.publish_tool("hello", "1.0")
        self.spork("install", "hello")
        self.spork("hold", "hello")
        self.assertIn("(held)", self.spork("list").stdout)
        self.publish_tool("hello", "2.0")
        self.assertIn("(held)", self.spork("status").stdout)
        self.assertIn("held at 1.0", self.spork("update", "hello").output)
        self.assertEqual(self.installed("hello"), "1.0")
        self.spork("unhold", "hello")
        self.spork("update", "hello")
        self.assertEqual(self.installed("hello"), "2.0")

    def test_force_reinstall_same_version(self):
        self.publish_tool("hello", "1.0")
        self.spork("install", "hello")
        out = self.spork("install", "--force", "hello").output
        self.assertIn("using cached", out)
        self.assertEqual(self.run_cmd("hello"), "hello 1.0")

    # ------------------------------------------------------------ drawers, search, sources

    def test_drawer_priority_and_explicit_choice(self):
        extra = self.home / "extra"; extra.mkdir()
        self.publish_tool("hello", "1.0")
        self.publish_tool("hello", "9.0", where=extra)
        self.spork("drawer", "add", "extra", str(extra))
        self.assertRegex(self.spork("drawer", "list").stdout, r"extra\s+1 packages\s+link ->")

        self.spork("install", "hello")
        self.assertEqual(self.installed("hello"), "1.0")
        self.spork("install", "extra/hello")
        self.assertEqual(self.installed("hello"), "9.0")
        self.assertEqual(self.receipt("hello")["drawer"], "extra")

        self.assertIn("already exists", self.spork("drawer", "add", "extra", str(extra), ok=False).stderr)
        self.spork("drawer", "rm", "extra")
        self.assertNotIn("extra", self.spork("drawer", "list").stdout)

    def test_manifests_in_drawer_subfolder(self):
        repo = self.home / "repo"; (repo / "drawer").mkdir(parents=True)
        self.publish_tool("nested", "1.0", where=repo / "drawer")
        self.spork("drawer", "add", "repo", str(repo))
        self.spork("install", "nested")
        self.assertEqual(self.run_cmd("nested"), "nested 1.0")

    def test_search(self):
        self.publish_tool("alpha", "1.0", description="Parses JSON quickly")
        self.publish_tool("beta", "1.0", description="Something else")
        out = self.spork("search", "json").stdout
        self.assertIn("alpha", out)
        self.assertNotIn("beta", out)
        self.assertIn("beta", self.spork("search", "bet").stdout)
        self.assertIn("No packages found", self.spork("search", "zzz").stdout)

    def test_install_from_file_and_url(self):
        m = self.publish_tool("local", "1.0", where=self.build)
        self.spork("install", str(m))
        self.assertEqual(self.receipt("local")["source"], str(m))

        self.publish_tool("remote", "1.0", where=self.www)
        url = f"{self.base_url}/remote.json"
        self.spork("install", url)
        self.assertEqual(self.receipt("remote")["source"], url)
        self.publish_tool("remote", "2.0", where=self.www)
        self.assertRegex(self.spork("status").stdout, r"remote\s+1\.0 -> 2\.0")

    # ------------------------------------------------------------ dependencies, arch, hooks

    def test_depends(self):
        self.publish_tool("lib", "1.0")
        self.publish_tool("app", "1.0", depends=["lib"])
        self.assertIn("Installing dependency lib", self.spork("install", "app").output)
        self.assertEqual(self.installed("lib"), "1.0")

    def test_architecture_selection(self):
        builds = {}
        for arch in ("arm64", "x86_64"):
            url, digest = self.serve(self.tool_archive("multi", "1.0", say=arch),
                                     f"multi-{arch}.tar.gz")
            builds[arch] = {"url": url, "hash": digest}
        self.manifest("multi", version="1.0", architecture=builds,
                      extract_dir="multi-1.0", bin="bin/multi")
        self.spork("install", "multi", env={"SPORK_ARCH": "x86_64"})
        self.assertEqual(self.run_cmd("multi"), "x86_64")
        self.spork("install", "--force", "multi")
        self.assertEqual(self.run_cmd("multi"), "arm64")
        self.assertEqual(self.receipt("multi")["arch"], "arm64")

    def test_intel_only_falls_back_to_rosetta(self):
        url, digest = self.serve(self.tool_archive("old", "1.0"))
        self.manifest("old", version="1.0", bin="bin/old",
                      architecture={"x86_64": {"url": url, "hash": digest, "extract_dir": "old-1.0"}})
        self.assertIn("Rosetta", self.spork("install", "old").stderr)
        self.assertEqual(self.receipt("old")["arch"], "x86_64")
        self.manifest("armonly", version="1.0",
                      architecture={"arm64": {"url": url, "hash": digest}})
        self.assertIn("not available for x86_64",
                      self.spork("install", "armonly", ok=False, env={"SPORK_ARCH": "x86_64"}).stderr)

    def test_hooks(self):
        self.publish_tool(
            "hooked", "1.0",
            pre_install='echo pre > pre.txt',
            post_install=['echo "$version $arch" > "$dir/post.txt"',
                          'echo "$bindir|$appdir|$persist_dir" >> post.txt'],
            pre_uninstall=f'touch "{self.home}/pre_uninstall_ran"',
        )
        self.spork("install", "hooked")
        cur = self.spork_home / "apps/hooked/current"
        self.assertEqual((cur / "pre.txt").read_text().strip(), "pre")
        lines = (cur / "post.txt").read_text().splitlines()
        self.assertEqual(lines[0], "1.0 universal")
        self.assertEqual(lines[1], f"{self.spork_home}/bin|{self.appdir}|{self.spork_home}/persist/hooked")
        self.spork("uninstall", "hooked")
        self.assertTrue((self.home / "pre_uninstall_ran").exists())

    def test_failing_hook_stops_install(self):
        self.publish_tool("bad", "1.0", pre_install="exit 3")
        self.assertIn("pre_install failed", self.spork("install", "bad", ok=False).stderr)
        self.assertIsNone(self.installed("bad"))
        self.assertFalse((self.spork_home / "bin/bad").exists())

    def test_notes_are_shown(self):
        self.publish_tool("noted", "1.0", notes=["Line one", "Line two"])
        out = self.spork("install", "noted").stdout
        self.assertIn("Notes:\n    Line one\n    Line two", out)

    # ------------------------------------------------------------ command links

    def test_command_conflicts(self):
        self.publish_tool("first", "1.0", bin=[["bin/first", "shared"]])
        self.publish_tool("second", "1.0", bin=[["bin/second", "shared"]])
        self.spork("install", "first")
        self.assertIn("already provided by first", self.spork("install", "second").stderr)
        self.assertEqual(self.run_cmd("shared"), "first 1.0")

        self.spork("install", "--force", "second")
        self.assertEqual(self.run_cmd("shared"), "second 1.0")
        self.spork("uninstall", "first")
        self.assertEqual(self.run_cmd("shared"), "second 1.0", "uninstalling first removed second's link")

    def test_unowned_command_needs_force(self):
        (self.spork_home / "bin").mkdir(parents=True, exist_ok=True)
        (self.spork_home / "bin/hello").write_text("mine")
        self.publish_tool("hello", "1.0")
        self.assertIn("another file", self.spork("install", "hello").stderr)
        self.assertEqual((self.spork_home / "bin/hello").read_text(), "mine")

    def test_refuses_to_replace_spork(self):
        self.publish_tool("evil", "1.0", bin=[["bin/evil", "spork"]])
        self.assertIn("refusing to replace the 'spork' command", self.spork("install", "evil").stderr)
        self.assertFalse((self.spork_home / "bin/spork").exists())

    def test_missing_command_is_skipped(self):
        self.publish_tool("hello", "1.0", bin=["bin/hello", "bin/ghost"])
        self.assertIn("command 'bin/ghost' not found", self.spork("install", "hello").stderr)
        self.assertEqual(self.run_cmd("hello"), "hello 1.0")

    # ------------------------------------------------------------ apps

    def make_app_zip(self, version):
        src = self.tree(f"app-{version}", {
            "Foo.app/Contents/MacOS/Foo": f'#!/bin/sh\necho "Foo {version}"\n',
            "Foo.app/Contents/Info.plist": (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<plist version="1.0"><dict>'
                '<key>CFBundleExecutable</key><string>Foo</string>'
                '<key>CFBundleIdentifier</key><string>test.spork.foo</string>'
                '</dict></plist>\n'),
        })
        out = self.build / f"foo-{version}.zip"
        subprocess.run(["ditto", "-c", "-k", "--keepParent", src / "Foo.app", out], check=True)
        return out

    def publish_app(self, version):
        url, digest = self.serve(self.make_app_zip(version))
        return self.manifest("foo", version=version, url=url, hash=digest, app="Foo.app",
                             bin=[["Foo.app/Contents/MacOS/Foo", "foo"]])

    def test_app_install_update_uninstall(self):
        self.publish_app("1.0")
        self.spork("install", "foo")
        app = self.appdir / "Foo.app"
        self.assertTrue(app.is_dir())
        self.assertEqual(self.run_cmd("foo"), "Foo 1.0")
        self.assertIn("Apps:        Foo.app", self.spork("info", "foo").stdout)

        self.publish_app("2.0")
        self.spork("update", "foo")
        self.assertEqual(self.run_cmd("foo"), "Foo 2.0")

        self.spork("uninstall", "foo")
        self.assertFalse(app.exists())
        self.assertFalse((self.spork_home / "bin/foo").exists())

    def test_unowned_app_needs_force(self):
        (self.appdir / "Foo.app").mkdir(parents=True)
        self.publish_app("1.0")
        self.assertIn("wasn't installed by spork", self.spork("install", "foo", ok=False).stderr)
        self.assertTrue((self.appdir / "Foo.app").is_dir())
        self.spork("install", "--force", "foo")
        self.assertEqual(self.run_cmd("foo"), "Foo 1.0")

    # ------------------------------------------------------------ persisted data

    def test_persist_survives_update_and_uninstall(self):
        def publish(v):
            self.publish_tool("keeper", v, persist=["data", ["conf/settings.ini", "settings.ini"]],
                              extra={"conf/settings.ini": f"shipped {v}\n", "data/default.txt": "d\n"})

        publish("1.0")
        self.spork("install", "keeper")
        keep = self.spork_home / "persist/keeper"
        cur = self.spork_home / "apps/keeper/current"
        self.assertTrue((cur / "data").is_symlink())
        self.assertEqual((keep / "data/default.txt").read_text(), "d\n")
        self.assertEqual((keep / "settings.ini").read_text(), "shipped 1.0\n")

        (keep / "settings.ini").write_text("mine\n")
        (cur / "data/user.db").write_text("rows\n")
        publish("2.0")
        self.spork("update", "keeper")
        self.assertEqual((cur / "conf/settings.ini").read_text(), "mine\n")
        self.assertEqual((cur / "data/user.db").read_text(), "rows\n")

        self.assertIn("kept your data", self.spork("uninstall", "keeper").stdout)
        self.assertTrue((keep / "settings.ini").exists())
        self.spork("install", "keeper")
        self.assertEqual((cur / "conf/settings.ini").read_text(), "mine\n")

        self.spork("uninstall", "--purge", "keeper")
        self.assertFalse(keep.exists())

    def test_purge_after_plain_uninstall(self):
        self.publish_tool("keeper", "1.0", persist="data")
        self.spork("install", "keeper")
        self.spork("uninstall", "keeper")
        self.assertTrue((self.spork_home / "persist/keeper/data").is_dir())
        self.assertIn("Deleted saved data", self.spork("uninstall", "--purge", "keeper").stdout)
        self.assertFalse((self.spork_home / "persist/keeper").exists())

    def test_bad_persist_paths_rejected_before_download(self):
        for path, msg in [("../escape", "plain path"), ("/abs", "relative"), ("Foo.app/x", "app bundle")]:
            with self.subTest(path=path):
                self.manifest("bad", version="1.0", url=f"{self.base_url}/never-served.tar.gz",
                              persist=[path])
                err = self.spork("install", "bad", ok=False).stderr
                self.assertIn(msg, err)
                self.assertNotIn("download failed", err)

    # ------------------------------------------------------------ PATH

    def test_env_add_path_and_shellenv(self):
        self.publish_tool("pathy", "1.0", env_add_path=["tools", "$persist_dir/global/bin", "."])
        self.spork("install", "pathy")
        cur = f"{self.spork_home}/apps/pathy/current"
        expect = f'{self.spork_home}/bin:{cur}/tools:{self.spork_home}/persist/pathy/global/bin:{cur}'
        self.assertEqual(self.spork("shellenv").stdout.strip(), f'export PATH="{expect}:$PATH"')
        self.assertIn("fish_add_path -g", self.spork("shellenv", env={"SHELL": "/opt/fish"}).stdout)
        self.spork("uninstall", "pathy")
        self.assertEqual(self.spork("shellenv").stdout.strip(), f'export PATH="{self.spork_home}/bin:$PATH"')

    def test_bad_env_add_path_rejected(self):
        for p in ("/usr/bin", "../up", "$persist_dir/../x"):
            with self.subTest(path=p):
                self.publish_tool("pathy", "1.0", env_add_path=[p])
                self.spork("install", "pathy", ok=False)
                self.assertIsNone(self.installed("pathy"))

    # ------------------------------------------------------------ mirrors and cache

    def test_mirror_rules(self):
        # The specific rule comes first, so "last match wins" would fail.
        self.spork("mirror", "add", "https://github.com/org/", "https://m.example/org/")
        self.spork("mirror", "add", "https://github.com/", "https://m.example/gh/")
        self.assertEqual(self.spork("mirror", "test", "https://github.com/org/x").stdout.strip(),
                         "https://m.example/org/x")
        self.assertEqual(self.spork("mirror", "test", "https://github.com/other/x").stdout.strip(),
                         "https://m.example/gh/other/x")
        self.assertEqual(self.spork("mirror", "test", "https://example.com/x").stdout.strip(),
                         "https://example.com/x")

        self.spork("mirror", "add", "https://github.com/", "https://m2.example/")  # replaces the rule
        self.assertEqual(self.spork("mirror", "test", "https://github.com/a").stdout.strip(),
                         "https://m2.example/a")
        self.assertIn("https://m2.example/", self.spork("mirror", "list").stdout)

        self.spork("mirror", "rm", "https://github.com/org/")
        self.assertIn("no mirror rule", self.spork("mirror", "rm", "https://github.com/org/", ok=False).stderr)
        self.assertIn("can't contain spaces", self.spork("mirror", "add", "a b", "c", ok=False).stderr)

    def test_shared_mirrors_file_with_comments(self):
        shared = self.home / "team-mirrors"
        shared.write_text("# team rules\nhttps://a.example/ https://b.example/\n")
        out = self.spork("mirror", "test", "https://a.example/x",
                         env={"SPORK_MIRRORS_FILE": str(shared)}).stdout
        self.assertEqual(out.strip(), "https://b.example/x")

    def test_install_through_mirror(self):
        url, digest = self.serve(self.tool_archive("hello", "1.0"))
        blocked = "https://downloads.example.invalid/"
        self.manifest("hello", version="1.0", url=url.replace(self.base_url + "/", blocked),
                      hash=digest, extract_dir="hello-1.0", bin="bin/hello")
        self.assertIn("download failed", self.spork("install", "hello", ok=False).stderr)

        self.spork("mirror", "add", blocked, self.base_url + "/")
        out = self.spork("install", "hello").output
        self.assertIn(f"via mirror {self.base_url}/hello-1.0.tar.gz", out)
        self.assertEqual(self.run_cmd("hello"), "hello 1.0")

    def test_cache(self):
        self.publish_tool("hello", "1.0")
        self.spork("install", "hello")
        self.assertIn("hello#1.0#hello-1.0.tar.gz", self.spork("cache").stdout)
        self.spork("uninstall", "hello")
        self.assertIn("using cached", self.spork("install", "hello").output)
        self.spork("cache", "rm", "hello")
        self.assertIn("Cache is empty", self.spork("cache").stdout)

    def test_cleanup(self):
        self.publish_tool("hello", "1.0")
        self.publish_tool("other", "1.0")
        self.spork("install", "hello", "other")
        cache = self.spork_home / "cache"
        (cache / "hello#2.0#hello-2.0.tar.gz.part").write_text("partial")

        out = self.spork("cleanup", "hello").stdout
        self.assertIn("Removed 2 cached file(s)", out)
        self.assertEqual([p.name for p in cache.iterdir()], ["other#1.0#other-1.0.tar.gz"])

        self.assertIn("Removed 1 cached file(s)", self.spork("cleanup").stdout)
        self.assertTrue(cache.is_dir(), "cache folder should be kept")
        self.assertEqual(list(cache.iterdir()), [])
        self.assertIn("Nothing to clean up", self.spork("cleanup").stdout)
        self.assertEqual(self.run_cmd("hello"), "hello 1.0")  # installed packages untouched

    def test_cleanup_old_versions(self):
        self.publish_tool("hello", "1.0")
        self.spork("install", "hello")
        apps = self.spork_home / "apps"
        (apps / "hello" / "0.9" / "bin").mkdir(parents=True)       # left by a failed update
        (apps / "broken" / "2.0").mkdir(parents=True)              # failed first install, no "current"

        self.spork("cache", "rm")                                  # cache only: versions stay
        self.assertTrue((apps / "hello" / "0.9").exists())

        out = self.spork("cleanup", "hello").stdout
        self.assertIn("removed hello 0.9", out)
        self.assertIn("Removed 1 old version(s), freed", out)
        self.assertEqual(sorted(p.name for p in (apps / "hello").iterdir() if p.is_dir()),
                         ["1.0", "current"])
        self.assertTrue((apps / "broken").exists())

        self.assertIn("removed broken 2.0", self.spork("cleanup").stdout)
        self.assertFalse((apps / "broken").exists())
        self.assertEqual(self.run_cmd("hello"), "hello 1.0")
        self.assertRegex(self.spork("list").stdout, r"hello\s+1\.0")

        self.assertIn("invalid package name", self.spork("cleanup", "../x", ok=False).stderr)

    def test_hash_command(self):
        f = self.build / "x"; f.write_text("hi")
        expect = "sha256:" + sha256(f)
        self.assertEqual(self.spork("hash", str(f)).stdout.strip(), expect)
        url, _ = self.serve(f)
        self.assertEqual(self.spork("hash", url).stdout.strip(), expect)

    # ------------------------------------------------------------ self-update

    def git(self, cwd, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       cwd=cwd, env=self.env, check=True, capture_output=True)

    def upstream(self):
        """A local git repo standing in for spork-pm/spork, holding this spork."""
        repo = self.build / "upstream"
        repo.mkdir()
        shutil.copy(SPORK, repo / "spork")
        self.git(repo, "init", "-q", "-b", "main")
        self.git(repo, "add", "spork")
        self.git(repo, "commit", "-q", "-m", "v1")
        return repo

    def release(self, repo, version, marker="", text=None):
        """Commit a new spork to the repo: a new version, plus a marker in 'spork update'."""
        if text is None:
            text = SPORK.read_text().replace("SPORK_VERSION=0.1.0", f"SPORK_VERSION={version}")
            text = text.replace('say "Updating drawers"', f'say "Updating drawers{marker}"')
        (repo / "spork").write_text(text)
        self.git(repo, "commit", "-q", "-am", version)

    def install(self, *args, repo=None):
        # A linked "apps" drawer keeps install.sh from cloning the real one.
        (self.home / "apps-drawer").mkdir(exist_ok=True)
        self.spork("drawer", "add", "apps", str(self.home / "apps-drawer"))
        env = {**self.env, "SPORK_REPO": repo or "file:///nonexistent"}
        p = subprocess.run([str(SPORK.parent / "install.sh"), "--no-modify-path", *args],
                           env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def installed_spork(self, *args, env=None):
        p = subprocess.run([str(self.spork_home / "bin/spork"), *args], env={**self.env, **(env or {})},
                           capture_output=True, text=True, timeout=120)
        p.output = p.stdout + p.stderr
        self.assertEqual(p.returncode, 0, p.output)
        return p

    def test_self_update_from_git(self):
        repo = self.upstream()
        self.install(repo=f"file://{repo}")
        self_dir = self.spork_home / "self"
        self.assertTrue((self_dir / ".git").is_dir())
        self.assertEqual(os.readlink(self.spork_home / "bin/spork"), str(self_dir / "spork"))
        self.assertIn("spork 0.1.0", self.installed_spork("version").stdout)
        self.assertIn("spork updates itself from file://", self.installed_spork("doctor", env={"PATH": f"{self.spork_home}/bin:/usr/bin:/bin"}).output)

        self.assertNotIn("Updated spork", self.installed_spork("update").output)

        self.release(repo, "9.9.9", marker=" (new)")
        out = self.installed_spork("update").output
        self.assertIn("Updated spork to 9.9.9", out)
        # The new version ran the rest of the update, once.
        self.assertIn("Updating drawers (new)", out)
        self.assertEqual(out.count("updating spork"), 1)
        self.assertIn("spork 9.9.9", self.installed_spork("version").stdout)

        # Updating specific packages, or opting out, leaves spork alone.
        self.release(repo, "9.9.10")
        self.publish_tool("hello", "1.0")
        self.installed_spork("install", "hello")
        self.assertNotIn("updating spork", self.installed_spork("update", "hello").output)
        self.assertNotIn("updating spork", self.installed_spork("update", env={"SPORK_NO_SELF_UPDATE": "1"}).output)
        self.assertIn("spork 9.9.9", self.installed_spork("version").stdout)

    def test_self_update_keeps_broken_version_out(self):
        repo = self.upstream()
        self.install(repo=f"file://{repo}")
        self.release(repo, "2.0", text="#!/bin/bash\nif then\n")
        out = self.installed_spork("update").output
        self.assertIn("looks broken", out)
        self.assertIn("spork 0.1.0", self.installed_spork("version").stdout)

    def test_self_update_from_download(self):
        # No git and no reachable repo: install.sh installs its own copy as a download.
        p = self.install()
        self.assertIn("installing the copy", p.stdout)
        self_dir = self.spork_home / "self"
        top = self.build / "spork-main"
        top.mkdir()
        (top / "spork").write_text(SPORK.read_text().replace("SPORK_VERSION=0.1.0", "SPORK_VERSION=3.0"))
        (top / "spork").chmod(0o755)
        with tarfile.open(self.www / "spork.tar.gz", "w:gz") as t:
            t.add(top, arcname="spork-main")
        (self_dir / ".spork-source").write_text(f"{self.base_url}/spork.tar.gz\n")

        out = self.installed_spork("update").output
        self.assertIn("Updated spork to 3.0", out)
        self.assertIn("spork 3.0", self.installed_spork("version").stdout)
        self.assertTrue((self_dir / ".spork-source").exists())
        self.assertNotIn("Updated spork", self.installed_spork("update").output)

    def test_linked_install_never_self_updates(self):
        self.install("--link")
        self.assertEqual(os.readlink(self.spork_home / "self"), str(SPORK.parent))
        out = self.installed_spork("update").output
        self.assertNotIn("updating spork", out)
        self.assertIn("won't update itself", self.installed_spork("doctor", env={"PATH": f"{self.spork_home}/bin:/usr/bin:/bin"}).output)

    def test_install_replaces_old_layout(self):
        old = self.spork_home / "libexec"
        old.mkdir(parents=True)
        shutil.copy(SPORK, old / "spork")
        (self.spork_home / "bin").mkdir(exist_ok=True)
        os.symlink(old / "spork", self.spork_home / "bin/spork")
        repo = self.upstream()
        self.install(repo=f"file://{repo}")
        self.assertFalse(old.exists())
        self.assertEqual(os.readlink(self.spork_home / "bin/spork"), str(self.spork_home / "self/spork"))

    # ------------------------------------------------------------ doctor

    def test_doctor(self):
        out = self.spork("doctor", env={"PATH": f"{self.spork_home}/bin:/usr/bin:/bin"}).output
        self.assertIn("is writable", out)
        self.assertIn("Drawers: main", out)
        self.assertIn("All good", out)


if __name__ == "__main__":
    unittest.main()
