"""Ajoute au catalogue les nouvelles pages Weebly portant un repère valide.
Ne supprime ni ne modifie les recettes existantes.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

BASE = 'https://lesrecettesdeleonard.weebly.com/'
DOMAIN = 'lesrecettesdeleonard.weebly.com'
CATALOGUE = Path('recettes.json')
REPORT = Path('rapport_mise_a_jour.json')
CATEGORIES = {
    ('entrees', 'soupes-et-veloutes'): 'Soupes et Veloutés',
    ('entrees', 'entrees-froides'): 'Entrées froides',
    ('entrees', 'entrees-chaudes'): 'Entrées chaudes',
}
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; CatalogueRecettesLeonard/1.0)'}


def fetch(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read().decode('utf-8', errors='replace')


class RecipePage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.markers = []
        self.title = ''
        self.in_title = False
        self.images = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if 'data-recette-categorie' in attributes:
            self.markers.append(attributes)
        if tag == 'title':
            self.in_title = True
        if tag == 'meta' and (attributes.get('property') in ('og:image', 'twitter:image') or attributes.get('name') == 'twitter:image'):
            image = attributes.get('content', '')
            if image:
                self.images.append(image)

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def valid_url(url):
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == 'https' and parsed.netloc == DOMAIN and parsed.path.endswith('.html')


def main():
    existing = json.loads(CATALOGUE.read_text(encoding='utf-8'))
    if not isinstance(existing, list) or not existing:
        raise ValueError('Catalogue absent, vide ou invalide : aucune modification')
    known = {r['url'].rstrip('/') for r in existing}
    root = ET.fromstring(fetch(BASE + 'sitemap.xml'))
    urls = list(dict.fromkeys(n.text.strip() for n in root.iter() if n.tag.rsplit('}', 1)[-1] == 'loc' and n.text))
    if len(urls) < len(existing):
        raise ValueError('Sitemap incomplet : aucune modification')
    candidates = [u for u in urls if valid_url(u) and u.rstrip('/') not in known]
    additions = []
    errors = []
    ignored = 0
    for index, url in enumerate(candidates, 1):
        try:
            page = RecipePage()
            page.feed(fetch(url))
            matches = [CATEGORIES.get((m.get('data-recette-categorie'), m.get('data-recette-sous-categorie'))) for m in page.markers]
            matches = [c for c in matches if c]
            if not matches:
                ignored += 1
                continue
            if len(set(matches)) != 1:
                errors.append({'url': url, 'error': 'Repères contradictoires'})
                continue
            title = page.title.strip()
            image = urllib.parse.urljoin(url, page.images[0]) if page.images else ''
            if not title or not image or urllib.parse.urlparse(image).scheme != 'https':
                errors.append({'url': url, 'error': 'Titre ou image manquant'})
                continue
            additions.append({'title': title, 'category': matches[0], 'url': url, 'image': image})
            print(f'NOUVELLE RECETTE : {title} / {matches[0]} / {url}', flush=True)
        except Exception as exc:
            errors.append({'url': url, 'error': str(exc)})
        if index % 100 == 0:
            print(f'Pages examinées : {index}/{len(candidates)}', flush=True)

    report = {'pages_sitemap': len(urls), 'recettes_existantes': len(existing), 'pages_examinees': len(candidates), 'ignorees_sans_repere': ignored, 'nouvelles_recettes': additions, 'erreurs': errors}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Bilan : {len(additions)} nouvelle(s) recette(s), {len(errors)} erreur(s).", flush=True)
    if errors:
        raise RuntimeError('Certaines pages ont échoué : aucune mise à jour. Voir le rapport.')
    if len(additions) > 10:
        raise RuntimeError('Plus de 10 ajouts détectés : validation manuelle requise, aucune mise à jour.')
    if additions:
        temp = CATALOGUE.with_suffix('.json.tmp')
        temp.write_text(json.dumps(existing + additions, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(temp, CATALOGUE)
        print(f'Catalogue mis à jour : {len(existing)} -> {len(existing) + len(additions)} recettes.', flush=True)
    else:
        print('Aucune nouvelle recette : catalogue inchangé.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'ERREUR : {exc}', file=sys.stderr, flush=True)
        sys.exit(1)
