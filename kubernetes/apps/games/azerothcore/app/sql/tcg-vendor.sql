-- TCG loot + bag vendor: Landro Longshot (Booty Bay, NPC 17249)
-- Makes the retail TCG-code redeemer a gold vendor for all WotLK-era TCG loot,
-- plus every 16+ slot bag (general + profession) not sold by a stock vendor —
-- crafted-only bags (Netherweave/Frostweave/…) structurally never appear on
-- the AH (AHBot draws greens uniformly from a ~5,400-item pool).
--
-- NOT applied by Flux/dbimport. Apply manually against acore_world:
--   kubectl exec -i -n games azerothcore-db-0 -- \
--     sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" acore_world' < tcg-vendor.sql
-- Then restart the worldserver (item/vendor/creature templates are cached at
-- boot) and wipe client Cache\WDB so new buy prices display.
--
-- Idempotent: safe to re-run, and must be re-applied after any from-scratch
-- dbimport rebuild (a kopiur restore of the dump PVC already covers it).

-- ---------------------------------------------------------------------------
-- Buy prices (copper = gold * 10000). All these items ship with BuyPrice 0.
-- ---------------------------------------------------------------------------
-- Mounts
UPDATE item_template SET BuyPrice = 1000000000 WHERE entry = 33225; -- Reins of the Swift Spectral Tiger (100,000g)
UPDATE item_template SET BuyPrice =  500000000 WHERE entry = 46778; -- Magic Rooster Egg (50,000g)
UPDATE item_template SET BuyPrice =  450000000 WHERE entry = 54069; -- Blazing Hippogryph (45,000g)
UPDATE item_template SET BuyPrice =  400000000 WHERE entry = 33224; -- Reins of the Spectral Tiger (40,000g)
UPDATE item_template SET BuyPrice =  350000000 WHERE entry = 35226; -- X-51 Nether-Rocket X-TREME (35,000g)
UPDATE item_template SET BuyPrice =  300000000 WHERE entry = 38576; -- Big Battle Bear (30,000g)
UPDATE item_template SET BuyPrice =  300000000 WHERE entry = 54068; -- Wooly White Rhino (30,000g)
UPDATE item_template SET BuyPrice =  150000000 WHERE entry = 35225; -- X-51 Nether-Rocket (15,000g)
UPDATE item_template SET BuyPrice =   75000000 WHERE entry = 23720; -- Riding Turtle (7,500g)
-- Pets
UPDATE item_template SET BuyPrice =   60000000 WHERE entry = 34493; -- Dragon Kite (6,000g)
UPDATE item_template SET BuyPrice =   60000000 WHERE entry = 49343; -- Spectral Tiger Cub (6,000g)
UPDATE item_template SET BuyPrice =   50000000 WHERE entry = 38050; -- Soul-Trader Beacon (5,000g)
UPDATE item_template SET BuyPrice =   40000000 WHERE entry = 23713; -- Hippogryph Hatchling (4,000g)
UPDATE item_template SET BuyPrice =   40000000 WHERE entry = 49287; -- Tuskarr Kite (4,000g)
UPDATE item_template SET BuyPrice =   30000000 WHERE entry = 34492; -- Rocket Chicken (3,000g)
UPDATE item_template SET BuyPrice =   25000000 WHERE entry = 32588; -- Banana Charm (2,500g)
-- Tabards
UPDATE item_template SET BuyPrice =   30000000 WHERE entry = 23705; -- Tabard of Flame (3,000g)
UPDATE item_template SET BuyPrice =   30000000 WHERE entry = 23709; -- Tabard of Frost (3,000g)
UPDATE item_template SET BuyPrice =   10000000 WHERE entry = 38309; -- Tabard of Nature (1,000g)
UPDATE item_template SET BuyPrice =   10000000 WHERE entry = 38310; -- Tabard of the Arcane (1,000g)
UPDATE item_template SET BuyPrice =   10000000 WHERE entry = 38311; -- Tabard of the Void (1,000g)
UPDATE item_template SET BuyPrice =   10000000 WHERE entry = 38312; -- Tabard of Brilliance (1,000g)
UPDATE item_template SET BuyPrice =   10000000 WHERE entry = 38313; -- Tabard of Fury (1,000g)
UPDATE item_template SET BuyPrice =   10000000 WHERE entry = 38314; -- Tabard of the Defender (1,000g)
-- Toys (permanent)
UPDATE item_template SET BuyPrice =   25000000 WHERE entry = 23716; -- Carved Ogre Idol (2,500g)
UPDATE item_template SET BuyPrice =   20000000 WHERE entry = 35227; -- Goblin Weather Machine - Prototype 01-B (2,000g)
UPDATE item_template SET BuyPrice =   15000000 WHERE entry = 38301; -- D.I.S.C.O. (1,500g)
UPDATE item_template SET BuyPrice =   15000000 WHERE entry = 38578; -- The Flag of Ownership (1,500g)
UPDATE item_template SET BuyPrice =   15000000 WHERE entry = 54452; -- Ethereal Portal (1,500g)
UPDATE item_template SET BuyPrice =   10000000 WHERE entry = 23714; -- Perpetual Purple Firework (1,000g)
UPDATE item_template SET BuyPrice =   10000000 WHERE entry = 33223; -- Fishing Chair (1,000g)
UPDATE item_template SET BuyPrice =   10000000 WHERE entry = 45037; -- Epic Purple Shirt (1,000g)
UPDATE item_template SET BuyPrice =   10000000 WHERE entry = 45063; -- Foam Sword Rack (1,000g)
UPDATE item_template SET BuyPrice =   10000000 WHERE entry = 54212; -- Instant Statue Pedestal (1,000g)
UPDATE item_template SET BuyPrice =    7500000 WHERE entry = 32542; -- Imp in a Ball (750g)
UPDATE item_template SET BuyPrice =    7500000 WHERE entry = 32566; -- Picnic Basket (750g)
UPDATE item_template SET BuyPrice =    7500000 WHERE entry = 33219; -- Goblin Gumbo Kettle (750g)
UPDATE item_template SET BuyPrice =    7500000 WHERE entry = 45047; -- Sandbox Tiger (750g)
UPDATE item_template SET BuyPrice =    5000000 WHERE entry = 34499; -- Paper Flying Machine Kit (500g)
-- Consumables
UPDATE item_template SET BuyPrice =   10000000 WHERE entry = 54218; -- Landro's Gift Box (1,000g)
UPDATE item_template SET BuyPrice =    2500000 WHERE entry = 46780; -- Ogre Pinata (250g)
UPDATE item_template SET BuyPrice =    1000000 WHERE entry = 38233; -- Path of Illidan (100g)
UPDATE item_template SET BuyPrice =    1000000 WHERE entry = 38577; -- Party G.R.E.N.A.D.E. (100g)
UPDATE item_template SET BuyPrice =    1000000 WHERE entry = 46779; -- Path of Cenarius (100g)
UPDATE item_template SET BuyPrice =    1000000 WHERE entry = 54455; -- Paint Bomb (100g)
UPDATE item_template SET BuyPrice =     500000 WHERE entry = 35223; -- Papa Hummel's Old-Fashioned Pet Biscuit (50g)

-- ---------------------------------------------------------------------------
-- Vendor inventory (slot = display order: mounts, pets, tabards, toys,
-- consumables, then bags)
-- ---------------------------------------------------------------------------
DELETE FROM npc_vendor WHERE entry = 17249;
INSERT INTO npc_vendor (entry, slot, item, maxcount, incrtime, ExtendedCost, VerifiedBuild) VALUES
(17249,  1, 33225, 0, 0, 0, 0), -- Reins of the Swift Spectral Tiger
(17249,  2, 46778, 0, 0, 0, 0), -- Magic Rooster Egg
(17249,  3, 54069, 0, 0, 0, 0), -- Blazing Hippogryph
(17249,  4, 33224, 0, 0, 0, 0), -- Reins of the Spectral Tiger
(17249,  5, 35226, 0, 0, 0, 0), -- X-51 Nether-Rocket X-TREME
(17249,  6, 38576, 0, 0, 0, 0), -- Big Battle Bear
(17249,  7, 54068, 0, 0, 0, 0), -- Wooly White Rhino
(17249,  8, 35225, 0, 0, 0, 0), -- X-51 Nether-Rocket
(17249,  9, 23720, 0, 0, 0, 0), -- Riding Turtle
(17249, 10, 34493, 0, 0, 0, 0), -- Dragon Kite
(17249, 11, 49343, 0, 0, 0, 0), -- Spectral Tiger Cub
(17249, 12, 38050, 0, 0, 0, 0), -- Soul-Trader Beacon
(17249, 13, 23713, 0, 0, 0, 0), -- Hippogryph Hatchling
(17249, 14, 49287, 0, 0, 0, 0), -- Tuskarr Kite
(17249, 15, 34492, 0, 0, 0, 0), -- Rocket Chicken
(17249, 16, 32588, 0, 0, 0, 0), -- Banana Charm
(17249, 17, 23705, 0, 0, 0, 0), -- Tabard of Flame
(17249, 18, 23709, 0, 0, 0, 0), -- Tabard of Frost
(17249, 19, 38312, 0, 0, 0, 0), -- Tabard of Brilliance
(17249, 20, 38313, 0, 0, 0, 0), -- Tabard of Fury
(17249, 21, 38309, 0, 0, 0, 0), -- Tabard of Nature
(17249, 22, 38310, 0, 0, 0, 0), -- Tabard of the Arcane
(17249, 23, 38314, 0, 0, 0, 0), -- Tabard of the Defender
(17249, 24, 38311, 0, 0, 0, 0), -- Tabard of the Void
(17249, 25, 23716, 0, 0, 0, 0), -- Carved Ogre Idol
(17249, 26, 35227, 0, 0, 0, 0), -- Goblin Weather Machine - Prototype 01-B
(17249, 27, 38301, 0, 0, 0, 0), -- D.I.S.C.O.
(17249, 28, 38578, 0, 0, 0, 0), -- The Flag of Ownership
(17249, 29, 54452, 0, 0, 0, 0), -- Ethereal Portal
(17249, 30, 23714, 0, 0, 0, 0), -- Perpetual Purple Firework
(17249, 31, 45063, 0, 0, 0, 0), -- Foam Sword Rack
(17249, 32, 45037, 0, 0, 0, 0), -- Epic Purple Shirt
(17249, 33, 54212, 0, 0, 0, 0), -- Instant Statue Pedestal
(17249, 34, 33223, 0, 0, 0, 0), -- Fishing Chair
(17249, 35, 32566, 0, 0, 0, 0), -- Picnic Basket
(17249, 36, 33219, 0, 0, 0, 0), -- Goblin Gumbo Kettle
(17249, 37, 32542, 0, 0, 0, 0), -- Imp in a Ball
(17249, 38, 45047, 0, 0, 0, 0), -- Sandbox Tiger
(17249, 39, 34499, 0, 0, 0, 0), -- Paper Flying Machine Kit
(17249, 40, 54218, 0, 0, 0, 0), -- Landro's Gift Box
(17249, 41, 46780, 0, 0, 0, 0), -- Ogre Pinata
(17249, 42, 38233, 0, 0, 0, 0), -- Path of Illidan
(17249, 43, 46779, 0, 0, 0, 0), -- Path of Cenarius
(17249, 44, 38577, 0, 0, 0, 0), -- Party G.R.E.N.A.D.E.
(17249, 45, 54455, 0, 0, 0, 0), -- Paint Bomb
(17249, 46, 35223, 0, 0, 0, 0), -- Papa Hummel's Old-Fashioned Pet Biscuit
-- Bags: general (by size), then soul/herb/enchanting/engineering/gem/mining/
-- leatherworking/inscription. Prices come from the items' stock BuyPrice
-- (all nonzero — no item_template changes, so no client cache wipe needed).
-- Excluded: test/deprecated items (1977, 4501, 13330, 21857, 2119x, 23162)
-- and bags stock vendors already sell (Haris Pilton, Halaa, profession
-- suppliers: 27680, 30745-30748, 38082, 51809).
(17249, 47,  4500, 0, 0, 0, 0), -- Traveler's Backpack (16)
(17249, 48, 10683, 0, 0, 0, 0), -- Explorer's Knapsack (16)
(17249, 49, 10959, 0, 0, 0, 0), -- Demon Hide Sack (16)
(17249, 50, 11742, 0, 0, 0, 0), -- Wayfarer's Knapsack (16)
(17249, 51, 14155, 0, 0, 0, 0), -- Mooncloth Bag (16)
(17249, 52, 20400, 0, 0, 0, 0), -- Pumpkin Bag (16)
(17249, 53, 21841, 0, 0, 0, 0), -- Netherweave Bag (16)
(17249, 54, 22233, 0, 0, 0, 0), -- Zigris' Footlocker (16)
(17249, 55, 14156, 0, 0, 0, 0), -- Bottomless Bag (18)
(17249, 56, 17966, 0, 0, 0, 0), -- Onyxia Hide Backpack (18)
(17249, 57, 19914, 0, 0, 0, 0), -- Panther Hide Sack (18)
(17249, 58, 21843, 0, 0, 0, 0), -- Imbued Netherweave Bag (18)
(17249, 59, 22679, 0, 0, 0, 0), -- Supply Bag (18)
(17249, 60, 33117, 0, 0, 0, 0), -- Jack-o'-Lantern (18)
(17249, 61, 21876, 0, 0, 0, 0), -- Primal Mooncloth Bag (20)
(17249, 62, 34067, 0, 0, 0, 0), -- Tattered Hexcloth Sack (20)
(17249, 63, 34845, 0, 0, 0, 0), -- Pit Lord's Satchel (20)
(17249, 64, 35516, 0, 0, 0, 0), -- Sun Touched Satchel (20)
(17249, 65, 41599, 0, 0, 0, 0), -- Frostweave Bag (20)
(17249, 66, 50317, 0, 0, 0, 0), -- Papa's New Bag (20)
(17249, 67, 41600, 0, 0, 0, 0), -- Glacial Bag (22)
(17249, 68, 43345, 0, 0, 0, 0), -- Dragon Hide Bag (22)
(17249, 69, 49295, 0, 0, 0, 0), -- Enlarged Onyxia Hide Backpack (22)
(17249, 70, 50316, 0, 0, 0, 0), -- Papa's Brand New Bag (22)
(17249, 71, 22244, 0, 0, 0, 0), -- Box of Souls (16, soul)
(17249, 72, 21340, 0, 0, 0, 0), -- Soul Pouch (20, soul)
(17249, 73, 21341, 0, 0, 0, 0), -- Felcloth Bag (24, soul)
(17249, 74, 21342, 0, 0, 0, 0), -- Core Felcloth Bag (28, soul)
(17249, 75, 21872, 0, 0, 0, 0), -- Ebon Shadowbag (28, soul)
(17249, 76, 41597, 0, 0, 0, 0), -- Abyssal Bag (32, soul)
(17249, 77, 22251, 0, 0, 0, 0), -- Cenarion Herb Bag (20, herb)
(17249, 78, 22252, 0, 0, 0, 0), -- Satchel of Cenarius (24, herb)
(17249, 79, 38225, 0, 0, 0, 0), -- Mycah's Botanical Bag (28, herb)
(17249, 80, 45773, 0, 0, 0, 0), -- Emerald Bag (32, herb)
(17249, 81, 22246, 0, 0, 0, 0), -- Enchanted Mageweave Pouch (16, ench)
(17249, 82, 22248, 0, 0, 0, 0), -- Enchanted Runecloth Bag (20, ench)
(17249, 83, 22249, 0, 0, 0, 0), -- Big Bag of Enchantment (24, ench)
(17249, 84, 21858, 0, 0, 0, 0), -- Spellfire Bag (28, ench)
(17249, 85, 41598, 0, 0, 0, 0), -- Mysterious Bag (32, ench)
(17249, 86, 23774, 0, 0, 0, 0), -- Fel Iron Toolbox (24, eng)
(17249, 87, 23775, 0, 0, 0, 0), -- Titanium Toolbox (32, eng)
(17249, 88, 24270, 0, 0, 0, 0), -- Bag of Jewels (24, gem)
(17249, 89, 29540, 0, 0, 0, 0), -- Reinforced Mining Bag (28, mining)
(17249, 90, 38347, 0, 0, 0, 0), -- Mammoth Mining Bag (32, mining)
(17249, 91, 34482, 0, 0, 0, 0), -- Leatherworker's Satchel (20, lw)
(17249, 92, 34490, 0, 0, 0, 0), -- Bag of Many Hides (24, lw)
(17249, 93, 38399, 0, 0, 0, 0), -- Trapper's Traveling Pack (28, lw)
(17249, 94, 38307, 0, 0, 0, 0), -- Crafty's Bottomless Inscription Bag (32, inscr)
(17249, 95, 44446, 0, 0, 0, 0); -- Pack of Endless Pockets (32, inscr)

-- ---------------------------------------------------------------------------
-- Give Landro the vendor flag (ships gossip-only: npcflag 1 -> 1|128 = 129)
-- ---------------------------------------------------------------------------
UPDATE creature_template SET npcflag = npcflag | 128 WHERE entry = 17249;

-- ---------------------------------------------------------------------------
-- Reach the vendor: Landro ships a gossip menu (7394, the TCG promotions
-- tree), and a vendor npcflag alone can't open the shop when a gossip menu is
-- present — the player needs a gossip option of type 3 (vendor). Add
-- "browse your goods" to his root menu (OptionNpcFlag 128 = only shows while
-- the vendor flag is set). Without this the 96 vendor rows above are
-- unreachable. Live changes need `.reload gossip_menu_option`.
-- ---------------------------------------------------------------------------
DELETE FROM gossip_menu_option WHERE MenuID = 7394 AND OptionID = 1;
INSERT INTO gossip_menu_option (MenuID, OptionID, OptionIcon, OptionText, OptionType, OptionNpcFlag)
VALUES (7394, 1, 1, 'I would like to browse your goods.', 3, 128);
