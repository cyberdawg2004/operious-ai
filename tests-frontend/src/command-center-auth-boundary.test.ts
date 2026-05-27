import { test } from 'node:test';
import { match } from 'node:assert';
import { join } from 'node:path';
import { ROOT, readText } from './util.js';

const COMMAND_CENTER_ROOT = join(ROOT, 'apps', 'command-center2', 'frontend');

test('command center proxy explicitly protects dashboard routes', () => {
  const text = readText(join(COMMAND_CENTER_ROOT, 'proxy.ts'));

  match(
    text,
    /auth0\.getSession\(request\)/,
    'proxy.ts must verify an Auth0 session before serving protected routes',
  );
  match(
    text,
    /pathname\.startsWith\("\/dashboard\/"\)/,
    'dashboard child routes must be treated as protected routes',
  );
  match(
    text,
    /NextResponse\.redirect\(signInUrl\)/,
    'unauthenticated protected requests must redirect to sign-in',
  );
});

test('command center logout returns outside the protected dashboard', () => {
  const text = readText(join(COMMAND_CENTER_ROOT, 'components', 'sidebar.tsx'));

  match(
    text,
    /new URL\("\/api\/auth\/logout", window\.location\.origin\)/,
    'logout must call the Auth0 logout route using the current app origin',
  );
  match(
    text,
    /logoutUrl\.searchParams\.set\("returnTo", window\.location\.origin\)/,
    'logout must return to the app origin so the protected root redirects to sign-in',
  );
});
