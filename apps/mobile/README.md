# apps/mobile (placeholder)

Reserved for the future Expo / React Native mobile app.

## Why this folder exists now

Pantry capture is a phone-camera-first feature. The web app supports it via the
browser camera API, but the real UX wants a native app. By reserving this folder
in the monorepo now, we avoid restructuring later and we set up `pnpm-workspace`
to include it from day one.

## When to populate

Once Sprint 1 (pantry capture on web) is shipping reliably, scaffold this with:

```bash
cd apps
pnpm create expo-app mobile -t expo-template-blank-typescript
```

Then:

- Add `@frugal-living/shared-types` as a workspace dependency.
- Reuse the API client pattern from `apps/web/src/lib/api.ts`.
- Use `expo-camera` for the pantry capture flow.
- Use `expo-secure-store` for auth tokens once auth is real.

## What goes here vs. apps/web

- **Native-only capabilities** — true wake-word voice, background sync,
  notifications for daily briefings, barcode scanner.
- **Shared UI patterns** — adapt from web; use React Native equivalents.
- **Shared business types** — import from `packages/shared-types`.
