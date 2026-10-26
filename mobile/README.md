# The School Expert™ — mobile app (Android & iOS)

The app is a [Capacitor](https://capacitorjs.com) shell around the live website, so every feature, plan and dashboard
ships to the app the moment it ships to the web — one codebase, no duplicate releases. The website is already an
installable PWA (manifest, offline page, bottom navigation), and the REST API at `/api/v1` (bearer tokens) is ready
for fully native screens later (see `docs/API.md`).

## Build
Requirements: Node 18+, Android Studio (Android), Xcode 15+ on macOS (iOS).

```bash
cd mobile
npm install
npx cap add android      # and/or: npx cap add ios
npx cap sync
npx cap open android     # build & run from Android Studio; release: Build → Generate Signed Bundle
```

## Before publishing
1. Icons & splash: replace `resources/` (1024×1024 icon, 2732×2732 splash) and run `npx @capacitor/assets generate`.
2. Deep links: host `/.well-known/assetlinks.json` (Android) and `apple-app-site-association` (iOS) on schoolexpert.in.
3. Push notifications: add Firebase `google-services.json` (Android) / APNs key (iOS).
4. Store listings: Google Play Console & App Store Connect under Poornaphala Media and Infotech Services LLP.
   The app is for parents, schools, teachers and education partners (adults) — declare it is **not directed at children**.
5. Payments: plans and services are paid through Razorpay in the web view. Digital-goods rules of the app stores may
   require review — schools/vendor plans are B2B services; confirm with each store's current policy before launch.
