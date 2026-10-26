"""Sponsored placements (revenue stream: featured / sponsored placement).

Ads are always labelled "Sponsored", never mixed into organic ranking or AI School Match scoring."""
from ..db import db

PLACEMENTS = ('home', 'directory', 'school_match', 'resources', 'jobs', 'newsletter', 'marketplace', 'community_teachers')

def pick(placement, city=None, n=1):
    rows = db.all("""SELECT id, title, image_url, link_url, org_id FROM ad_placements
                     WHERE placement = %s AND active AND status = 'approved' AND current_date BETWEEN starts_on AND ends_on
                       AND (city IS NULL OR city = '' OR %s::text IS NULL OR lower(city) = lower(%s::text))
                     ORDER BY random() LIMIT %s""", placement, city, city, n)
    if rows: db.run('UPDATE ad_placements SET impressions = impressions + 1 WHERE id = ANY(%s)', [r['id'] for r in rows])
    return rows
