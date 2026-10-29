"""Offline tests for tools/drawer-validate and tools/drawer-test.
Run with: python3 -m unittest discover -s tools/tests"""

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..")
_loader = importlib.machinery.SourceFileLoader("drawer_validate", os.path.join(TOOLS, "drawer-validate"))
_spec = importlib.util.spec_from_loader("drawer_validate", _loader)
dv = importlib.util.module_from_spec(_spec)
_loader.exec_module(dv)
cv = dv.cv

HASH = "a" * 64


def manifest(**over):
    m = {
        "version": "1.2.0",
        "description": "A tool",
        "homepage": "https://github.com/o/tool",
        "architecture": {"arm64": {"url": "https://h/v1.2.0/tool-1.2.0-arm64.tar.gz", "hash": "sha256:" + HASH}},
        "checkver": "github",
        "autoupdate": {"architecture": {"arm64": {"url": "https://h/v$version/tool-$version-arm64.tar.gz"}}},
    }
    m.update(over)
    return m


class Fields(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(dv.check_fields(manifest()), [])
        self.assertEqual(dv.check_fields({"version": "1", "description": "d", "homepage": "h", "url": "u"}), [])

    def test_missing(self):
        self.assertEqual(dv.check_fields([]), ["not a JSON object"])
        m = manifest(description="", architecture={"arm64": {"url": "u"}, "x86_64": {"hash": "h"}})
        del m["homepage"]
        self.assertEqual(dv.check_fields(m), ["missing description", "missing homepage",
                                              "missing url in architecture.x86_64"])
        m = manifest()
        del m["architecture"]
        self.assertEqual(len(dv.check_fields(m)), 1)


class Compare(unittest.TestCase):
    def test_normalize_hash(self):
        self.assertEqual(dv.normalize_hash("ABC"), "sha256:abc")
        self.assertEqual(dv.normalize_hash("sha512:ABC"), "sha512:abc")
        self.assertEqual(dv.normalize_hash(["a", "sha1:b"]), ["sha256:a", "sha1:b"])

    def test_differences(self):
        a = {"version": "1", "architecture": {"arm64": {"url": "x", "hash": "h"}}, "bin": ["a"]}
        b = {"version": "1", "architecture": {"arm64": {"url": "y", "hash": "h", "extract_dir": "d"}}, "bin": ["a"]}
        self.assertEqual(dv.differences(a, b), [("architecture.arm64.url", "x", "y"),
                                                ("architecture.arm64.extract_dir", None, "d")])
        self.assertEqual(dv.differences(a, a), [])

    def test_match_groups(self):
        auto = {"url": "https://h/$version/x-$matchCommit.zip"}
        self.assertTrue(dv.uses_match_groups(auto, {"commit": "abc"}))
        self.assertFalse(dv.uses_match_groups(auto, {"build": "1"}))
        self.assertFalse(dv.uses_match_groups({"url": "$matchHead"}, {"version": "1"}))


class Autoupdate(unittest.TestCase):
    def check(self, m, latest="1.2.0", groups=None, digest="sha256:" + HASH):
        with mock.patch.object(cv, "check_version", return_value=(latest, groups or {})), \
                mock.patch.object(cv, "hash_download", return_value=digest) as dl:
            result = dv.check_autoupdate(m, lambda msg: None)
        return result, dl

    def test_rule_reproduces_manifest(self):
        (errors, warnings), dl = self.check(manifest())
        self.assertEqual((errors, warnings), ([], []))
        dl.assert_called_once_with("https://h/v1.2.0/tool-1.2.0-arm64.tar.gz")

    def test_upstream_newer_still_checks_current_version(self):
        (errors, _), dl = self.check(manifest(), latest="1.3.0")
        self.assertEqual(errors, [])
        dl.assert_called_once_with("https://h/v1.2.0/tool-1.2.0-arm64.tar.gz")

    def test_bare_uppercase_hash_is_fine(self):
        m = manifest()
        m["architecture"]["arm64"]["hash"] = HASH.upper()
        self.assertEqual(self.check(m)[0], ([], []))

    def test_wrong_url_and_hash(self):
        m = manifest()
        m["autoupdate"]["architecture"]["arm64"]["url"] = "https://h/$version/tool-$version-arm64.zip"
        (errors, _), _ = self.check(m, digest="sha256:" + "b" * 64)
        self.assertEqual(len(errors), 2)
        self.assertIn("architecture.arm64.url", errors[0])
        self.assertIn("tool-1.2.0-arm64.zip", errors[0])
        self.assertIn("architecture.arm64.hash", errors[1])

    def test_missing_hash(self):
        m = manifest()
        del m["architecture"]["arm64"]["hash"]
        (errors, _), _ = self.check(m)
        self.assertEqual(len(errors), 1)
        self.assertIn("the manifest has nothing", errors[0])

    def test_checkver_error(self):
        with mock.patch.object(cv, "check_version", side_effect=cv.CheckverError("unsupported jsonpath")):
            errors, _ = dv.check_autoupdate(manifest(), lambda m: None)
        self.assertEqual(errors, ["checkver: unsupported jsonpath"])

    def test_hash_rule_error(self):
        m = manifest()
        m["autoupdate"]["hash"] = {"url": "$baseurl/SHASUMS256.txt"}
        with mock.patch.object(cv, "check_version", return_value=("1.2.0", {})), \
                mock.patch.object(cv, "fetch_text", return_value="nothing here"):
            errors, _ = dv.check_autoupdate(m, lambda msg: None)
        self.assertEqual(len(errors), 1)
        self.assertIn("no hash for tool-1.2.0-arm64.tar.gz", errors[0])

    def test_no_autoupdate(self):
        m = manifest()
        del m["autoupdate"]
        self.assertEqual(len(dv.check_autoupdate(m, print)[0]), 1)
        del m["checkver"]
        self.assertEqual(dv.check_autoupdate(m, print), ([], []))

    def test_match_groups_from_other_version(self):
        m = manifest()
        m["autoupdate"]["architecture"]["arm64"]["url"] = "https://h/$version/$matchCommit.tgz"
        (errors, warnings), dl = self.check(m, latest="1.3.0", groups={"commit": "abc"})
        self.assertEqual(errors, [])
        self.assertIn("named groups", warnings[0])
        dl.assert_not_called()

    def test_older_upstream_warns(self):
        (errors, warnings), _ = self.check(manifest(), latest="1.1.0")
        self.assertEqual(errors, [])
        self.assertIn("older", warnings[0])


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True)


class Picking(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.mkdir(os.path.join(self.root, "drawer"))
        for name in ("a", "b", "c"):
            self.write("drawer/%s.json" % name, {"version": "1"})
        git(self.root, "init", "-q")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "base")
        self.cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def write(self, path, data):
        with open(os.path.join(self.root, path), "w") as f:
            json.dump(data, f)

    def listed(self, *argv):
        with mock.patch("sys.stdout.write") as out:
            self.assertEqual(dv.main(["--list", *argv]), 0)
        return "".join(c.args[0] for c in out.call_args_list).split()

    def test_since(self):
        base = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.write("drawer/b.json", {"version": "2"})
        self.write("drawer/d.json", {"version": "1"})
        self.write("README.md", "x")
        os.remove("drawer/c.json")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "change")
        self.assertEqual(self.listed("--since", base), ["drawer/b.json", "drawer/d.json"])
        self.assertEqual(self.listed("--since", "HEAD"), [])

    def test_all_when_unknown(self):
        all_ = ["drawer/a.json", "drawer/b.json", "drawer/c.json"]
        self.assertEqual(self.listed(), all_)
        with mock.patch("sys.stderr"):
            for since in ("", "0" * 40, "nosuchref"):
                self.assertEqual(self.listed("--since", since), all_)

    def test_packages(self):
        self.assertEqual(self.listed("b", "drawer/a.json"), ["drawer/b.json", "drawer/a.json"])

    def test_offline_run(self):
        self.write("drawer/a.json", {"version": "1", "description": "d", "homepage": "h", "url": "u"})
        with open("drawer/b.json", "w") as f:
            f.write("{oops")
        with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            self.assertEqual(dv.main(["--offline", "a"]), 0)
            self.assertEqual(dv.main(["--offline", "a", "b"]), 1)


class DrawerTest(unittest.TestCase):
    """tools/drawer-test, with a fake spork that logs its calls."""

    def run_it(self, *args, fail=""):
        with tempfile.TemporaryDirectory() as tmp:
            drawer = os.path.join(tmp, "mydrawer")
            os.makedirs(os.path.join(drawer, "drawer"))
            log = os.path.join(tmp, "log")
            fake = os.path.join(tmp, "spork")
            with open(fake, "w") as f:
                f.write('#!/bin/bash\necho "$SPORK_HOME|$*" >> %s\n'
                        '[ "$1 $2" = "install ./drawer/%s.json" ] && exit 1\nexit 0\n' % (log, fail))
            os.chmod(fake, 0o755)
            r = subprocess.run([os.path.join(TOOLS, "drawer-test"), *args], cwd=drawer, capture_output=True,
                               text=True, env=dict(os.environ, SPORK_BIN=fake))
            with open(log) as f:
                calls = [line.rstrip("\n").split("|", 1) for line in f]
            home_left = os.path.exists(calls[0][0])
        return r, calls, home_left

    def test_installs_each(self):
        r, calls, home_left = self.run_it("jq", "drawer/fd.json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(calls[0][1].startswith("drawer add mydrawer /"), calls[0])
        self.assertEqual([c[1] for c in calls[1:]], [
            "install ./drawer/jq.json", "uninstall --purge jq",
            "install ./drawer/fd.json", "uninstall --purge fd"])
        self.assertNotIn(os.path.expanduser("~"), calls[0][0])
        self.assertFalse(home_left)

    def test_failure(self):
        r, calls, _ = self.run_it("jq", "fd", fail="jq")
        self.assertEqual(r.returncode, 1)
        self.assertIn("::error file=drawer/jq.json::jq failed to install", r.stdout)
        self.assertIn("install ./drawer/fd.json", [c[1] for c in calls])


if __name__ == "__main__":
    unittest.main()
