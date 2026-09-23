"""Disable the generated k8s client's client-side field validation.

Test fixtures build partial model objects (only the fields a given test
cares about); the generated models otherwise reject `None` for fields the
real API always populates, which has nothing to do with what these unit
tests are checking.

This must be a per-test autouse fixture, not one-time module-level code:
a live integration test calling collectors.k8s_client._load_config()
triggers kubernetes.config.load_kube_config(), which silently replaces
the client's global default Configuration -- undoing a one-time override
for every test that runs afterward in the same pytest process.
"""

import pytest
from kubernetes.client import Configuration


@pytest.fixture(autouse=True)
def _disable_k8s_client_side_validation():
    configuration = Configuration()
    configuration.client_side_validation = False
    Configuration.set_default(configuration)
