"""Disable the generated k8s client's client-side field validation.

Test fixtures build partial model objects (only the fields a given test
cares about); the generated models otherwise reject `None` for fields the
real API always populates, which has nothing to do with what these unit
tests are checking.
"""

from kubernetes.client import Configuration

_configuration = Configuration()
_configuration.client_side_validation = False
Configuration.set_default(_configuration)
