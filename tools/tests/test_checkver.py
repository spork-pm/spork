"""Offline tests for tools/checkver. Run with: python3 -m unittest discover -s tools/tests"""

import importlib.machinery
import importlib.util
import os
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
_loader = importlib.machinery.SourceFileLoader("checkver", os.path.join(HERE, "..", "checkver"))
_spec = importlib.util.spec_from_loader("checkver", _loader)
cv = importlib.util.module_from_spec(_spec)
_loader.exec_module(cv)


class Versions(unittest.TestCase):
    def test_compare(self):
        newer = [("1.10", "1.9"), ("2.0.0", "1.99"), ("1.0", "1.0-rc1"), ("1.0-2", "1.0"),
                 ("2.56.0-3", "2.56.0-2"), ("1.0-rc2", "1.0-rc1"), ("1.0-rc1", "1.0-beta")]
        for a, b in newer:
            self.assertEqual(cv.compare_versions(a, b), 1, (a, b))
            self.assertEqual(cv.compare_versions(b, a), -1, (b, a))
        self.assertEqual(cv.compare_versions("1.2.3", "1.2.3"), 0)

    def test_vars(self):
        v = cv.version_vars("2.56.0-2", {"commit": "a44aeca"})
        self.assertEqual(v["majorVersion"], "2")
        self.assertEqual(v["patchVersion"], "0")
        self.assertEqual(v["matchHead"], "2.56.0")
        self.assertEqual(v["matchTail"], "-2")
        self.assertEqual(v["preReleaseVersion"], "2")
        self.assertEqual(v["cleanVersion"], "25602")
        self.assertEqual(v["underscoreVersion"], "2_56_0_2")
        self.assertEqual(v["matchCommit"], "a44aeca")

    def test_substitute(self):
        v = cv.version_vars("1.2.3", {})
        self.assertEqual(cv.substitute("a/$version/$majorVersion.x/$dir", v), "a/1.2.3/1.x/$dir")
        self.assertEqual(cv.substitute("$VERSION", v), "1.2.3")
        self.assertEqual(cv.substitute("gh_$version_macOS.zip", v), "gh_1.2.3_macOS.zip")
        self.assertEqual(cv.substitute("$majorVersion$minorVersion", v), "12")
        self.assertEqual(cv.substitute(["$version", {"k": "$minorVersion"}], v), ["1.2.3", {"k": "2"}])


class JsonPath(unittest.TestCase):
    data = [{"version": "v26.1.0", "lts": False}, {"version": "v24.2.0", "lts": "Krypton"},
            {"version": "v22.9.0", "lts": "Jod"}]

    def test_paths(self):
        self.assertEqual(cv.jsonpath(self.data, "$[0].version"), ["v26.1.0"])
        self.assertEqual(cv.jsonpath(self.data, "$[-1].version"), ["v22.9.0"])
        self.assertEqual(cv.jsonpath(self.data, "$[?(@.lts)].version"), ["v24.2.0", "v22.9.0"])
        self.assertEqual(cv.jsonpath(self.data, "$[?(@.lts == 'Jod')].version"), ["v22.9.0"])
        self.assertEqual(cv.jsonpath(self.data, "$[?(@.lts != false)].version"), ["v24.2.0", "v22.9.0"])
        self.assertEqual(cv.jsonpath({"a": {"b-c": 1}}, "$.a['b-c']"), [1])
        self.assertEqual(cv.jsonpath({"a": [1, 2]}, "$.a[*]"), [1, 2])
        with self.assertRaises(cv.CheckverError):
            cv.jsonpath(self.data, "$..version")


RELEASE = """{"tag_name": "v2.56.0-3", "assets": [{"browser_download_url":
 "https://github.com/desktop/dugite-native/releases/download/v2.56.0-3/dugite-native-v2.56.0-b5c1d2e-macOS-arm64.tar.gz"}]}"""


class CheckVersion(unittest.TestCase):
    def run_check(self, manifest, text):
        with mock.patch.object(cv, "fetch_text", return_value=text) as fetch:
            result = cv.check_version(manifest)
        return result, fetch.call_args[0][0]

    def test_github_shorthand(self):
        (version, _), url = self.run_check(
            {"checkver": "github", "homepage": "https://github.com/sharkdp/fd"}, '{"tag_name": "v10.6.0"}')
        self.assertEqual(version, "10.6.0")
        self.assertEqual(url, "https://api.github.com/repos/sharkdp/fd/releases/latest")

    def test_github_prefixed_tag(self):
        (version, _), _ = self.run_check({"checkver": {"github": "jqlang/jq"}}, '{"tag_name":"jq-1.8.3"}')
        self.assertEqual(version, "1.8.3")

    def test_named_groups(self):
        regex = r"download/v(?<version>[\d.]+-\d+)/dugite-native-v[\d.]+-(?<commit>[0-9a-f]+)-macOS-arm64"
        (version, groups), _ = self.run_check({"checkver": {"github": "desktop/dugite-native", "regex": regex}}, RELEASE)
        self.assertEqual(version, "2.56.0-3")
        self.assertEqual(groups["commit"], "b5c1d2e")

    def test_jsonpath_and_replace(self):
        m = {"checkver": {"url": "https://x/index.json", "jsonpath": "$[?(@.lts)].version",
                          "regex": r"v(\d+)\.(\d+)\.(\d+)", "replace": "${1}.${2}"}}
        (version, _), _ = self.run_check(m, '[{"version":"v26.1.0","lts":false},{"version":"v24.2.0","lts":"K"}]')
        self.assertEqual(version, "24.2")


class Autoupdate(unittest.TestCase):
    def test_architectures_and_checksum_file(self):
        manifest = {
            "version": "24.1.0",
            "architecture": {"arm64": {"url": "old", "hash": "old", "extract_dir": "old"}},
            "bin": "bin/node",
            "autoupdate": {
                "architecture": {"arm64": {"url": "https://n/v$version/node-v$version-darwin-arm64.tar.gz",
                                           "extract_dir": "node-v$version-darwin-arm64"}},
                "hash": {"url": "$baseurl/SHASUMS256.txt"},
            },
        }
        sums = ("a" * 64 + "  node-v24.2.0-darwin-arm64.tar.gz\n"
                + "b" * 64 + "  node-v24.2.0-darwin-arm64.tar.xz\n")
        with mock.patch.object(cv, "fetch_text", return_value=sums) as fetch:
            out = cv.autoupdate(manifest, "24.2.0", {}, lambda m: None)
        fetch.assert_called_once_with("https://n/v24.2.0/SHASUMS256.txt")
        arm = out["architecture"]["arm64"]
        self.assertEqual(out["version"], "24.2.0")
        self.assertEqual(arm["url"], "https://n/v24.2.0/node-v24.2.0-darwin-arm64.tar.gz")
        self.assertEqual(arm["extract_dir"], "node-v24.2.0-darwin-arm64")
        self.assertEqual(arm["hash"], "sha256:" + "a" * 64)
        self.assertEqual(list(out), list(manifest))  # key order kept
        self.assertEqual(manifest["version"], "24.1.0")  # input untouched

    def test_download_hash_keeps_rename_fragment(self):
        manifest = {"version": "1", "url": "old#/jq", "hash": "x",
                    "autoupdate": {"url": "https://h/jq-$version/jq-macos#/jq"}}
        with mock.patch.object(cv, "hash_download", return_value="sha256:cc") as dl:
            out = cv.autoupdate(manifest, "2", {}, lambda m: None)
        dl.assert_called_once_with("https://h/jq-2/jq-macos")
        self.assertEqual(out["url"], "https://h/jq-2/jq-macos#/jq")
        self.assertEqual(out["hash"], "sha256:cc")

    def test_url_list(self):
        manifest = {"version": "1", "url": ["a", "b"], "hash": ["x", "y"],
                    "autoupdate": {"url": ["https://h/$version/a", "https://h/$version/b"]}}
        with mock.patch.object(cv, "hash_download", side_effect=["sha256:1", "sha256:2"]):
            out = cv.autoupdate(manifest, "2", {}, lambda m: None)
        self.assertEqual(out["hash"], ["sha256:1", "sha256:2"])

    def test_no_autoupdate(self):
        with self.assertRaises(cv.CheckverError):
            cv.autoupdate({"version": "1"}, "2", {}, lambda m: None)


if __name__ == "__main__":
    unittest.main()
