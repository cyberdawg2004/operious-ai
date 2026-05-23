# Operious Marketing 2 Frontend

Next.js App Router frontend for the Operious enterprise marketing site.

## Development

```bash
npm run dev
```

Open `http://localhost:3000`.

## Environment

`NEXT_PUBLIC_COMMAND_CENTER_URL` controls the header Sign In destination.

`CONTACT_ENDPOINT_URL` configures the server-side destination for enterprise access requests. The `/api/contact` route forwards validated JSON submissions to this endpoint when it is set.

`CONTACT_ENDPOINT_TOKEN` is optional. When present, `/api/contact` sends it as a bearer token to the configured contact endpoint.

Without `CONTACT_ENDPOINT_URL`, `/api/contact` still validates the form and returns an accepted response for local development and preview testing.

## Verification

```bash
npm run lint
npm run build
```
