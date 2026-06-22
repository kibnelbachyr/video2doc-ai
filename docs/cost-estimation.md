# Estimation des coûts Azure

Cette page propose une estimation des coûts mensuels Azure de video2doc-ai
selon trois scénarios de volumétrie. Elle est construite à partir de la
configuration réelle du pipeline (`infra/main.bicep`, `FRAMES_PER_MINUTE`)
combinée à des hypothèses d'usage explicites — **ce n'est pas un devis
contractuel**, mais un ordre de grandeur pour cadrer un budget.

> **⚠️ Fiabilité des tarifs unitaires.** Cet environnement n'a pas d'accès
> réseau direct aux pages de tarification officielles
> (`azure.microsoft.com/pricing`, API `prices.azure.com`) — toutes les
> tentatives ont été bloquées (403). Les tarifs ci-dessous proviennent de
> sources secondaires largement citées (calculateurs de coûts, retours
> communautaires) et **doivent être revérifiés** avant toute décision
> budgétaire, via le
> [calculateur de prix Azure](https://azure.microsoft.com/pricing/calculator/)
> ou directement dans le portail (Cost Management). Aucune différenciation
> tarifaire par région (France Central vs autre) n'a pu être confirmée — les
> tarifs pay-as-you-go Azure sont généralement identiques entre régions UE.
> Les montants sont en **USD** (devise par défaut des pages de pricing
> consultées) ; un abonnement facturé en EUR affichera des montants
> légèrement différents selon le taux de change appliqué par Microsoft.

---

## 1. Hypothèses d'usage retenues

| Paramètre | Hypothèse | Source |
|---|---|---|
| Rythme d'extraction des frames | 1 frame / 5 s (`FRAMES_PER_MINUTE=12`) | `infra/main.bicep` (valeur déployée) |
| Ressources par job (Container App) | 1 vCPU, 2 GiB, scale-to-zero | `infra/main.bicep` |
| Durée de traitement du pipeline | ≈ 1,5 × la durée de la vidéo (transcription + extraction + vision séquentielle + appel LLM) | Hypothèse — non mesurée précisément, à valider avec des jobs réels |
| Tokens LLM par vidéo | ≈ 172 tokens / frame (ancré sur l'exemple réel : 36 frames → 6 210 tokens, voir `docs/pipeline.md`) | Exemple empirique du log `[llm] Generation complete – 6210 tokens used` |
| Répartition tokens entrée/sortie | 80 % entrée / 20 % sortie | Hypothèse — le prompt (transcript + contexte visuel) domine largement la réponse générée |
| Taille moyenne d'un fichier vidéo | ≈ 30 Mo / minute (capture d'écran H.264 compressée) | Hypothèse à ajuster selon les vidéos réelles |
| Politique de rétention Blob | Aucune actuellement (voir [Plan de mise en production](production-readiness-plan.md)) | `infra/main.bicep` — pas de lifecycle policy |

---

## 2. Tarifs unitaires retenus (à vérifier)

| Service | Tarif retenu | Unité | Confiance |
|---|---|---|---|
| Azure Container Apps (Consumption) | $0.000024 / vCPU-s, $0.000003 / GiB-s | par seconde active | Moyenne |
| — grant gratuit mensuel | 180 000 vCPU-s, 360 000 GiB-s, 2M requêtes | par mois, par abonnement | Moyenne |
| Azure AI Speech (S0, temps réel) | $1.00 | par heure d'audio | Faible-moyenne |
| Azure AI Vision 4.0 (S1, caption + OCR) | $1.50 | par 1 000 transactions (1 frame = 1 transaction, caption+read demandés dans le même appel) | Faible — à confirmer si OCR est facturé séparément |
| Azure AI Foundry — GPT-4.1 Global Standard | $2.00 entrée / $8.00 sortie | par million de tokens | Moyenne (la plus cohérente entre sources) |
| Azure Blob Storage (Standard LRS, Hot) | ≈ $0.02 | par Go / mois | Faible — sources entre $0.018 et $0.023 |
| Azure Key Vault (Standard) | $0.03 | par 10 000 opérations | Moyenne |
| Azure Container Registry (Basic) | ≈ $5 | par mois (10 Go inclus) | Moyenne |
| Azure Static Web Apps (Free) | $0 | — | Élevée (confirmé) |

---

## 3. Coût marginal par minute de vidéo traitée

En combinant les hypothèses ci-dessus, le coût variable (hors stockage
cumulé et hors frais fixes d'infrastructure) suit approximativement :

| Poste | Coût / minute de vidéo |
|---|---|
| Azure AI Speech | ≈ $0.017 |
| Azure AI Vision (12 frames/min) | ≈ $0.018 |
| Azure AI Foundry (GPT-4.1) | ≈ $0.007 |
| Compute (Container Apps) | ≈ $0.003 |
| **Total marginal** | **≈ $0.044 / minute de vidéo** |

C'est l'indicateur le plus utile pour budgétiser : **environ 4 à 5 centimes
de dollar par minute de vidéo traitée**, hors stockage et hors coûts fixes.

---

## 4. Scénarios

### Scénario A — PoV / phase de test actuelle

10 vidéos/mois, durée moyenne 5 minutes (volume observé en PoV).

| Poste | Calcul | Coût/mois |
|---|---|---|
| Azure AI Speech | 10 × 5 min | $0.83 |
| Azure AI Vision | 10 × 60 frames | $0.90 |
| Azure AI Foundry (GPT-4.1) | 10 × ~10 300 tokens | $0.33 |
| Compute (Container Apps) | 4 500 vCPU-s — sous le grant gratuit | $0.00 |
| Stockage Blob | ~1,5 Go | $0.03 |
| Frais fixes (ACR + Key Vault) | — | $5.00 |
| **Total** | | **≈ $7 / mois** |

À ce volume, les frais fixes (ACR) dominent largement le coût réel d'usage.

### Scénario B — Pilote interne

50 vidéos/mois, durée moyenne 10 minutes.

| Poste | Calcul | Coût/mois |
|---|---|---|
| Azure AI Speech | 50 × 10 min | $8.35 |
| Azure AI Vision | 50 × 120 frames | $9.00 |
| Azure AI Foundry (GPT-4.1) | 50 × ~20 700 tokens | $3.31 |
| Compute (Container Apps) | 45 000 vCPU-s — sous le grant gratuit | $0.00 |
| Stockage Blob | ~15 Go | $0.30 |
| Frais fixes (ACR + Key Vault) | — | $5.00 |
| **Total** | | **≈ $26 / mois** |

### Scénario C — Production à volume soutenu

300 vidéos/mois, durée moyenne 15 minutes (≈ 10–15 vidéos/jour ouvré).

| Poste | Calcul | Coût/mois |
|---|---|---|
| Azure AI Speech | 300 × 15 min | $75.00 |
| Azure AI Vision | 300 × 180 frames | $81.00 |
| Azure AI Foundry (GPT-4.1) | 300 × ~31 000 tokens | $29.82 |
| Compute (Container Apps) | 405 000 vCPU-s, 225 000 au-dessus du grant gratuit | $6.75 |
| Stockage Blob | ~135 Go ajoutés/mois | $2.70 |
| Frais fixes (ACR + Key Vault) | — | $5.00 |
| **Total** | | **≈ $200 / mois** |

À ce volume, le grant gratuit mensuel de Container Apps ne couvre plus tout
le compute, et le stockage commence à devenir significatif **s'il n'y a pas
de politique de rétention** — voir point d'attention ci-dessous.

---

## 5. Tableau comparatif

| | Scénario A (PoV) | Scénario B (Pilote) | Scénario C (Production) |
|---|---|---|---|
| Vidéos/mois | 10 | 50 | 300 |
| Durée moyenne | 5 min | 10 min | 15 min |
| **Coût total estimé** | **≈ $7/mois** | **≈ $26/mois** | **≈ $200/mois** |
| Coût moyen / vidéo | ≈ $0.71 | ≈ $0.52 | ≈ $0.67 |

Le coût par vidéo reste dans une fourchette assez stable (~$0.50–0.70),
porté principalement par Speech + Vision + LLM, qui croissent
proportionnellement à la durée de la vidéo.

---

## 6. Points d'attention budgétaires

- **Stockage non borné** — sans politique de lifecycle sur le conteneur
  `jobs` (voir [Plan de mise en production](production-readiness-plan.md)),
  le stockage Blob **s'accumule mois après mois** plutôt que de se
  stabiliser à la ligne "Stockage" ci-dessus. Sur 12 mois sans purge, le
  scénario C atteindrait ~1,6 To stockés, soit ~$32/mois de stockage à lui
  seul (vs $2.70 en régime "ajout du mois").
- **GPT-4.1 Provisioned Throughput (PTU)** — au-delà d'un certain volume
  soutenu, un déploiement à débit provisionné peut devenir plus économique
  et plus prévisible que le pay-as-you-go `GlobalStandard` utilisé
  aujourd'hui ; à réévaluer une fois le volume réel du scénario C atteint.
- **`FRAMES_PER_MINUTE`** est le levier le plus direct : Vision et la part
  visuelle du prompt LLM sont quasi-linéaires avec le nombre de frames.
  Réduire de 12 à 6 frames/minute coupe environ de moitié ces deux postes
  sans changer Speech ni Compute.
- **Coûts non inclus dans cette estimation** : bande passante sortante
  (egress), Application Insights/Log Analytics (non déployés actuellement),
  authentification (APIM ou SWA Standard si ajoutée), support Azure.

---

## 7. Comment fiabiliser ces chiffres

1. **Calculateur de prix Azure** : https://azure.microsoft.com/pricing/calculator/
   — saisir les SKU exacts de `infra/main.bicep` (Container Apps
   Consumption, Speech S0, Vision S1, OpenAI GPT-4.1 Global Standard,
   Storage Standard LRS Hot, Key Vault Standard, ACR Basic).
2. **Portail Azure → Cost Management** une fois quelques semaines de PoV
   réel écoulées — les coûts observés remplaceront avantageusement toutes
   les hypothèses de ce document.
3. **API Retail Prices** (`prices.azure.com`) si un accès réseau direct est
   disponible côté utilisateur, pour obtenir les tarifs exacts par région
   et par SKU de façon programmatique.

---

## 8. Paramètres à saisir dans le calculateur Azure

Pour chaque ligne ci-dessous : rechercher le service dans le calculateur,
sélectionner la région **France Central** (repli sur **West Europe** si le
service n'y est pas listé), puis configurer comme indiqué. Le tableau final
donne les valeurs numériques à saisir pour reproduire les trois scénarios.

| Service à ajouter | Paramètres à sélectionner |
|---|---|
| **Azure Container Apps** | Type de plan : *Consumption* · vCPU : `1` · Mémoire : `2 GiB` · saisir directement les vCPU-secondes et GiB-secondes totales (voir tableau) |
| **Azure AI Speech** (sous *Cognitive Services* ou *Speech Services*) | Fonctionnalité : *Speech to Text* · Niveau : *Standard (S0)* · saisir les heures d'audio/mois |
| **Azure AI Vision** (*Computer Vision*) | Fonctionnalité : *Image Analysis* (Caption + Read/OCR) · Niveau : *Standard S1* · saisir les transactions/mois (1 frame = 1 transaction) |
| **Azure OpenAI Service** | Modèle : *GPT-4.1* · Type de déploiement : *Global Standard* (pay-as-you-go, pas de PTU) · saisir tokens d'entrée et de sortie séparément |
| **Storage Accounts** (Blob) | Type de compte : *Standard* · Redondance : *LRS* · Niveau d'accès : *Hot* · General Purpose v2 · saisir la capacité en Go |
| **Key Vault** | Niveau : *Standard* · saisir un nombre d'opérations faible (~5 000/mois) — coût négligeable dans tous les cas |
| **Container Registry** | Niveau : *Basic* | — coût fixe, pas de paramètre de volume |
| **Static Web Apps** | Niveau : *Free* | — $0, peut être omis du calcul |

### Valeurs à saisir par scénario

| Paramètre | Scénario A | Scénario B | Scénario C |
|---|---|---|---|
| Container Apps — vCPU-secondes/mois | 4 500 | 45 000 | 405 000 |
| Container Apps — GiB-secondes/mois | 9 000 | 90 000 | 810 000 |
| Container Apps — requêtes/mois | ~20 | ~100 | ~600 |
| Speech — heures d'audio/mois | 0.83 | 8.3 | 75 |
| Vision — transactions/mois | 600 | 6 000 | 54 000 |
| OpenAI — tokens d'entrée/mois | 82 800 | 828 000 | 7 452 000 |
| OpenAI — tokens de sortie/mois | 20 700 | 207 000 | 1 863 000 |
| Storage — capacité (Go) | 1.5 | 15 | 135 |

Le nombre de requêtes Container Apps ci-dessus ne couvre que l'upload et la
récupération du résultat ; le polling toutes les 2 s côté navigateur ajoute
des requêtes supplémentaires mais reste largement sous le quota gratuit de
2M requêtes/mois inclus, donc sans impact sur le total.
