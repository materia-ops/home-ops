-- AHBot listing tuning: more profession-levelling materials on the AH.
--
-- The mod-ah-bot quality/class mix lives in acore_world.mod_auctionhousebot,
-- not in mod_ahbot.conf (the conf only holds filters). Stock weights put white
-- trade goods (ore/herbs/cloth/leather — the levelling mats) at 27% while
-- green equipment got 30%; observed live result was ~7 cloth / ~9 herb
-- listings per faction house. Shift weight from green items to white trade
-- goods and raise the listing depth 1000 → 10000 per house (2026-07-18:
-- 4000 → 10000 after mats still felt thin; ~30k total is trivial for the
-- server — the only cost is longer TSM full scans).
--
-- The 14 percent columns must keep summing to 100 (module normalizes against
-- the total): 40+12+10+1 TGs + 10+17+8+2 items = 100.
--
-- NOT applied by Flux/dbimport. Apply manually against acore_world:
--   kubectl exec -i -n games azerothcore-db-0 -c azerothcore-db -- \
--     sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" acore_world' < ahbot-tuning.sql
-- Then restart the worldserver (the module reads this table at boot). The AH
-- fills toward the new maxitems over the following cycles. (Live alternative,
-- no restart: GM/SOAP `ahbotoptions maxitems <2|6|7> <n>` and
-- `ahbotoptions percentages ...` — both persist to this table themselves.)
--
-- Idempotent: safe to re-run, and must be re-applied after any from-scratch
-- dbimport rebuild (a kopiur restore of the dump PVC already covers it).

-- All houses (2 = Alliance, 6 = Horde, 7 = Neutral): white trade goods
-- 27 → 40, funded by green items 30 → 17.
UPDATE mod_auctionhousebot
SET percentwhitetradegoods = 40,
    percentgreenitems      = 17;

-- All houses: 10k listing depth (neutral included — Booty Bay is the realm's
-- shopping stop since Landro sells bags, see tcg-vendor.sql).
UPDATE mod_auctionhousebot
SET maxitems = 10000;

-- ---------------------------------------------------------------------------
-- Profession-mats floor (2026-07-19). Requires the azerothcore-image build
-- carrying the mod-ah-bot profession-mats-bin patch: its module migration
-- adds mod_auctionhousebot.percentprofessionmats (DEFAULT 0 = inert), so
-- ORDERING MATTERS — roll that image (or run its ALTER) BEFORE this section,
-- or the UPDATE below fails on the missing column.
--
-- The dedicated mats bin is fed from auctionhousebot_professionItems
-- (~3,660 rows, gems included) and is an ADDITIVE floor: mats stay in their
-- quality bins too. Uniform pick within the bin means per-item density =
-- binMax / 3660; to bias gems/levelling mats harder, curate that table down
-- later — deliberately NOT done here.
--
-- All 15 columns must still sum to 100 per house. Fund mats=20 from the
-- bins it overlaps most: whiteTG 40→28, greenTG 12→8, greenItems 17→13:
-- TGs 0+28+8+10+1+0+0 = 47, items 0+10+13+8+2+0+0 = 33, mats 20 → 100.
-- Live-tunable afterwards via `ahbotoptions percentages` (15 values).
UPDATE mod_auctionhousebot
SET percentprofessionmats  = 20,
    percentwhitetradegoods = 28,
    percentgreentradegoods = 8,
    percentgreenitems      = 13;
