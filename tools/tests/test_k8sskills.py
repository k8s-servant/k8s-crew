import os

import pytest

from tools.k8sskills import load_checker, read_ref

network = pytest.mark.skipif(os.environ.get("K8S_CREW_OFFLINE") == "1", reason="K8S_CREW_OFFLINE=1")


def test_ref_read_from_versions_env():
    assert read_ref() == "v0.10.0"


@network
def test_checker_accepts_read_only():
    assert load_checker().check_command("kubectl get pods -A") == []


@network
def test_checker_rejects_write():
    assert load_checker().check_command("kubectl delete pod my-app -n my-namespace") != []


@network
def test_checker_flags_secret():
    assert load_checker().secret_problems("kubectl get secret -n my-namespace") != []


@network
def test_commands_module_exposes_extract_blocks():
    assert hasattr(load_checker().commands_module, "extract_blocks")


@network
def test_own_tools_package_not_clobbered():
    import sys

    load_checker()
    import tools.k8sskills

    assert tools.k8sskills.__file__.startswith(os.getcwd())
    assert not any(m.startswith("tools.skillcheck") for m in sys.modules)
