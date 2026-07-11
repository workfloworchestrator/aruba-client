# Releasing aruba-client to PyPI

Releases follow the same flow as
[orchestrator-core](https://github.com/workfloworchestrator/orchestrator-core):
creating a GitHub release triggers `.github/workflows/publish-package.yml`,
which builds the package with `uv build` and publishes it to PyPI using
[trusted publishing](https://docs.pypi.org/trusted-publishers/) (OIDC, so no API
tokens or secrets are needed).

## One-time setup (GitHub / PyPI GUI)

1. **PyPI: add a trusted publisher.** On
   <https://pypi.org/manage/account/publishing/> add a *pending publisher*
   (or, once the project exists, under the project's *Publishing* settings):
   - PyPI project name: `aruba-client`
   - Owner: `workfloworchestrator`
   - Repository: `aruba-client`
   - Workflow name: `publish-package.yml`
   - Environment name: `pypi`
2. **GitHub: create the environment.** In the repo, go to
   *Settings → Environments → New environment* and create one named `pypi`.
   Optionally add required reviewers so a publish needs approval.

## Cutting a release

1. Bump `version` in `pyproject.toml` and merge to `main`.
2. On GitHub, go to *Releases → Draft a new release*.
3. Create a new tag matching the version (e.g. `0.2.0`), add release notes,
   and publish the release.
4. The *Upload Python Package* workflow builds and uploads the sdist and
   wheel to PyPI.

For pre-releases, use a [PEP 440](https://peps.python.org/pep-0440/)
pre-release version such as `0.2.0rc1`.
