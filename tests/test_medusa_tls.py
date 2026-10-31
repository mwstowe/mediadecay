"""Regression tests for the Medusa TLS verify_ssl default (P1 #7)."""
from mediadecay.clients import medusa


def test_verify_ssl_defaults_to_true(db):
    # db fixture config has no verify_ssl key for medusa.
    _url, _headers, verify = medusa._base()
    assert verify is True, "TLS verification must default to ON"


def test_verify_ssl_opt_out(db):
    from mediadecay.config import get_config
    get_config()["medusa"]["verify_ssl"] = False
    medusa._insecure_warned = False
    _url, _headers, verify = medusa._base()
    assert verify is False, "explicit verify_ssl: false must be honored"


def test_get_helper_verifies_by_default():
    import inspect
    sig = inspect.signature(medusa._get)
    assert sig.parameters["verify"].default is True
