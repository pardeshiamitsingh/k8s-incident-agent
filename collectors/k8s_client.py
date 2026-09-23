"""K8s API client construction (spec 001).

Picks in-cluster ServiceAccount config when running inside a pod, else
falls back to the local kubeconfig context -- never requires the caller to
know which environment it's running in.
"""

import logging

from kubernetes import client, config

logger = logging.getLogger(__name__)


def _load_config() -> None:
    try:
        config.load_incluster_config()
        logger.debug("loaded in-cluster ServiceAccount config")
    except config.ConfigException:
        config.load_kube_config()
        logger.debug("loaded local kubeconfig")


def build_api_client() -> client.CoreV1Api:
    _load_config()
    return client.CoreV1Api()


def build_apps_api_client() -> client.AppsV1Api:
    _load_config()
    return client.AppsV1Api()
