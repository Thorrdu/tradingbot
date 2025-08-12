Évaluation “règles de l’art”
Points solides:
Normalisation par volatilité (z-score) avec EWM: simple et pertinent pour filtrer les faux signaux.
Confirmation multi-ticks: limite le bruit.
SL/TP liés à l’ATR-like plutôt qu’à des pourcentages fixes.
Limites constatées:
Exécution en MARKET seulement: frais taker + slippage → érode un edge de scalping.
Aucune contrainte sur le spread/impact avant d’entrer; pas de filtre de liquidité ni d’orderbook.
Le “auto mode” contrarian/momentum est indiqué, mais le basculement per‑symbol est placeholder (non effectif).
Le lookback est temporel fixe; pas d’adaptation du seuil z aux régimes (vol/heure).
Confirmation simple “même sens” sur N ticks, sans contrôle de renversement rapide.
Conséquence: beaucoup de SL et de MICRO_TRAIL visibles dans vos stats (exécution rapide mais prise de gains faibles), edge compressé par les frais.
Recommandations trading + code
Exécution maker (à implémenter):
Entrées BUY: LIMIT à prix maker ancré sur le bid: bid − offset_bps (IOC=false). Timeout entry_limit_timeout_sec avec fallback en MARKET si non rempli.
Sorties:
SL: rester en MARKET (priorité au risque).
TP/Trailing: tenter LIMIT côté bid/ask (maker) avec timeout court (ex: 2–3 s) puis fallback MARKET si non rempli.
Paramètres à ajouter:
prefer_maker: true|false
maker_offset_bps: 1.0–3.0
entry_limit_timeout_sec: 2–5
exit_limit_timeout_sec: 2–3 et exit_maker_for_tp: true, exit_maker_for_trailing: true
Prérequis: exposer une méthode client “book ticker” pour récupérer bid/ask, et une création d’ordre LIMIT (avec IOC optionnel). Si Pionex supporte post-only, l’activer; sinon, simuler post-only en plaçant prix intra‑spread côté passif.
Filtres d’entrée:
Filtre de spread: entrer seulement si spread <= X bps (réduit l’impact d’exécution).
Filtre d’orderbook: éviter d’acheter si l’imbalance Asks>>Bids au niveau 1–3 est défavorable.
Ajustement dynamique du seuil z: base 2.6, mais relevé en heures vol / abaissé en heures calmes via quantile des z sur la dernière heure.
Augmenter breakout_confirm_ticks à 3 pour réduire les micro‑bruits si le débit reste suffisant.
Auto‑mode effectif:
Implémenter le vrai basculement par paire: calculer rolling TP‑rate et PnL/trade sur N entrées et basculer ‘contrarian’ ↔ ‘momentum’ quand <45 % ou >55 % (avec hystérésis).
Qualité de price feed:
Calculer change_pct depuis mid=(bid+ask)/2 plutôt que last/close pour réduire le biais d’exécution.
Journalisation/frais:
Enregistrer fees estimées et slippage à l’entrée/sortie (à partir des fills) pour mesurer l’impact net.
