# v0.0.1 signed metadata

This directory contains the public Ed25519 key, exact canonical manifests and
detached signatures for the two Actryn v0.0.1 software-preview candidates. The
large `payload.tar` files are deliberately kept out of Git; their SHA-256 values
are bound by the manifests and by
[`signed-distribution-verification.json`](../signed-distribution-verification.json).

`SHA256SUMS` covers every file here that existed at signing time. Verify either
signature from the repository root with:

```sh
openssl pkeyutl -verify -pubin \
  -inkey docs/development/v0.0.1-signed-metadata/release-public.pem \
  -rawin \
  -in docs/development/v0.0.1-signed-metadata/server/manifest.json \
  -sigfile docs/development/v0.0.1-signed-metadata/server/signature.ed25519
```

Replace `server` with `robot` for the Robot candidate. The trusted SPKI SHA-256
is `3bc25f592073d520c88635fca7fe1838d156428c314b34db4ebd655a18ce6735`.
The signatures authenticate the manifests and provenance; they do not establish
physical qualification, live motion or an independent installation.
