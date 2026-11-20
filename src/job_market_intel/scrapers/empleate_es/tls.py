"""TLS trust bundle for www.empleate.gob.es.

Measured on 2026-11-20: this host's TLS handshake sends **only its leaf
certificate** (``C=ES, O=Servicio Público de Empleo Estatal,
CN=*.empleate.gob.es``). The leaf is issued by ``Entrust OV TLS Issuing
RSA CA 2``, which is itself issued by ``Sectigo Public Server
Authentication Root R46`` -- a root that *is* present in certifi.
Because the intermediate is never sent, OpenSSL cannot build the chain
from certifi's roots alone and every request fails with::

    SSL: CERTIFICATE_VERIFY_FAILED ... unable to get local issuer certificate

Reproduced four ways before writing this module:

* ``requests`` with certifi -- fails on this machine;
* ``curl_cffi`` with ``impersonate="chrome"``/``"chrome124"``/
  ``"safari17_0"`` -- fails (all three);
* ``openssl s_client -showcerts`` -- reports exactly one certificate in
  the handshake and ``verify error:num=21:unable to verify the first
  certificate``;
* Windows' own Schannel store (and therefore ``curl.exe``) -- succeeds,
  but only because the OS had already cached the intermediate from the
  leaf's Authority Information Access URL.

The standard fix for an incomplete chain is applied here: ship the missing
intermediate and append it to a copy of the root bundle. The intermediate
was downloaded from the leaf's own AIA extension
(``http://crt.sectigo.com/EntrustOVTLSIssuingRSACA2.crt``) and verified
with ``openssl verify -CAfile <certifi> -untrusted <intermediate> <leaf>``
-> ``OK``. Certificate verification therefore stays **on**; nothing is
disabled and no ``verify=False`` appears anywhere.

The shipped file keeps the ``.crt`` name it was fetched under (``.pem`` is
gitignored repo-wide because that extension is reserved for private keys;
``.pem`` and ``.crt`` are the same PEM container here). It is a public CA
intermediate certificate, not a private key, so it is safe to commit, and
a test asserts it loads.

The intermediate is valid until 2027-12-10. If the host rotates to a
different issuer the run fails loudly with the same
``unable to get local issuer certificate`` error rather than silently
degrading, which is the correct failure mode: refresh the file from the
new leaf's AIA and update this module's docstring.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from requests import certs

#: The intermediate the server omits, shipped with the package.
INTERMEDIATE_PEM = Path(__file__).with_name("certs") / "entrust_ov_tls_issuing_rsa_ca_2.crt"


def build_ca_bundle() -> str:
    """Return a path to certifi's roots plus the missing intermediate.

    The bundle is rebuilt only when its contents change: the file name
    carries a short digest of the payload, so a certifi upgrade (or a
    different ``REQUESTS_CA_BUNDLE``) produces a new file instead of
    reusing a stale one. Writes are atomic via ``os.replace`` so two
    parallel sessions cannot observe a half-written bundle.
    """
    if not INTERMEDIATE_PEM.is_file():  # pragma: no cover - packaging guard
        raise FileNotFoundError(f"missing intermediate certificate bundle: {INTERMEDIATE_PEM}")

    roots = Path(certs.where()).read_bytes()
    intermediate = INTERMEDIATE_PEM.read_bytes()
    separator = b"" if roots.endswith(b"\n") else b"\n"
    payload = roots + separator + intermediate

    digest = hashlib.sha256(payload).hexdigest()[:16]
    target = Path(tempfile.gettempdir()) / f"jmi_empleate_es_ca_{digest}.pem"
    if not target.is_file() or target.read_bytes() != payload:
        staging = target.with_name(target.name + f".{os.getpid()}.tmp")
        staging.write_bytes(payload)
        os.replace(staging, target)
    return str(target)
