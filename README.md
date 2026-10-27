# spork

A [Scoop](https://scoop.sh)-style package manager for macOS that works without admin rights.

- GUI apps (`.app`) are installed into `~/Applications`.
- Command-line tools are linked into `~/.spork/bin`, which you add to `$PATH`.
- Nothing is written outside your home folder, and `sudo` is never used.
- It's a single Bash script that only uses tools macOS ships with (`curl`, `plutil`, `shasum`,
  `ditto`, `tar`, `hdiutil`/`diskutil`, `pkgutil`). git is optional.

## Install

```bash
./install.sh
```

This copies spork to `~/.spork`, sets up the bundled `main` bucket, and adds this line to
`~/.zshrc` (or `~/.bash_profile`):

```bash
eval "$(~/.spork/bin/spork shellenv)"
```

Pass `--no-modify-path` to skip editing your shell file. Set `SPORK_HOME` or `SPORK_APPDIR`
to use different folders.

## Usage

```bash
spork search json          # find packages
spork install jq rectangle # install a CLI tool and a GUI app
spork list                 # what's installed
spork update               # refresh buckets, show what's outdated
spork update --all         # update everything
spork uninstall rectangle
spork hold jq              # pin a version (spork unhold jq to undo)
spork doctor               # check PATH, folders, buckets
```

Run `spork help` for the full list (`info`, `cat`, `home`, `prefix`, `which`, `cache`, `hash`, …).
`-f`/`--force` reinstalls, or lets spork replace an app or command it doesn't own.

## Layout

```
~/.spork/
  bin/                    # add to PATH: symlinks to commands
  apps/<pkg>/<version>/   # unpacked package files
  apps/<pkg>/current      # symlink to the installed version
  buckets/<name>/         # manifest collections
  cache/                  # downloads, reused on reinstall
~/Applications/           # .app bundles
```

Command links point through `current`, so they keep working across updates. Old versions are
deleted after an update.

## Buckets

A bucket is a folder or git repo of JSON manifests, in a `bucket/` subfolder or at the top level
(same as Scoop).

```bash
spork bucket add work https://github.com/your-org/spork-bucket  # git, or a tarball download if git is missing
spork bucket add local ~/my-manifests                           # a local folder (linked, edits show up immediately)
spork bucket list
spork install work/sometool                                     # pick a bucket explicitly
```

You can also install straight from a manifest: `spork install ./foo.json` or
`spork install https://example.com/foo.json`.

## Manifest format

```json
{
    "version": "1.2.3",
    "description": "One line shown in search",
    "homepage": "https://example.com",
    "license": "MIT",
    "url": "https://example.com/foo-1.2.3.zip",
    "hash": "sha256:…",
    "extract_dir": "foo-1.2.3",
    "bin": ["foo", ["bin/foo-cli", "foo2"]],
    "app": "Foo.app",
    "depends": ["bar"],
    "pre_install": "…shell…",
    "post_install": ["…shell…", "…"],
    "pre_uninstall": "…shell…",
    "notes": "Shown after install"
}
```

| Field | Meaning |
|---|---|
| `url` | A download URL, or a list of them. Add `#/name` to rename a download, e.g. `…/jq-macos-arm64#/jq`. |
| `hash` | One per URL. `sha256:` (default), `sha512:` or `sha1:`. Get one with `spork hash <url>`. |
| `architecture` | `{"arm64": {…}, "x86_64": {…}}`. Overrides `url`, `hash`, `extract_dir`, `bin`, `app`, `notes` per CPU. On Apple silicon, an Intel-only package falls back to Rosetta with a warning. |
| `extract_dir` | Folder inside the archive to use as the package root. |
| `bin` | Commands to link into `~/.spork/bin`: `"path"`, or a list of `"path"` / `["path", "alias"]`. A path can point inside an installed app, e.g. `["Foo.app/Contents/Resources/foo", "foo"]`. |
| `app` | `.app` bundle(s) to move into `~/Applications`. |
| `depends` | Packages to install first. |
| hooks | Shell run from the package folder, with `$dir`, `$version`, `$appdir`, `$bindir`, `$arch` set. |

Supported downloads: `.zip`, `.tar`/`.tar.gz`/`.tgz`/`.tar.xz`/`.tar.bz2`/`.tar.zst`, `.dmg`
(mounted read-only, contents copied), `.pkg` (payload unpacked; its installer scripts are **not**
run), `.gz`, and plain binaries.

Look at [bucket/](bucket/) for working examples (ripgrep, fd, jq, Rectangle).

## Limits

- `.pkg` installers that need their scripts or must install to `/Library` won't work. Pick a
  `.zip`/`.dmg` build when one exists.
- Apps that insist on living in `/Applications`, or that install privileged helpers or kernel/system
  extensions, need an admin.
- Version checks compare strings: any change in a bucket's `version` counts as an update.
- Downloads use `curl`, so corporate proxies work through `https_proxy` / `HTTPS_PROXY`.
