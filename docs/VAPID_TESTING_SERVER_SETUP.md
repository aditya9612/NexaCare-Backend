# NexaCare Browser Push Notifications — VAPID Setup Guide

## Purpose

This document explains how to generate and configure VAPID keys for the NexaCare Browser Push Notification backend on a Testing Server.

IMPORTANT:
- Generate separate VAPID keys for Local, Testing, and Production environments.
- Never commit or expose the VAPID private key.
- Never put the private key in frontend code.
- Do not paste private keys into GitHub, pull requests, chat, screenshots, or source code.
- `VAPID_CLAIM_EMAIL` is only a VAPID contact/subject value. It is not a secret and does not send email.

---

# 1. Required Environment Variables

The backend expects:

VAPID_PRIVATE_KEY=<REAL_GENERATED_PRIVATE_KEY>
VAPID_PUBLIC_KEY=<REAL_GENERATED_PUBLIC_KEY>
VAPID_CLAIM_EMAIL=mailto:test@example.com

For production, replace the temporary email with a real monitored company/team email.

Example:

VAPID_CLAIM_EMAIL=mailto:devops@nexacare.com

Do NOT put real private/public key values in this document.

---

# 2. Generate VAPID Keys — Windows Testing Server

Use this section if the Testing Server runs Windows.

## Step 1 — Open PowerShell or Command Prompt

Open a terminal on the Testing Server.

## Step 2 — Go to the backend project

Example:

cd C:\path\to\NexaCare-Backend

Replace the path with the actual deployment directory.

## Step 3 — Activate the virtual environment

If the project has a virtual environment named `venv`:

PowerShell:

.\venv\Scripts\Activate.ps1

Command Prompt:

venv\Scripts\activate

If the server uses another environment name/path, activate that environment instead.

## Step 4 — Verify pywebpush / py-vapid is installed

Run:

python -c "from py_vapid import Vapid; print('py-vapid import OK')"

Expected:

py-vapid import OK

If this fails, install project requirements first:

python -m pip install -r requirements.txt

Then repeat the import test.

## Step 5 — Generate a NEW Testing VAPID key pair

Run:

python -c "from py_vapid import Vapid; v=Vapid(); v.generate_keys(); print('PRIVATE=',v.private_key.hex()); print('PUBLIC=',v.public_key.public_bytes_raw().hex())"

The output will look like:

PRIVATE=<long-secret-value>
PUBLIC=<long-public-value>

IMPORTANT:
- Treat PRIVATE as a secret.
- PUBLIC can be shared with the frontend team.
- Do not commit either value to Git.

## Step 6 — Configure Testing Server Environment

Set these values in the Testing Server's environment/.env/secret configuration:

VAPID_PRIVATE_KEY=<PRIVATE_VALUE_GENERATED_ABOVE>
VAPID_PUBLIC_KEY=<PUBLIC_VALUE_GENERATED_ABOVE>
VAPID_CLAIM_EMAIL=mailto:test@example.com

Do not commit the Testing Server `.env` file.

## Step 7 — Restart the Backend

Restart the FastAPI/Uvicorn service so the new environment variables are loaded.

Then verify application startup.

---

# 3. Generate VAPID Keys — Linux / AWS Testing Server

Use this section if the Testing Server runs Linux, EC2, or another SSH-accessible Linux server.

## Step 1 — SSH into the Testing Server

Example:

ssh <user>@<server>

Use the actual server access method provided by DevOps.

## Step 2 — Go to the backend project

Example:

cd /path/to/NexaCare-Backend

Replace the path with the actual deployment directory.

## Step 3 — Activate the virtual environment

Example:

source venv/bin/activate

If the deployment uses another virtual environment path, activate that environment instead.

## Step 4 — Verify py-vapid

Run:

python -c "from py_vapid import Vapid; print('py-vapid import OK')"

Expected:

py-vapid import OK

If this fails:

python -m pip install -r requirements.txt

Then repeat the import test.

## Step 5 — Generate a NEW Testing VAPID key pair

Run:

python -c "from py_vapid import Vapid; v=Vapid(); v.generate_keys(); print('PRIVATE=',v.private_key.hex()); print('PUBLIC=',v.public_key.public_bytes_raw().hex())"

Output:

PRIVATE=<long-secret-value>
PUBLIC=<long-public-value>

IMPORTANT:
- Never put PRIVATE into Git.
- Never put PRIVATE into frontend code.
- Do not send PRIVATE through unsecured chat.
- PUBLIC is safe to provide to the frontend team.

## Step 6 — Configure the Testing Server Environment

Set:

VAPID_PRIVATE_KEY=<PRIVATE_VALUE_GENERATED_ABOVE>
VAPID_PUBLIC_KEY=<PUBLIC_VALUE_GENERATED_ABOVE>
VAPID_CLAIM_EMAIL=mailto:test@example.com

Depending on the deployment architecture, environment variables may be configured using:
- a server `.env` file,
- systemd service environment,
- Docker environment/secrets,
- AWS deployment/secret-management configuration,
- or another DevOps-managed secret store.

Do NOT assume the deployment uses `.env`. Follow the existing deployment configuration.

## Step 7 — Restart the Backend

Restart the deployed FastAPI/Celery services using the project's existing deployment process.

Both the API process and Celery worker must receive the VAPID environment variables because Browser Push delivery happens in the Celery worker.

---

# 4. Frontend Handoff

The frontend team needs ONLY the Testing `VAPID_PUBLIC_KEY`.

They must NOT receive:

VAPID_PRIVATE_KEY

The frontend needs to:
1. Register a Service Worker.
2. Request browser notification permission.
3. Create a PushSubscription using the Testing VAPID public key.
4. Send endpoint + p256dh + auth to:

POST /api/v1/notifications/push/subscribe

For unsubscribe:

DELETE /api/v1/notifications/push/unsubscribe

The frontend must use the PUBLIC key belonging to the same environment as the backend.

Example:

Testing Backend VAPID_PUBLIC_KEY
        |
        +----> Testing Frontend PushSubscription

Do not use Local public key with Testing backend or Production public key with Testing backend.

---

# 5. Verification Checklist

After configuration, verify:

[ ] `VAPID_PRIVATE_KEY` is configured on the Testing backend.
[ ] `VAPID_PUBLIC_KEY` is configured on the Testing backend.
[ ] `VAPID_CLAIM_EMAIL` is configured.
[ ] `py-vapid` import works.
[ ] `pywebpush` is installed.
[ ] `pip check` passes.
[ ] FastAPI starts successfully.
[ ] Celery worker starts successfully.
[ ] Testing backend can read the VAPID configuration.
[ ] Private key is NOT exposed in logs/API responses.
[ ] Private key is NOT committed to Git.
[ ] Frontend receives ONLY the public key.
[ ] Frontend Service Worker is registered.
[ ] Browser PushSubscription is created.
[ ] Subscribe API stores the subscription.
[ ] A test notification reaches the browser.

---

# 6. Environment Separation

Recommended:

LOCAL:
    Local Private Key
    Local Public Key

TESTING:
    Testing Private Key
    Testing Public Key

PRODUCTION:
    Production Private Key
    Production Public Key

Never reuse the Production private key in Local or Testing.

---

# 7. Important Security Rule

This file is documentation only.

NEVER add actual VAPID values to this file.

Bad:

VAPID_PRIVATE_KEY=actual-secret-key

Good:

VAPID_PRIVATE_KEY=<PRIVATE_VALUE_GENERATED_ABOVE>

The real values must exist only in the appropriate environment/secret configuration.

---

# 8. Temporary Testing Email

If the company does not currently have a dedicated email address for VAPID contact information, Testing/Local can temporarily use:

VAPID_CLAIM_EMAIL=mailto:test@example.com

This value is not a VAPID secret.

For Production, use a real monitored company/team email such as:

VAPID_CLAIM_EMAIL=mailto:devops@nexacare.com

provided that the address actually exists.

---

# 9. Do Not Generate Keys in Git

The command below generates the keys:

python -c "from py_vapid import Vapid; v=Vapid(); v.generate_keys(); print('PRIVATE=',v.private_key.hex()); print('PUBLIC=',v.public_key.public_bytes_raw().hex())"

Run it directly on the target environment when possible.

The generated private key must be copied only into the target environment's secure configuration.

---

# 10. Final Rule

Code/config.py contains only empty defaults:

VAPID_PRIVATE_KEY: str = ""
VAPID_PUBLIC_KEY: str = ""
VAPID_CLAIM_EMAIL: str = "mailto:admin@nexacare.com"

Actual environment-specific values are supplied outside Git.

This allows the same codebase to be safely deployed to Local, Testing, and Production with different VAPID key pairs.
