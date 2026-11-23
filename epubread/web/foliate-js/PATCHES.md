# Vendored foliate-js

- Upstream: https://github.com/johnfactotum/foliate-js (MIT, see `LICENSE`)
- Pinned commit: `78914ae` (2026-05-01)
- Removed from the vendored copy: `.git`, `tests/`, `rollup*`, `eslint.config.js`, `package*.json`, and upstream's demo `reader.html` / `reader.js`.

## Local patches

Each patch lives in `patches/` and is already applied to the files here. Re-apply them after any upgrade.

| Patch | File | Why |
|---|---|---|
| `0001-epub-empty-metadata.patch` | `epub.js` | EPUBs with an empty `<metadata>` element (seen in calibre exports) crash on `Object.groupBy(undefined)`. Guard with `?? []`. To be sent upstream. |

## Upgrading

1. Clone upstream at the new commit and copy it over this directory, using the same exclusions.
2. `git apply patches/*.patch` (drop any patch upstream has merged).
3. Update the pinned commit above and run `pytest tests/integration`.
