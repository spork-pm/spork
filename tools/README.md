# Auto-updating manifests

Like Scoop's `checkver` / `autoupdate`, a manifest can say how to find its latest version and how
to build the new download URLs from it. A scheduled GitHub Actions workflow then keeps the
drawer up to date: it rewrites each outdated manifest (new `version`, `url`, `hash`,
`extract_dir`), installs it with spork on macOS to make sure it works, and commits it.

These tools are for drawer maintainers. spork itself ignores both fields.

## Example

```json
{
    "version": "10.5.0",
    "homepage": "https://github.com/sharkdp/fd",
    "architecture": {
        "arm64": {
            "url": "https://github.com/sharkdp/fd/releases/download/v10.5.0/fd-v10.5.0-aarch64-apple-darwin.tar.gz",
            "hash": "sha256:…",
            "extract_dir": "fd-v10.5.0-aarch64-apple-darwin"
        }
    },
    "bin": "fd",
    "checkver": "github",
    "autoupdate": {
        "architecture": {
            "arm64": {
                "url": "https://github.com/sharkdp/fd/releases/download/v$version/fd-v$version-aarch64-apple-darwin.tar.gz",
                "extract_dir": "fd-v$version-aarch64-apple-darwin"
            }
        }
    }
}
```

## `checkver`: finding the latest version

| Form | Meaning |
|---|---|
| `"github"` | Latest GitHub release of the `homepage` repo. The version is the tag without its prefix (`v1.2.3`, `jq-1.2.3` → `1.2.3`). |
| `{"github": "owner/repo"}` | Same, for another repo (or a full `https://github.com/…` URL). |
| `{"github": "…", "regex": "…"}` | Match `regex` against the release's API JSON, to read the version (or other parts) from tag or asset names. |
| `{"url": "…", "regex": "…"}` | Download a page and match `regex` against it. |
| `{"url": "…", "jsonpath": "…"}` | Download JSON and pick a value. Add `regex` to cut the version out of it. |
| `"…regex…"` | Match the regex against the `homepage` page. |

- The version is the `version` named group, else the first group, else the whole match.
- Other named groups become variables for `autoupdate`: `(?<commit>[0-9a-f]+)` gives `$matchCommit`.
  Both `(?<name>…)` and Python's `(?P<name>…)` work.
- `"replace": "${1}.${2}"` builds the version from groups instead.
- `jsonpath` supports `$.a.b`, `$['a-b']`, `$[0]`, `$[-1]`, `$[*]`, `$[?(@.key)]` (key is truthy) and
  `$[?(@.key == 'x')]` / `!=`. The first match is used.
- A manifest is only updated when the new version is newer, so a "latest" release that's actually a
  backport never downgrades it.

## `autoupdate`: building the new manifest

Every field in `autoupdate` (and in `autoupdate.architecture.<arch>`) is copied into the manifest
with these variables filled in. Fields usually set are `url` and `extract_dir`, but any field works.

| Variable | For `2.56.0-2` |
|---|---|
| `$version` | `2.56.0-2` |
| `$majorVersion` `$minorVersion` `$patchVersion` `$buildVersion` | `2` `56` `0` `2` |
| `$matchHead` / `$matchTail` | `2.56.0` / `-2` (the leading dotted numbers, and the rest) |
| `$preReleaseVersion` | `2` (after the first `-`) |
| `$cleanVersion` `$underscoreVersion` `$dashVersion` `$dotVersion` | `25602` `2_56_0_2` `2-56-0-2` `2.56.0.2` |
| `$match<Name>` | each named group from `checkver` |

Other `$names` (like `$dir` in hooks) are left alone.

**Hashes.** By default each new URL is downloaded and hashed (sha256). To read hashes from a
checksum file instead, add a `hash` rule. It applies to every architecture unless one has its own:

```json
"hash": {"url": "$baseurl/SHASUMS256.txt"}
```

In a `hash` rule, `$url`, `$baseurl` (the URL without its file name) and `$basename` are also
available. The file is searched for a `<hash>  <basename>` line, or a single hash if that's all it
holds. Add `regex` (first group, or a `hash` group) or `jsonpath` for other layouts. sha1, sha256
and sha512 are recognised by length.

## Running it locally

```bash
cd path/to/drawer-repo
~/Developer/spork/tools/checkver               # list outdated packages
~/Developer/spork/tools/checkver -u jq         # update jq's manifest
~/Developer/spork/tools/checkver -v 1.8.1 jq   # set a specific version (re-hashes)
~/Developer/spork/tools/checkver -u -f         # rebuild every manifest at its current version
```

`checkver -u -f` should leave the files unchanged. It's a quick way to check that a new
`autoupdate` rule reproduces the hand-written URLs and hashes. Set `GITHUB_TOKEN` to avoid
GitHub's API rate limit. It needs Python 3 and nothing else.

`drawer-autoupdate` is what the workflow runs: `checkver -u`, then a test install and a commit for each
updated manifest. `AUTOUPDATE_DRY_RUN=1` runs it without pushing.

## The GitHub Actions workflow

[`.github/workflows/autoupdate.yml`](../.github/workflows/autoupdate.yml) is a reusable workflow.
Copy [`examples/drawer-autoupdate.yml`](../examples/drawer-autoupdate.yml) into a drawer as
`.github/workflows/autoupdate.yml`. It runs every 6 hours and can also be started by hand from
the Actions tab, for some packages only.

| Input | Default | |
|---|---|---|
| `packages` | all | Packages to check, separated by spaces. |
| `mode` | `push` | `push` commits `<pkg>: Update to version <ver>` to the branch. `pr` opens one pull request per package, on an `autoupdate/<pkg>` branch that later runs update. |
| `test` | `true` | Install each updated manifest with spork (macOS runner, native CPU only) and skip any that fail. `false` runs on Linux without testing. |
| `spork-ref` | `main` | Version of these tools to use. |

Notes:

- For `mode: pr`, turn on **Settings → Actions → General → Allow GitHub Actions to create and
  approve pull requests** in the drawer repo.
- Pushes and pull requests made with the default `GITHUB_TOKEN` don't start other workflows. If
  the drawer has its own CI, pass a personal access token or app token as the `token` secret.
- A package that fails (no match, download error, failed install) doesn't block the others. The
  run is marked failed, and the job summary lists what happened to each package.
