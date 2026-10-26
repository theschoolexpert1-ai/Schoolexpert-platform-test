# Plans, access & revenue streams

Payment decides what every school and vendor can see and do. All rules live in **plan grants** (Admin → Subscriptions & Billing Desk → Plans & pricing), read by `tse/lib/entitlements.py`. Change a price or a feature there — no code change needed.

## School plans (annual, + 18% GST)

| | School - Basic ₹4,999 | School - Plus ₹11,999 *(most popular)* | School - Pro ₹24,999 |
|---|---|---|---|
| Verified listing + School Dashboard | ✓ | ✓ | ✓ |
| Detailed profile (fees, facilities, contacts) for entitled parents | — | ✓ | ✓ |
| Verified leads + instant alerts | — | ✓ | ✓ |
| Job posts | 2 | Unlimited | Unlimited + 3 featured/month |
| Photos & videos | 5 | 30 | Unlimited |
| See detailed profiles of other schools & partners | — | ✓ | ✓ |
| Reply to verified reviews | — | ✓ | ✓ |
| Full profile used in AI School Match | — | ✓ | ✓ |
| Analytics | Basic | 30-day | Advanced |
| Featured placement (top of city & category), Pro badge | — | — | ✓ |
| Teacher directory (recruitment) | — | add-on ₹4,999 | ✓ |
| Campuses | 1 | 1 | Unlimited |
| Sponsored banner days, newsletter & podcast feature, account manager | — | — | 30 days, ✓ |
| Event pass discount | — | 10% | 25% |

## Vendor plans (all education partners, providers & professionals)

| | Vendor - Basic ₹5,999 | Vendor - Plus ₹14,999 | Vendor - Pro ₹29,999 |
|---|---|---|---|
| Verified listing + Vendor Dashboard | ✓ | ✓ | ✓ |
| Detailed profile & enquiries from schools/parents | — | ✓ | ✓ |
| Marketplace products / commission | 5 / 15% | 50 / 10% | Unlimited / 7% |
| Featured placement, webinar partner slot, podcast & newsletter feature | — | — | ✓ |
| Sponsored banner days | — | — | 60 |

**Founding Partner** (one-time ₹35,000 schools / ₹25,000 vendors): Pro benefits, 3-year renewal waiver, lifetime badge.

## Upgrades
Basic → Plus → Pro, one step at a time, from **Dashboard → Plan & upgrade**. Price = new plan − credit for unused days of the current plan (`credit = amount paid × days left ÷ 365`). The new plan runs 12 months from the upgrade date; the old subscription is marked *upgraded*. Renewal reminders appear 30 days before expiry. Unpaid organisations can complete forms and save, but their listing is hidden and the dashboard shows only "Activate".

## Revenue streams → where they are in the product
| # | Stream (from your chart) | Built as |
|---|---|---|
| 1 | School subscription plans | School - Basic/Plus/Pro, renewals, upgrades with proration |
| 2 | Verified school leads | Parent unlock pack (₹499 / 10 schools) → verified enquiries routed only to Plus/Pro schools |
| 4 | Featured / sponsored placement | Pro featured ranking in directory; Sponsored Banner add-on (₹4,999 / 30 days) on directory, AI Match sidebar, jobs, resources — always labelled, never affects AI Match scores |
| 5 | Education partner memberships | Vendor - Basic/Plus/Pro |
| 6 | Founding partner programme | Founding Partner plans + waiver logic |
| 7 | Teacher memberships | Free teacher profile + Teacher Premium (₹499/yr) |
| 8 | Podcasts & webinars | Pro podcast/webinar features, sponsorships, listener questions |
| 10 | Workshops / events | Paid passes, member discounts by tier, sponsorships |
| 10 | TSE product marketplace | TSE products + vendor products; tier-based commission in the seller ledger |
| 11 | Events & sponsorships | Events & Sponsorship Desk |
| 12 | Recruitment marketplace | Job limits by tier, Featured Job (₹999), Recruitment Plus add-on, teacher directory for Pro |
| 14 | Affiliate / referral | Every account has a referral link (Dashboard → Refer & earn); 10–12% commission on paid orders, approved and paid in the Payouts Desk |
| 15 | TSE product/service subscriptions | NewsWorms, Bookclub, Ask The School Expert, Personal Assistance |
| 16 | Homeschoolers meetups | Paid meetup events in the Homeschoolers Hub |
