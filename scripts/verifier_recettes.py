"""Audit en lecture seule des recettes marquées dans le sitemap Weebly."""
import json
import re
import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

BASE = 'https://lesrecettesdeleonard.weebly.com/'
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; CatalogueRecettesAudit/1.0)'}


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as response:
        return response.read().decode('utf-8', errors='replace')


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.marker = []
        self.title = ''
        self.in_title = False
        self.images = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if 'data-recette-categorie' in a:
            self.marker.append(a)
        if tag == 'title':
            self.in_title = True
        if tag == 'meta' and a.get('property') in ('og:image', 'twitter:image'):
            self.images.append(a.get('content', ''))

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def main():
    catalogue = json.loads(Path('recettes.json').read_text(encoding='utf-8'))
    known = {r.get('url', '').rstrip('/') for r in catalogue}
    xml = ET.fromstring(get(urllib.parse.urljoin(BASE, 'sitemap.xml')))
    urls = [node.text.strip() for node in xml.iter() if node.tag.rsplit('}', 1)[-1] == 'loc' and node.text]
    urls = list(dict.fromkeys(u for u in urls if urllib.parse.urlparse(u).netloc == 'lesrecettesdeleonard.weebly.com'))
    print(f'Pages du sitemap : {len(urls)} | Recettes déjà dans le catalogue : {len(known)}')
    # Test prudent : seules les pages inconnues du catalogue sont examinées.
    # Les pages existantes non marquées ne sont jamais supprimées.
    candidates = [u for u in urls if u.rstrip('/') not in known]
    print(f'Pages à examiner (hors catalogue actuel) : {len(candidates)}')
    results = []
    errors = []
    for i, url in enumerate(candidates, 1):
        try:
            page = Page()
            page.feed(get(url))
            for marker in page.marker:
                category = marker.get('data-recette-categorie', '')
                subcategory = marker.get('data-recette-sous-categorie', '')
                if category == 'entrees' and subcategory in ('soupes-et-veloutes', 'entrees-froides', 'entrees-chaudes'):
                    results.append({'url': url, 'titre_page': page.title.strip(), 'categorie': category, 'sous_categorie': subcategory, 'image_candidate': page.images[0] if page.images else ''})
                    print(f'[RECETTE MARQUÉE] {url} — {subcategory}')
                    break
        except Exception as e:
            errors.append({'url': url, 'erreur': str(e)})
        if i % 100 == 0:
            print(f'Pages examinées : {i}/{len(candidates)}', flush=True)
    report = {'pages_sitemap': len(urls), 'recettes_catalogue': len(known), 'pages_examinees': len(candidates), 'recettes_marquees_a_examiner': results, 'erreurs': errors}
    Path('rapport_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Test terminé : {len(results)} pages marquées, {len(errors)} erreurs. Aucun fichier du catalogue modifié.')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'Échec du test : {e}', file=sys.stderr)
        sys.exit(1)
