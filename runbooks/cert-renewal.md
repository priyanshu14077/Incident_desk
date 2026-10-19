# Runbook: renew an expired TLS certificate

Use when callers log TLS handshake failures such as `x509: certificate has expired`.

## 1. Confirm
- A certificate event shows the service's certificate reached its notAfter time.
- Callers fail the handshake; the service's own metrics may look healthy because requests never reach it.

## 2. Renew
- Issue a new certificate for the hostname from the internal CA.
- Store it in the secrets manager under the service's TLS entry.

## 3. Reload
- Reload or restart the service so it serves the new certificate.
- Check the served certificate's validity dates from a caller.

## 4. Verify
- Handshake errors stop and the caller's error rate returns to baseline.

## 5. Follow up
- Add an expiry alert at 30 and 7 days before notAfter.
