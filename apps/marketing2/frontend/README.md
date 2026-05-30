# Operious Marketing 2 Frontend

Next.js App Router frontend for the Operious enterprise marketing site.

## Development

```bash
npm run dev
```

Open `http://localhost:3000`.

## Environment

`NEXT_PUBLIC_COMMAND_CENTER_URL` is reserved for command center links. The public header now routes buyers to the architecture review flow.

`CONTACT_ENDPOINT_URL` configures the server-side destination for architecture review and security packet requests. The `/api/contact` route forwards validated JSON submissions to this endpoint.

`CONTACT_ENDPOINT_TOKEN` is optional. When present, `/api/contact` sends it as a bearer token to the configured contact endpoint.

Without `CONTACT_ENDPOINT_URL`, `/api/contact` returns HTTP 503. The form must never confirm a request that was not delivered.

## Verification

```bash
npm run lint
npm run build
```
