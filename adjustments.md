# Ajustements projet: passage à spot2 et amélioration exécution/entrées

Ce document trace les changements apportés pour professionnaliser l'architecture, introduire l'exécution maker et améliorer les critères d'entrée.

## Paramètres ajoutés (config)
- `prefer_maker` (bool, défaut true)
- `maker_offset_bps` (float, défaut 2.0)
- `entry_limit_timeout_sec` (int, défaut 3)
- `exit_limit_timeout_sec` (int, défaut 2)
- `exit_maker_for_tp` (bool, défaut true)
- `exit_maker_for_trailing` (bool, défaut true)
- `entry_max_spread_bps` (float, défaut 3.0)
- `entry_orderbook_min_imbalance` (float, défaut 0.0, 0–1, positif = bids>asks)
- `dynamic_z_enabled` (bool, défaut true)
- `dynamic_z_percentile` (float, défaut 0.7)

Valeurs optimales initiales appliquées: voir `pionex_futures_bot/config/config.json` (déjà mises à jour plus haut pour z, trailing).

## Architecture
- Nouveau module `spot2/`:
  - `bot.py`: logique haut niveau par symbole (signaux, gestion position, SL/TP, trailing)
  - `execution.py`: couche d’exécution (LIMIT maker avec timeout + fallback MARKET, gestion annulation, lecture book/ticker)
  - `signals.py`: utilitaires signaux (z dynamique, filtres spread/OB)

## Exécution maker
- Entrée BUY: LIMIT au bid − offset_bps, sans IOC, timeout `entry_limit_timeout_sec`, fallback MARKET si non rempli.
- TP/trailing: LIMIT côté maker avec timeout `exit_limit_timeout_sec`, fallback MARKET. SL reste MARKET.

## Filtres d’entrée
- Rejet si spread > `entry_max_spread_bps`.
- Rejet si imbalance OB sur 3 niveaux < `entry_orderbook_min_imbalance` (optionnel).

## Z-score dynamique
- Seuil effectif: `max(z_threshold_base, percentile(|z|, dynamic_z_percentile) )` sur une fenêtre mobile de z récents.

## CLI
- Nouvelle commande `spot2` dans `pionex_futures_bot/__main__.py`.


