# SEO & SEM

## Built into the site
- **Server-rendered HTML** (no client-side rendering), so every page is crawlable and fast.
- `/sitemap.xml` generated live: every listing, category, job, event, podcast, product, public teacher profile and page. `/robots.txt` blocks dashboards, admin, checkout and registration steps.
- **Unique titles, meta descriptions and canonical URLs** on every template; Open Graph and Twitter cards.
- **Structured data (schema.org JSON-LD):** `Organization` (site-wide), `School` / `EducationalOrganization` / `Person` + `AggregateRating` on listings, `JobPosting` on jobs (eligible for Google for Jobs), `Event` on events, `Product` + `Offer` on marketplace items, `FAQPage` on the FAQ.
- **Clean, keyword-bearing URLs:** `/l/greenwood-valley-school-bengaluru`, `/c/preschool?city=Bengaluru`, `/jobs/tgt-mathematics-cbse-...`.
- Location-aware landing pages: every category × city filter is a crawlable URL (`/c/school-registration?city=Mysuru`).
- Accessible markup (labels, alt text, skip link, keyboard navigation) and mobile-first layout.
- Analytics and ad tags load only after cookie consent (DPDP).

## Launch checklist
1. Google Search Console → verify the domain (DNS TXT at GoDaddy, or set `GOOGLE_SITE_VERIFICATION`) → submit the sitemap. Do the same in Bing Webmaster Tools.
2. **Google Business Profile** for The School Expert (Bengaluru address); encourage listed schools to link to their School Expert page from their own Business Profiles.
3. Redirect old URLs: `registration.schoolexpert.in/forms/<slug>` → `/register/<slug>` (the slugs are identical, so one nginx rule handles it).
4. Ask verified schools to share their page link with parents (the "Copy link for parents" button) — natural backlinks.
5. Publish regularly: podcast episodes, newsletter issues, events and resources all generate new indexed pages.

## Keyword map (start here)
| Intent | Target pages | Example keywords |
|---|---|---|
| School search (high volume, local) | `/c/school-registration?city=X`, `/c/preschool?city=X`, listings | "CBSE schools in Bengaluru", "best preschool in Jayanagar", "inclusive school Chennai", "special school Mysuru", "IB school fees Bengaluru" |
| Admissions help | `/ask/schools`, `/personal-assistance` | "school admission 2027-28 Bengaluru", "school admission help", "TC collection service" |
| Teacher jobs | `/jobs`, job pages | "teacher jobs Bengaluru", "TGT maths vacancy CBSE", "special educator jobs" |
| Teacher CV | `/teachers/cv`, `/teachers` | "teacher resume format India", "CV for teacher job" |
| Experts | `/ask` | "child psychologist for students Bengaluru", "career counselling after 10th", "school fee EMI" |
| Homeschooling | `/homeschoolers-hub` | "homeschooling in India", "NIOS homeschooling", "homeschool meetup Bengaluru" |
| Kids reading | `/bookclub`, `/newsworms` | "kids newspaper India", "storytelling sessions for kids online", "book club for children" |
| B2B (vendors) | `/for-partners`, `/directory/vendors` | "school ERP vendors India", "school uniform suppliers Bengaluru", "school bus service providers" |

## SEM (Google Ads) — suggested structure
Set `GOOGLE_ADS_ID` and import GA4 conversions (`sign_up`, `purchase`, `generate_lead`).

| Campaign | Ad groups | Landing page | Conversion | Notes |
|---|---|---|---|---|
| Parents — Admissions (Search, city-targeted) | school search by board & city; preschool; admission help | `/ask/schools?city=…` | Pack purchase | Peak Oct–Feb. Use location extensions. |
| Parents — Personal Assistance | "admission form collection", "TC collection" | `/personal-assistance` | PA payment | Restrict to serviced cities. |
| Schools — Get listed (Search + LinkedIn) | "school marketing", "admission leads for schools" | `/for-schools` | Plan purchase | Target principals and owners; exclude job seekers. |
| Education partners (Search + LinkedIn) | ERP, publishers, uniforms, transport | `/for-partners`, `/founding-partners` | Registration submitted | B2B: optimise for qualified leads. |
| Teachers (Search + Meta) | teacher jobs by city / subject | `/jobs` | Sign-up | Low CPC, builds supply for schools. |
| Remarketing (Display/YouTube) | visitors who did not buy | home / category | Purchase | **Exclude** any audience relating to children; adult audiences only (DPDP s.9). |

Budget split to start: 40% parents (admission season), 25% schools, 20% partners, 15% teachers. Review search-term reports weekly and add negative keywords ("government job", "free", "salary" for school campaigns).

## Measuring
GA4 Explorations: funnel *category page → listing → pack purchase → unlock → enquiry*; *for-schools → registration started → submitted → plan paid*. The admin dashboard shows revenue by stream for cross-checking ad ROI.


## Audience acquisition built into the platform (v2)
- **Landing pages per audience and city** (indexable, schema.org markup): `/list-your-school[/<city>]`, `/become-a-vendor[/<category>]`, `/schools/<city>[?board=]`, `/teacher-jobs/<city>`, `/for-teachers`, `/school-match`, `/pricing`, `/guides/<slug>`.
- **Sitemap index** (`/sitemap.xml`) split into files of 20,000 URLs — scales with listings.
- **Attribution:** first-touch UTM / gclid / fbclid / referrer + landing page kept in a signed cookie (no personal data, no server session per visitor) and copied to the user, organisation and every order. Reports in Admin → Growth & SEO Desk.
- **Conversions:** `sign_up`, `generate_lead` (AI Match), `purchase` (value in INR) sent to GA4 and Google Ads (set `GOOGLE_ADS_LABEL_SIGNUP`, `GOOGLE_ADS_LABEL_PURCHASE`) **only after analytics-cookie consent**.
- **UTM builder** with suggested campaigns per audience in the Growth desk. Advertising is never targeted at children.
- **Legacy URLs:** 301 redirect map + pages at old paths (Site Integration Desk).
