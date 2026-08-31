# Security policy

GeoSkills processes local scientific data. A security report must never include unpublished measurements, sample identifiers, credentials, private paths, or other sensitive project material.

## Supported versions

Security fixes are prepared for the latest published release and the current release candidate. Older versions may be asked to upgrade before a fix is backported.

## Reporting a vulnerability

Use GitHub's private **Report a vulnerability** form in the repository Security tab when it is available. Include the affected GeoSkills version, operating system, a minimal reproduction using synthetic data, and the expected impact.

Do not publish exploit details or private research data in a public issue. If the private form is unavailable, open a public issue containing only a request for a private security contact; do not include the vulnerability details.

## Security boundaries

- GeoSkills is designed for local-only processing and does not require a network service for plotting.
- `shareable` output omits plotted-source CSV files and suppresses sample identifiers in supported figures.
- `local-reproducible` output may contain sensitive plotted data and must not be uploaded without a separate data-release review.
- Scientific correctness, figure interpretation, and repository security settings still require human review.

Dependencies are checked in continuous integration with `pip-audit`. GitHub vulnerability alerts, private vulnerability reporting, and branch protection are repository settings and should also be enabled by an administrator.
