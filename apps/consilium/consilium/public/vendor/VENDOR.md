# Vendored front-end libraries

These files are committed deliberately. The target environment has **no internet
access**, so nothing may be fetched from a CDN at build or run time. There is no
npm or yarn step in this project — these are the published distribution files,
copied in once and version-pinned here.

| Library | Version | Source |
|---|---|---|
| Bootstrap | 5.3.3 | npm registry, `bootstrap-5.3.3.tgz`, `dist/` |
| jQuery | 3.7.1 | npm registry, `jquery-3.7.1.tgz`, `dist/` |
| Bootstrap Icons | 1.11.3 | npm registry, `bootstrap-icons-1.11.3.tgz`, `font/` |

## Upgrading

1. Download the published tarball for the new version.
2. Replace the files below, keeping the same paths.
3. Update the version in this table and in `SHA256SUMS`.
4. Re-run `SHA256SUMS` verification and the front-end tests.

Do not add a package manager to the build to do this.
