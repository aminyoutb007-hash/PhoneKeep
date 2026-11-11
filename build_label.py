"""Label of a test build, e.g. "5.0-dev+B3". Empty for a release.

GitHub Actions writes this file before packaging a pull-request build; the committed value stays empty.
Shown next to the version in the About box and in `phonekeep-cli --version`, so the build being
tested is always identifiable. See docs/spec/12-engineering.md, "Build and release".
"""
BUILD_LABEL = ""
