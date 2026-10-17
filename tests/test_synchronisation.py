import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import mettre_a_jour_recettes as sync


class SynchronisationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.catalogue = Path(self.temp.name) / 'recettes.json'
        self.report = Path(self.temp.name) / 'rapport.json'
        self.url = sync.BASE + 'recette.html'
        self.recipe = dict(title='Ancien titre', image=sync.BASE + 'ancienne.jpg',
                           category='Soupes et Veloutés', url=self.url,
                           subcategory='Classement personnel', favorite=True)

    def run_sync(self, pages, recipes=None, dry_run=False):
        recipes = copy.deepcopy(recipes if recipes is not None else [self.recipe])
        self.catalogue.write_text(json.dumps(recipes), encoding='utf-8')
        sitemap = '<urlset>' + ''.join('<url><loc>' + url + '</loc></url>' for url in pages) + '</urlset>'

        def fetch(url):
            if url == sync.BASE + 'sitemap.xml':
                return sitemap
            result = pages[url]
            if isinstance(result, Exception):
                raise result
            return result

        with patch.object(sync, 'CATALOGUE', self.catalogue), patch.object(sync, 'REPORT', self.report), patch.object(sync, 'fetch', side_effect=fetch), contextlib.redirect_stdout(io.StringIO()):
            sync.main(dry_run=dry_run)
        return json.loads(self.catalogue.read_text(encoding='utf-8'))

    def test_update_and_add_preserves_all_other_fields(self):
        new = sync.BASE + 'nouvelle.html'
        pages = {self.url: '<title>Nouveau &amp; délicieux</title><meta property="og:image" content="/nouvelle.jpg">',
                 new: '<title>Nouvelle recette</title><meta property="og:image" content="/photo.jpg"><div data-recette-categorie="desserts" data-recette-sous-categorie="tartes-et-tartelettes"></div>'}
        result = self.run_sync(pages)
        expected = dict(self.recipe, title='Nouveau & délicieux', image=sync.BASE + 'nouvelle.jpg')
        self.assertEqual(result[0], expected)
        self.assertEqual(result[1]['category'], 'Tartes et tartelettes')
        self.assertEqual(result[1]['url'], new)
        # Une seconde exécution ne produit aucune différence.
        self.assertEqual(self.run_sync(pages, result), result)
        self.assertEqual(json.loads(self.report.read_text(encoding='utf-8'))['recettes_modifiees'], [])

    def test_empty_values_preserve_existing_data(self):
        for source in ('', '<title> </title><meta property="og:image" content="   ">'):
            with self.subTest(source=source):
                self.assertEqual(self.run_sync({self.url: source}), [self.recipe])

    def test_fields_update_independently(self):
        self.assertEqual(self.run_sync({self.url: '<title>Nouveau</title>'}), [dict(self.recipe, title='Nouveau')])
        self.assertEqual(self.run_sync({self.url: '<meta property="og:image" content="/photo.jpg">'}), [dict(self.recipe, image=sync.BASE + 'photo.jpg')])

    def test_network_error_leaves_catalogue_untouched(self):
        with self.assertRaises(RuntimeError):
            self.run_sync({self.url: OSError('Indisponible')})
        self.assertEqual(json.loads(self.catalogue.read_text()), [self.recipe])

    def test_dry_run_reports_without_writing_catalogue(self):
        self.assertEqual(self.run_sync({self.url: '<title>Nouveau</title>'}, dry_run=True), [self.recipe])
        self.assertEqual(len(json.loads(self.report.read_text())['recettes_modifiees']), 1)

    def test_absent_recipe_is_preserved(self):
        self.assertEqual(self.run_sync({sync.BASE + 'accueil.html': '<title>Accueil</title>'}), [self.recipe])

    def test_large_update_is_blocked(self):
        recipes = [dict(self.recipe, url=sync.BASE + str(i) + '.html') for i in range(11)]
        with self.assertRaises(RuntimeError):
            self.run_sync({r['url']: '<title>Nouveau</title>' for r in recipes}, recipes)
        self.assertEqual(json.loads(self.catalogue.read_text()), recipes)

    def test_carambar_uses_new_photo_with_legacy_fallback(self):
        page = sync.RecipePage()
        source = '<div style="background-image:url(/uploads/1/background-images/nouvelle.jpg)"></div>'
        page.feed(source)
        self.assertEqual(sync.choose_image(sync.CARAMBAR_URL, source, page), sync.BASE + 'uploads/1/background-images/nouvelle.jpg')
        self.assertEqual(sync.choose_image(sync.CARAMBAR_URL, '', sync.RecipePage()), sync.CARAMBAR_IMAGE)


if __name__ == '__main__':
    unittest.main()
