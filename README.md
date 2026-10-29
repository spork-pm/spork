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

This copies spork to `~/.spork`, adds the official `main` and `apps` drawers (see
[Drawers](#drawers)), and adds this line to `~/.zshrc` (or `~/.bash_profile`):

```bash
eval "$(~/.spork/bin/spork shellenv)"
```

Pass `--no-modify-path` to skip editing your shell file. Set `SPORK_HOME` or `SPORK_APPDIR`
to use different folders. If your network blocks GitHub, set up [mirrors](#mirrors-and-proxies)
for downloads (or point `SPORK_MIRRORS_FILE` at a shared rules file). Mirrors don't apply to git,
so the installer's drawers must be reachable by git or through git's own `insteadOf` config.

## Usage

```bash
spork search json          # find packages
spork install jq rectangle # install a CLI tool and a GUI app
spork list                 # what's installed
spork update               # refresh drawers, show what's outdated
spork update --all         # update everything
spork uninstall rectangle
spork uninstall --purge mytool  # also delete the tool's saved data (see "persist" below)
spork hold jq              # pin a version (spork unhold jq to undo)
spork cleanup              # delete cached downloads (spork cleanup jq for just one package)
spork doctor               # check PATH, folders, drawers
```

Run `spork help` for the full list (`info`, `cat`, `home`, `prefix`, `which`, `cache`, `hash`,
`mirror`, …).
`-f`/`--force` reinstalls, or lets spork replace an app or command it doesn't own.

## Layout

```
~/.spork/
  bin/                    # add to PATH: symlinks to commands
  apps/<pkg>/<version>/   # unpacked package files
  apps/<pkg>/current      # symlink to the installed version
  drawers/<name>/         # manifest collections
  persist/<pkg>/          # user data kept across updates and uninstalls
  cache/                  # downloads, reused on reinstall
~/Applications/           # .app bundles
```

Command links point through `current`, so they keep working across updates. Old versions are
deleted after an update.

## Drawers

A drawer is a folder or git repo of JSON manifests, in a `drawer/` subfolder or at the top level.
It's what Scoop calls a bucket. The installer adds the two official drawers:

| Drawer | Contents |
|---|---|
| [`main`](https://github.com/spork-pm/main) | Command-line tools, linked into `~/.spork/bin` |
| [`apps`](https://github.com/spork-pm/apps) | GUI apps, installed into `~/Applications` |

To add them again later, run `spork drawer add main` or `spork drawer add apps` (no URL needed).
When several drawers have a package with the same name, `main` wins, then the others in
alphabetical order. Use `drawer/package` to pick one.

```bash
spork drawer add work https://github.com/your-org/spork-drawer  # git, or a tarball download if git is missing
spork drawer add local ~/my-manifests                           # a local folder (linked, edits show up immediately)
spork drawer list
spork install work/sometool                                     # pick a drawer explicitly
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
    "persist": ["data", ["conf/settings.ini", "settings.ini"]],
    "env_add_path": ["tools", "$persist_dir/data/bin"],
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
| `persist` | Files or folders inside the package that hold user data: `"path"`, or a list of `"path"` / `["path", "name"]`. See [Persisted data](#persisted-data). |
| `env_add_path` | Extra folders to put on `PATH`, for tools that install their own commands. See [Extra PATH folders](#extra-path-folders). |
| hooks | Shell run from the package folder, with `$dir`, `$version`, `$appdir`, `$bindir`, `$arch` and `$persist_dir` (the package's [persisted data](#persisted-data) folder) set. |

Supported downloads: `.zip`, `.tar`/`.tar.gz`/`.tgz`/`.tar.xz`/`.tar.bz2`/`.tar.zst`, `.dmg`
(mounted read-only, contents copied), `.pkg` (payload unpacked; its installer scripts are **not**
run), `.gz`, and plain binaries.

Look at the [main](https://github.com/spork-pm/main/tree/main/drawer) and
[apps](https://github.com/spork-pm/apps/tree/main/drawer) drawers for working examples.

## Persisted data

Each update installs a package into a fresh folder and deletes the old one. A tool that keeps
user files next to its binary (config, a database, plugins) would lose them, so list those paths
under `persist`:

```json
"persist": ["data", ["conf/settings.ini", "settings.ini"]]
```

Each path is moved to `~/.spork/persist/<pkg>/` (under `name` when given) and replaced by a link
in the package folder:

- **First install:** the file or folder that ships in the package becomes the user's copy. If
  nothing ships at that path, an empty folder is created. To start with an empty file instead,
  create it in `pre_install`.
- **Updates and reinstalls:** the user's copy replaces whatever the new version ships at that
  path. Defaults added in a new version don't appear inside a persisted folder.
- **Uninstall:** the data is kept, so reinstalling picks it up again. `spork uninstall --purge <pkg>`
  deletes it, including data left behind by an earlier uninstall.

Paths are relative to the package folder (after `extract_dir`). Paths inside an `.app` bundle
aren't allowed: apps keep their data in `~/Library`, and changing a bundle breaks its signature.

## Extra PATH folders

Most packages only need `bin`, which links commands into `~/.spork/bin`. Some tools create
commands of their own later, like `npm install -g` with Node.js. List the folders those commands
land in under `env_add_path`:

```json
"env_add_path": ["tools", "$persist_dir/global/bin"]
```

- Plain entries are relative to the package folder. spork adds them through `current`, so they
  keep working after updates. `"."` means the package folder itself.
- Entries starting with `$persist_dir` point into the package's [persisted data](#persisted-data)
  folder, `~/.spork/persist/<pkg>/`. The folder doesn't need to exist yet.
- `spork shellenv` puts these folders on `PATH` after `~/.spork/bin`. The shell picks them up when
  it starts, so after installing such a package, open a new terminal or run
  `eval "$(spork shellenv)"`. Uninstalling the package removes them the same way.

## Mirrors and proxies

When a network blocks the original download sites, spork can rewrite URLs to go through an
internal mirror or proxy (Artifactory, Nexus, a caching proxy, …). Each rule swaps a URL prefix:

```bash
spork mirror add https://github.com/ https://artifactory.example.com/artifactory/github/
spork mirror add https://codeload.github.com/ https://artifactory.example.com/artifactory/codeload/
spork mirror list
spork mirror test https://github.com/jqlang/jq/releases/download/jq-1.8.2/jq-macos-arm64
spork mirror rm https://codeload.github.com/
```

With that rule, `https://github.com/jqlang/jq/releases/…` is downloaded from
`https://artifactory.example.com/artifactory/github/jqlang/jq/releases/…`.

- Rules apply to package downloads, manifest URLs, `spork hash` and drawers downloaded without
  git. git drawers clone straight from their URL; use git's own `url.<base>.insteadOf` config
  if you need to redirect them.
- When several rules match, the longest prefix wins.
- Checksums still come from the manifest, so a mirror can't hand you a different file.
- Rules live in `~/.spork/mirrors`, one `<from> <to>` per line (`#` starts a comment). Set
  `SPORK_MIRRORS_FILE` to use a shared file instead, e.g. one your team maintains.
- Drawers downloaded without git come from `codeload.github.com`, so mirror that host too.
- If the replacement must contain the whole original URL, put it in the rule, e.g.
  `spork mirror add https://github.com/ https://proxy.example.com/fetch/https://github.com/`.

### Mirrors that need a login

If your login keychain has an internet password for a mirror's host, spork sends it as HTTP basic
auth on every download that goes through that mirror. Save one with:

```bash
security add-internet-password -s artifactory.example.com -a your.name -w
```

(`-w` last makes `security` ask for the password, so it stays out of your shell history.)

- `spork mirror list` and `spork doctor` show which mirrors have a login. Neither reads the
  password, so they never trigger a keychain prompt.
- The first real download may show a keychain prompt asking to let `security` read the password.
  Choose **Always Allow** to skip it next time.
- Only rewritten URLs get the login: it is never sent to the original site, and curl drops it if
  the mirror redirects to another host.
- The password never appears on a command line (curl reads it from stdin).
- Set `SPORK_KEYCHAIN=0` to turn this off.

## Limits

- `.pkg` installers that need their scripts or must install to `/Library` won't work. Pick a
  `.zip`/`.dmg` build when one exists.
- Apps that insist on living in `/Applications`, or that install privileged helpers or kernel/system
  extensions, need an admin.
- Version checks compare strings: any change in a drawer's `version` counts as an update.
- Downloads use `curl`, so HTTP proxies work through `https_proxy` / `HTTPS_PROXY`. Proxies that
  ask for Kerberos get your ticket automatically, for curl and git alike (run `kinit` first). For
  mirrors that need different URLs, see [Mirrors and proxies](#mirrors-and-proxies).

## Development

`tests/test_spork.py` runs spork end to end in a throwaway home folder, with packages served
from a local web server, so it never touches your own `~/.spork` or `~/Applications`:

```bash
python3 -m unittest discover -s tests -v
```

Python is only needed for the tests; spork itself stays a plain Bash script.
