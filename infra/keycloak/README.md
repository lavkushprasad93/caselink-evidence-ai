# Keycloak realm for CaseLink

`copilot-realm.json` creates realm `copilot` with roles `admin`, `investigator`,
`supervisor`, and `auditor`; a public PKCE client `copilot-web`; and a confidential client
`copilot-api`. The web client's tokens carry `copilot-api` as their audience, which the API
validates.

The realm file contains no users or secrets. Create test users in the admin console.

## Import on startup

The Compose service starts Keycloak in development mode and imports this realm from
`infra/keycloak` on startup. Keycloak imports a realm only if it does not already exist.
To re-import after changing the realm file, remove the existing `copilot` realm in the
admin console before restarting Keycloak.

## Development users

In the admin console at <http://localhost:8080>, select realm `copilot`, then add users
under **Users**. Set passwords under **Credentials**, then assign a realm role under
**Role mapping**. Create at least one `investigator`, one `supervisor`, and one `auditor`.

## Check a token

Use an access token issued for a user, then call:

```sh
curl -H "Authorization: Bearer <token>" http://localhost:8000/me
```

The token's `iss` claim must exactly match `KEYCLOAK_ISSUER` in `.env`, which defaults to
`http://localhost:8080/realms/copilot`. Use the same hostname (`localhost` or `127.0.0.1`)
for the issuer and the JWKS endpoint.
