# WebHealth CDK application

Run dependency setup and npm commands from the repository root. This directory contains the CDK entry point, infrastructure, Lambda handlers and tests.

- [Project README](../README.md)
- [Operational runbook](../RUNBOOK.md)
- [API contract](../docs/API.md)
- [Testing map](../docs/TESTING.md)
- [Browser dashboard](../docs/DASHBOARD.md)

From this directory, with the virtual environment active:

~~~bash
ruff check .
pytest -m "not integration"
~~~

Three integration tests require actual AWS resources and --run-live. The repository-root runbook explains how the scripts obtain live resource names from CloudFormation outputs.
