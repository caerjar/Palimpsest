# Homebrew formula for Palimpsest.
#
# This file belongs in a TAP repo, not the main code repo. A tap is just a GitHub
# repo whose name starts with `homebrew-`. To publish:
#
#   1. Create a repo:  github.com/<you>/homebrew-tap
#   2. Put this file at:  Formula/palimpsest.rb  in that repo.
#   3. Cut a release in the code repo (tag v0.1.1) so the `url` tarball exists.
#   4. Fill in `sha256` below:
#        curl -fL https://github.com/<you>/palimpsest/archive/refs/tags/v0.1.1.tar.gz | shasum -a 256
#   5. Commit. Users then run:
#        brew tap <you>/tap
#        brew install palimpsest
#
# (A copy lives here in the code repo as the source of truth; copy it into the tap
# on each release and bump `url` + `sha256`.)
class Palimpsest < Formula
  include Language::Python::Virtualenv

  desc "Deterministic, offline manuscript workbench: Markdown sections to editorial HTML dossier"
  homepage "https://github.com/caerjar/Palimpsest"
  url "https://github.com/caerjar/Palimpsest/archive/refs/tags/v0.1.1.tar.gz"
  sha256 "ac04013458b7ba9e4d8277ca63127a9410f53dc06a2982f26ce455082adf48f9"
  license "MIT"

  # Palimpsest itself is pure stdlib. Needs 3.11+ for tomllib.
  depends_on "python@3.12"

  # Optional, for nicer export/import: `brew install pandoc` (Word/HTML) and
  # `brew install --cask basictex` (PDF). The app degrades gracefully without them.

  def install
    virtualenv_install_with_resources

    # PyMuPDF powers "import a PDF". Without it here the feature is dead on arrival
    # for `brew install` users: the app runs from this virtualenv, so a
    # `pip install pymupdf` anywhere else never reaches it.
    #
    # Installed with pip directly, NOT venv.pip_install: that helper passes
    # --no-binary=:all: (Homebrew builds Python packages from source), which sends
    # pip off to compile MuPDF — it bootstraps its own CMake and takes tens of
    # minutes when it works at all. PyMuPDF publishes binary wheels built against
    # MuPDF; --only-binary takes one, which is also why it can't be a `resource`
    # block. Failure is non-fatal: every other feature works without PDF import,
    # and the app then prints the exact command to add it.
    begin
      system libexec/"bin/python", "-m", "pip", "install", "--quiet",
             "--only-binary", ":all:", "pymupdf"
    rescue => e
      opoo "PyMuPDF could not be installed (#{e.message}); PDF import will be unavailable"
    end
  end

  test do
    # `pal` with no args prints its usage banner and exits 0.
    assert_match "manuscript workbench", shell_output("#{bin}/pal")
  end
end
