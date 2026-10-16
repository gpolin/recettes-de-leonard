"""Ajoute les nouvelles recettes Weebly et corrige la miniature de Carambar.
Les autres recettes existantes ne sont jamais modifiées ni supprimées.
"""
import html
import json
import os
import re
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
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; CatalogueRecettesLeonard/1.1)'}
CARAMBAR_URL = BASE + 'velouteacute-de-carambar.html'
CARAMBAR_IMAGE = BASE + 'uploads/1/3/1/2/131229293/background-images/221226262.png'


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
        self.meta_images = []
        self.background_images = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if 'data-recette-categorie' in attributes:
            self.markers.append(attributes)
        if tag == 'title':
            self.in_title = True
        if tag == 'meta' and (attributes.get('property') in ('og:image', 'twitter:image') or attributes.get('name') == 'twitter:image'):
            image = attributes.get('content', '')
            if image:
                self.meta_images.append(image)
        # Certaines pages Weebly mettent l'image du bandeau dans un attribut.
        for key in ('style', 'data-background', 'data-image', 'data-bg'):
            value = attributes.get(key, '') or ''
            self.background_images.extend(extract_background_images(value))

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def extract_background_images(source):
    """Extrait les URLs des images de fond (et non les icônes de contenu)."""
    source = html.unescape(source).replace('\\/', '/')
    # La présence du dossier background-images est le repère utilisé par Weebly.
    pattern = r'''(?:(?:https?:)?//[^\s"'<>\\()]+|/[^\s"'<>\\()]+)?/uploads/[^\s"'<>\\()]*?/background-images/[^\s"'<>\\()]+\.(?:png|jpe?g|webp)'''
    return re.findall(pattern, source, flags=re.IGNORECASE)


def choose_image(url, source, page):
    # Pour cette recette, l'image correcte a été vérifiée manuellement.
    if url.rstrip('/') == CARAMBAR_URL:
        return CARAMBAR_IMAGE
    candidates = extract_background_images(source)
    candidates.extend(page.background_images)
    for candidate in candidates:
        absolute = urllib.parse.urljoin(url, candidate)
        parsed = urllib.parse.urlparse(absolute)
        if parsed.scheme == 'https' and parsed.netloc == DOMAIN:
            return absolute
    # L'image de métadonnées est seulement un dernier recours.
    for candidate in page.meta_images:
        absolute = urllib.parse.urljoin(url, candidate)
        if urllib.parse.urlparse(absolute).scheme == 'https':
            return absolute
    return ''


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
            source = fetch(url)
            page = RecipePage()
            page.feed(source)
            matches = [CATEGORIES.get((m.get('data-recette-categorie'), m.get('data-recette-sous-categorie'))) for m in page.markers]
            matches = [c for c in matches if c]
            if not matches:
                ignored += 1
                continue
            if len(set(matches)) != 1:
                errors.append({'url': url, 'error': 'Repères contradictoires'})
                continue
            title = page.title.strip()
            image = choose_image(url, source, page)
            if not title or not image:
                errors.append({'url': url, 'error': 'Titre ou image manquant'})
                continue
            additions.append({'title': title, 'category': matches[0], 'url': url, 'image': image})
            print(f'NOUVELLE RECETTE : {title} / {matches[0]} / {url}', flush=True)
        except Exception as exc:
            errors.append({'url': url, 'error': str(exc)})
        if index % 100 == 0:
            print(f'Pages examinées : {index}/{len(candidates)}', flush=True)

    # Correction limitée à la miniature de Carambar, sans toucher aux autres champs.
    corrections = []
    updated = [dict(recipe) for recipe in existing]
    for recipe in updated:
        if recipe['url'].rstrip('/') == CARAMBAR_URL and recipe.get('image') != CARAMBAR_IMAGE:
            recipe['image'] = CARAMBAR_IMAGE
            corrections.append({'url': CARAMBAR_URL, 'image': CARAMBAR_IMAGE})

    report = {
        'pages_sitemap': len(urls),
        'recettes_existantes': len(existing),
        'pages_examinees': len(candidates),
        'ignorees_sans_repere': ignored,
        'nouvelles_recettes': additions,
        'photos_corrigees': corrections,
        'erreurs': errors,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Bilan : {len(additions)} ajout(s), {len(corrections)} photo(s) corrigée(s), {len(errors)} erreur(s).", flush=True)
    if errors:
        raise RuntimeError('Certaines pages ont échoué : aucune mise à jour. Voir le rapport.')
    if len(additions) > 10:
        raise RuntimeError('Plus de 10 ajouts détectés : validation manuelle requise, aucune mise à jour.')
    if additions or corrections:
        temp = CATALOGUE.with_suffix('.json.tmp')
        temp.write_text(json.dumps(updated + additions, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(temp, CATALOGUE)
        print(f'Catalogue mis à jour : {len(existing)} -> {len(existing) + len(additions)} recettes.', flush=True)
    else:
        print('Aucun changement : catalogue inchangé.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'ERREUR : {exc}', file=sys.stderr, flush=True)
        sys.exit(1)
