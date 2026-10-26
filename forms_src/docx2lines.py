import sys, re, zipfile
from lxml import etree
W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
W14='{http://schemas.microsoft.com/office/word/2010/wordml}'
def para_text(p):
    out=[]
    for el in p.iter():
        if el.tag==W+'t': out.append(el.text or '')
        elif el.tag==W+'tab': out.append(' ')
        elif el.tag==W+'br': out.append('\n')
        elif el.tag==W14+'checkbox': out.append('☐ ')
        elif el.tag==W+'sym':
            ch=el.get(W+'char','')
            if ch.upper() in ('F0A8','F06F','F071','F0FE','F0A3','F06E'): out.append('☐ ')
    t=''.join(out)
    # numbering -> keep list marker hint
    numpr=p.find('.//'+W+'numPr')
    pre=''
    if numpr is not None:
        nid=numpr.find(W+'numId'); lvl=numpr.find(W+'ilvl')
        nid=nid.get(W+'val') if nid is not None else '0'; lvl=lvl.get(W+'val') if lvl is not None else '0'
        fmt=NUMFMT.get((nid,lvl),'bullet')
        pre='# ' if fmt not in ('bullet','none') else '- '
    return [pre+x.strip() for x in t.split('\n') if x.strip()]
def walk(el,lines):
    for ch in el:
        if ch.tag==W+'p': lines+=para_text(ch)
        elif ch.tag==W+'tbl':
            for tr in ch.iter(W+'tr'):
                for tc in tr.findall(W+'tc'):
                    for p in tc.iter(W+'p'):
                        lines+=para_text(p)
        elif ch.tag==W+'sdt':
            c=ch.find(W+'sdtContent')
            if c is not None: walk(c,lines)
z=zipfile.ZipFile(sys.argv[1])
NUMFMT={}
try:
    nx=etree.fromstring(z.read('word/numbering.xml'))
    absf={}
    for a in nx.findall(W+'abstractNum'):
        aid=a.get(W+'abstractNumId')
        for l in a.findall(W+'lvl'):
            f=l.find(W+'numFmt'); absf[(aid,l.get(W+'ilvl'))]=f.get(W+'val') if f is not None else 'bullet'
    for n in nx.findall(W+'num'):
        aid=n.find(W+'abstractNumId').get(W+'val')
        for (a,l),f in absf.items():
            if a==aid: NUMFMT[(n.get(W+'numId'),l)]=f
except KeyError: pass
root=etree.fromstring(z.read('word/document.xml'))
lines=[]; walk(root.find(W+'body'),lines)
# dedupe consecutive duplicate lines (nested tables)
prev=None
for l in lines:
    if l!=prev: print(l)
    prev=l
