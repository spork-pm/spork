# Hosts spork needs to reach

Use this page to open a firewall or proxy for spork, or to decide which
[mirror rules](../README.md#mirrors-and-proxies) to set up. It covers spork itself and every
package in the official `main`, `apps` and `fonts` drawers.

The lists were built from the drawers on 2026-10-31, with each arm64 download followed through
its redirects. Each package's x86_64 build downloads from the same host. Drawers change often, so
when you're unsure, check a package's `url` with `spork cat <pkg>`.

## spork itself and the drawers

| Host | Used for |
|---|---|
| `github.com` | Installing and updating spork (`~/.spork/self`), and cloning or pulling the official drawers with git |
| `codeload.github.com` | spork and the drawers when git is missing: they're downloaded as tarballs instead |

Drawers you add yourself need access to wherever they're hosted.

## Hosts by package

Downloads are fetched with `curl -L`, so a firewall must allow the redirect host as well as the
host in the manifest.

| Host in the manifest | Redirects to | Packages |
|---|---|---|
| `github.com` | `release-assets.githubusercontent.com` | **main:** apfel, azure-cli, azure-kubelogin, colima, fastfetch, fd, gh, git, jq, lima, python, ripgrep, starship<br>**apps:** draw.io, headlamp, monitor-control, obsidian, ollama, openlogi, rectangle, stats<br>**fonts:** cascadiacode-nf, firacode-nf, hack-nf, jetbrainsmono-nf, meslo-nf |
| `nodejs.org` | | **main:** nodejs, nodejs-lts |
| `download.docker.com` | | **main:** docker |
| `builds.dotnet.microsoft.com` | | **main:** dotnet10-sdk |
| `get.helm.sh` | | **main:** helm |
| `dl.k8s.io` | | **main:** kubectl |
| `releases.hashicorp.com` | | **main:** terraform |
| `download.jetbrains.com` | `download-cdn.jetbrains.com` | **apps:** intellij, rider |
| `update.code.visualstudio.com` | `vscode.download.prss.microsoft.com` | **apps:** vscode |
| `download-installer.cdn.mozilla.net` | | **apps:** firefox |
| `www.coconut-flavour.com` | | **apps:** coconut-battery |

`colima` depends on `lima`, and both download from GitHub. No other package has dependencies,
and no install hook downloads anything.

### Setting up mirrors

Mirror rules match the URL in the manifest, before any redirect. A rule for
`https://github.com/` covers every GitHub package above: the mirror follows the redirect to
`release-assets.githubusercontent.com` itself, so your machine never contacts that host. Add one
rule per host in the first column that your network blocks, plus `https://codeload.github.com/`
if you install without git.
