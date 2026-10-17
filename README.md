# Recettes de Léonard

## Mettre à jour le catalogue

1. Modifier la recette sur Weebly, puis **publier** les changements.
2. Attendre la prochaine mise à jour quotidienne, ou ouvrir **Actions → Mise a jour automatique des recettes → Run workflow** dans GitHub pour la lancer immédiatement.
3. Attendre la fin de l'exécution et la publication de GitHub Pages, puis actualiser le catalogue dans le navigateur.

Chaque exécution recherche les nouvelles recettes et relit les recettes déjà répertoriées présentes dans le sitemap. Leurs titres et photos sont actualisés même sans repère de catégorie. Les nouvelles recettes doivent toujours porter les repères de catégorie et de sous-catégorie Weebly reconnus par le script.

Les catégories, sous-catégories, URL, champs supplémentaires et recettes absentes du sitemap sont conservés. Un titre ou une photo manquants ne remplacent jamais les données existantes. La photo historique du velouté de Carambar sert seulement de secours lorsqu'aucune photo n'est détectée.

En cas d'échec d'une page, le catalogue reste inchangé. Les limites existantes de 10 ajouts et de 10 recettes modifiées par exécution sont conservées, ainsi que l'exception initiale déjà validée dans le script. Si une limite est dépassée, consulter le rapport avant toute intervention : le script n'applique pas une mise à jour partielle.

Le détail des ajouts, modifications et erreurs figure dans l'artefact **rapport-mise-a-jour-recettes**, téléchargeable dans l'exécution GitHub Actions.

## Vérifier le script

Les tests sans accès réseau s'exécutent avant chaque synchronisation dans GitHub Actions. Pour les lancer localement :

```sh
python -m unittest discover -s tests -v
```

Pour analyser Weebly et générer `rapport_mise_a_jour.json` sans modifier le catalogue :

```sh
python scripts/mettre_a_jour_recettes.py --dry-run
```

Cette simulation conserve les mêmes contrôles et peut donc signaler une erreur ou un dépassement de limite.
