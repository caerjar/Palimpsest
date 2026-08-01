# Packaging & releasing Palimpsest

Three ways users install Palimpsest. All build from the same `pyproject.toml`.

| Channel   | Who it's for                     | What they run                                   |
|-----------|----------------------------------|-------------------------------------------------|
| pipx      | Anyone with Python 3.11+         | `pipx install git+https://github.com/caerjar/Palimpsest` |
| Homebrew  | Mac users (handles Python for them) | `brew tap caerjar/tap && brew install palimpsest` |
| .dmg      | Non-technical Mac users          | double-click the app                            |
| Docker    | Anyone with Docker (bundles pandoc + XeLaTeX) | `just serve`                       |

The core is pure Python stdlib — **no runtime dependencies**. External tools
(`git`, `pandoc`, XeLaTeX, PyMuPDF) are optional and detected at runtime; the app
degrades gracefully when they're absent.

---

## 1. pipx (works today, no release infra)

```
pipx install git+https://github.com/caerjar/Palimpsest
pal new "My Novel"
pal --book my-novel serve
```

`pipx install .` (from a clone) or `pip install .` into a venv both work too. For
the richer PDF *import* path, add the extra: `pip install '.[pdf]'` (pulls PyMuPDF).

## 2. Homebrew tap

A tap is a separate GitHub repo named `homebrew-tap`. The formula lives at
`homebrew/palimpsest.rb` in this repo as the source of truth; copy it into the
tap on each release.

**One-time setup**

1. Create `github.com/caerjar/homebrew-tap`.
2. Add `Formula/palimpsest.rb` (copy of `homebrew/palimpsest.rb`).

**Each release**

1. Tag and push a release in this repo: `git tag v0.1.0 && git push --tags`.
2. Compute the tarball hash:
   ```
   curl -fL https://github.com/caerjar/Palimpsest/archive/refs/tags/v0.1.0.tar.gz | shasum -a 256
   ```
3. In the tap's `Formula/palimpsest.rb`, bump `url` to the new tag and paste the
   `sha256`. Commit.
4. Users: `brew update && brew upgrade palimpsest`.

Test the formula locally before publishing:
```
brew install --build-from-source ./homebrew/palimpsest.rb
brew test palimpsest
brew audit --strict --new palimpsest
```

## 3. macOS .dmg (double-clickable app)

```
./packaging/build_dmg.sh
```

Produces `dist/Palimpsest.app` and `dist/Palimpsest-<version>.dmg`.

- **pandoc is bundled** (~150 MB) → Word/HTML/Markdown export works out of the box.
- **XeLaTeX is not bundled** → PDF export prompts `brew install --cask basictex`.
- The app has no CLI: on launch it seeds a starter book (first run), builds it, and
  serves the workbench at <http://127.0.0.1:8137>, opening the browser. The
  workbench is `~/Documents/Palimpsest` (writable; never inside the .app).

> **Before a public release, test the .dmg on a clean Mac** — ideally one without
> Homebrew or a system Python 3.12 — to confirm the bundle is fully self-contained.
> py2app embeds `Python.framework` in the app, but the machine you *build* on having
> its own Python can mask a missing-runtime problem. Verify: create a book, build,
> serve, and export a `.docx` (exercises the bundled pandoc) on the clean machine.

### Unsigned — first-launch step for users

The `.dmg` is unsigned (free). Tell users:

> Drag **Palimpsest** to Applications. The first time, **right-click the app →
> Open** and confirm. macOS asks once; after that it opens normally.

### Optional: signing + notarization (no warning)

Needs an Apple Developer account ($99/yr). After `build_dmg.sh`:

```
codesign --deep --force --options runtime \
  --sign "Developer ID Application: Your Name (TEAMID)" dist/Palimpsest.app
# rebuild the dmg from the signed .app, then:
xcrun notarytool submit dist/Palimpsest-<version>.dmg \
  --apple-id you@example.com --team-id TEAMID --password <app-specific-pw> --wait
xcrun stapler staple dist/Palimpsest-<version>.dmg
```

## Version bumps

Bump `version` in **`pyproject.toml`** — that is the source of truth, and
`palimpsest.__version__` reads it (installed metadata, or the file itself from a
checkout), so `pal --version` follows automatically.

Also bump `VERSION` in **`packaging/setup_app.py`** and the `url` tag in the tap
formula. Those two are separate copies because py2app and Homebrew each need the
number before the package exists.

(This list used to say "that's the whole surface" while `palimpsest/__init__.py`
carried a fourth copy. It drifted on the very next release — hence reading it
rather than restating it.)
