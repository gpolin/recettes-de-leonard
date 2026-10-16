"""Synchronise les titres et miniatures Weebly, et ajoute les nouvelles recettes.

Les catégories, URL et recettes absentes du sitemap ne sont jamais modifiées
ni supprimées. Une unique synchronisation initiale est autorisée seulement
si ses 211 différences correspondent exactement au rapport vérifié.
Ensuite, au plus 10 recettes existantes peuvent être modifiées par exécution.
"""
import html
import hashlib
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
MAX_ADDITIONS = 10
MAX_EXISTING_CHANGES = 10
# Autorisation exceptionnelle pour la première synchronisation, validée à partir
# du rapport du 16 octobre 2026 (210 titres et une photo).
# Si une seule différence apparaît, cette autorisation ne s'applique pas.
INITIAL_APPROVED_FINGERPRINT = '6e8153a9835f003ba81f2435160f09fe56238fb5bd6eeb39f03620462449ecac'
INITIAL_APPROVED_COUNT = 211

CATEGORIES = {
    ('entrees', 'soupes-et-veloutes'): 'Soupes et Veloutés',
    ('entrees', 'entrees-froides'): 'Entrées froides',
    ('entrees', 'entrees-chaudes'): 'Entrées chaudes',
    ('plats', 'autres-viandes'): 'Autres viandes',
    ('plats', 'boeuf'): 'Bœuf',
    ('plats', 'canard'): 'Canard',
    ('plats', 'poissons-et-fruits-de-mer'): 'Poissons et fruits de mer',
    ('plats', 'porc'): 'Porc',
    ('plats', 'veau'): 'Veau',
    ('plats', 'volaille'): 'Volaille',
    ('plats', 'vegetarien'): 'Végétarien',
    ('desserts', 'autres-desserts'): 'Autres desserts',
    ('desserts', 'biscuits-et-petites-douceurs'): 'Biscuits et petites douceurs',
    ('desserts', 'cremes-et-mousses'): 'Crèmes et mousses',
    ('desserts', 'desserts-aux-fruits'): 'Desserts aux fruits',
    ('desserts', 'entremets-et-desserts-individuels'): 'Entremets et desserts individuels',
    ('desserts', 'gateaux-et-patisseries'): 'Gâteaux et pâtisseries',
    ('desserts', 'panna-cotta'): 'Panna cotta',
    ('desserts', 'tartes-et-tartelettes'): 'Tartes et tartelettes',
    ('buffet', 'cocktails'): 'Cocktails',
    ('buffet', 'sale'): 'Salé',
    ('buffet', 'sucre'): 'Sucré',
}
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; CatalogueRecettesLeonard/1.2)'}
CARAMBAR_URL = BASE + 'velouteacute-de-carambar.html'
CARAMBAR_IMAGE = BASE + 'uploads/1/3/1/2/131229293/background-images/221226262.png'


def fetch(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read().decode('utf-8', errors='replace')


def extract_background_images(source):
    source = html.unescape(source).replace('\\/', '/')
    pattern = r'''(?:(?:https?:)?//[^\s"'<>\\()]+|/[^\s"'<>\\()]+)?/uploads/[^\s"'<>\\()]*?/background-images/[^\s"'<>\\()]+\.(?:png|jpe?g|webp)'''
    return re.findall(pattern, source, flags=re.IGNORECASE)


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
        for key in ('style', 'data-background', 'data-image', 'data-bg'):
            self.background_images.extend(extract_background_images(attributes.get(key, '') or ''))

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def choose_image(url, source, page):
    if url.rstrip('/') == CARAMBAR_URL:
        return CARAMBAR_IMAGE
    candidates = extract_background_images(source)
    candidates.extend(page.background_images)
    for candidate in candidates:
        absolute = urllib.parse.urljoin(url, candidate)
        parsed = urllib.parse.urlparse(absolute)
        if parsed.scheme == 'https' and parsed.netloc == DOMAIN:
            return absolute
    for candidate in page.meta_images:
        absolute = urllib.parse.urljoin(url, candidate)
        if urllib.parse.urlparse(absolute).scheme == 'https':
            return absolute
    return ''


def valid_url(url):
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == 'https' and parsed.netloc == DOMAIN and parsed.path.endswith('.html')


def changes_fingerprint(changes):
    """Empreinte exacte des anciennes et nouvelles valeurs, indépendante de l'ordre."""
    normalized = sorted(
        (item['url'], field, str(values['ancien']), str(values['nouveau']))
        for item in changes
        for field, values in item['modifications'].items()
    )
    encoded = json.dumps(normalized, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def main():
    existing = json.loads(CATALOGUE.read_text(encoding='utf-8'))
    if not isinstance(existing, list) or not existing:
        raise ValueError('Catalogue absent, vide ou invalide : aucune modification')
    known = {r['url'].rstrip('/'): i for i, r in enumerate(existing)}
    root = ET.fromstring(fetch(BASE + 'sitemap.xml'))
    urls = list(dict.fromkeys(n.text.strip() for n in root.iter() if n.tag.rsplit('}', 1)[-1] == 'loc' and n.text))
    if len(urls) < len(existing):
        raise ValueError('Sitemap incomplet : aucune modification')

    additions = []
    changes = []
    errors = []
    ignored = 0
    examined = 0
    updated = [dict(recipe) for recipe in existing]

    for url in urls:
        if not valid_url(url):
            continue
        key = url.rstrip('/')
        is_existing = key in known
        examined += 1
        try:
            source = fetch(url)
            page = RecipePage()
            page.feed(source)
            title = html.unescape(page.title).strip()
            image = choose_image(url, source, page)
            if is_existing:
                recipe = updated[known[key]]
                fields = {}
                # Ne jamais effacer un titre ou une image si Weebly n'en fournit pas.
                if title and title != recipe.get('title'):
                    fields['title'] = {'ancien': recipe.get('title'), 'nouveau': title}
                if image and image != recipe.get('image'):
                    fields['image'] = {'ancien': recipe.get('image'), 'nouveau': image}
                if fields:
                    changes.append({'url': url, 'modifications': fields})
                    for field, values in fields.items():
                        recipe[field] = values['nouveau']
                    print(f"MODIFICATION : {url} / {', '.join(fields)}", flush=True)
            else:
                matches = [CATEGORIES.get((m.get('data-recette-categorie'), m.get('data-recette-sous-categorie'))) for m in page.markers]
                matches = [c for c in matches if c]
                if not matches:
                    ignored += 1
                    continue
                if len(set(matches)) != 1:
                    errors.append({'url': url, 'error': 'Repères contradictoires'})
                    continue
                if not title or not image:
                    errors.append({'url': url, 'error': 'Titre ou image manquant'})
                    continue
                additions.append({'title': title, 'category': matches[0], 'url': url, 'image': image})
                print(f'NOUVELLE RECETTE : {title} / {matches[0]} / {url}', flush=True)
        except Exception as exc:
            errors.append({'url': url, 'error': str(exc)})
        if examined % 100 == 0:
            print(f'Pages examinées : {examined}', flush=True)

    report = {
        'pages_sitemap': len(urls),
        'recettes_existantes': len(existing),
        'pages_examinees': examined,
        'ignorees_sans_repere': ignored,
        'nouvelles_recettes': additions,
        'recettes_modifiees': changes,
        'erreurs': errors,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Bilan : {len(additions)} ajout(s), {len(changes)} recette(s) modifiée(s), {len(errors)} erreur(s).', flush=True)
    if errors:
        raise RuntimeError('Certaines pages ont échoué : aucune mise à jour. Voir le rapport.')
    if len(additions) > MAX_ADDITIONS:
        raise RuntimeError('Plus de 10 ajouts : validation manuelle requise, aucune mise à jour.')
    initial_approved = (
        len(changes) == INITIAL_APPROVED_COUNT
        and changes_fingerprint(changes) == INITIAL_APPROVED_FINGERPRINT
    )
    if len(changes) > MAX_EXISTING_CHANGES and not initial_approved:
        raise RuntimeError('Plus de 10 recettes existantes modifiées et rapport différent de la synchronisation validée : aucune mise à jour.')
    if initial_approved:
        print('Première synchronisation validée : 210 titres et 1 photo. Empreinte conforme.', flush=True)
    if additions or changes:
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
