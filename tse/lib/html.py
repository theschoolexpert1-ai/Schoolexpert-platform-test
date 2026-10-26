"""Allow-list HTML sanitiser (no external dependency)."""
from html.parser import HTMLParser
from html import escape

ALLOWED = {'p', 'br', 'strong', 'b', 'em', 'i', 'u', 'ul', 'ol', 'li', 'h2', 'h3', 'h4', 'blockquote', 'a', 'table', 'thead', 'tbody',
           'tr', 'th', 'td', 'hr', 'code', 'pre', 'span', 'img', 'figure', 'figcaption', 'dl', 'dt', 'dd', 'sup', 'sub'}
ATTRS = {'a': {'href', 'title'}, 'img': {'src', 'alt', 'width', 'height'}, 'td': {'colspan'}, 'th': {'colspan'}}
VOID = {'br', 'hr', 'img'}

class _S(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.out = []; self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'iframe', 'object'): self.skip += 1; return
        if tag not in ALLOWED or self.skip: return
        keep = []
        for k, v in attrs:
            if k in ATTRS.get(tag, ()) and v is not None:
                if k in ('href', 'src') and not (v.startswith(('http://', 'https://', '/', 'mailto:', 'tel:', '#'))): continue
                keep.append(f'{k}="{escape(v)}"')
        if tag == 'a': keep.append('rel="noopener nofollow"')
        self.out.append(f"<{tag}{' ' + ' '.join(keep) if keep else ''}>")
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'iframe', 'object'): self.skip = max(0, self.skip - 1); return
        if tag in ALLOWED and tag not in VOID and not self.skip: self.out.append(f'</{tag}>')
    def handle_data(self, data):
        if not self.skip: self.out.append(escape(data))

def clean(html):
    s = _S(); s.feed(html or ''); s.close(); return ''.join(s.out)
