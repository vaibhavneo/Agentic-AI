-- Seed data: manual-entry fallback foods so nutrition logging works without
-- a USDA_FDC_API_KEY configured. Per-100g values are standard, commonly
-- published nutrition facts (USDA-published-order-of-magnitude), entered
-- here as manual label data — not LLM-invented, not fetched live. Runs once
-- (tracked in schema_migrations like any other migration).

INSERT INTO foods (source, external_id, name, calories_kcal, protein_g, carbs_g, fiber_g, total_fat_g, saturated_fat_g, sodium_mg, potassium_mg, calcium_mg, magnesium_mg, added_sugar_g) VALUES
('manual', 'seed:rice_white_cooked',   'White rice, cooked',            130, 2.7,  28.2, 0.4,  0.3,  0.1,  1,    35,   10,  12, 0),
('manual', 'seed:rice_brown_cooked',   'Brown rice, cooked',            123, 2.7,  25.6, 1.8,  1.0,  0.2,  4,    86,   10,  44, 0),
('manual', 'seed:roti_wheat',          'Whole wheat roti / chapati',    297, 11.3, 46.0, 4.9,  7.3,  1.5,  400,  200,  33,  60, 0),
('manual', 'seed:dal_cooked',          'Lentils (dal), cooked',         116, 9.0,  20.1, 7.9,  0.4,  0.1,  2,    369,  19,  36, 0),
('manual', 'seed:chicken_breast',      'Chicken breast, cooked, skinless', 165, 31.0, 0.0, 0.0,  3.6,  1.0,  74,   256,  15,  29, 0),
('manual', 'seed:egg_boiled',          'Egg, whole, boiled',            155, 13.0, 1.1,  0.0,  11.0, 3.3,  124,  126,  50,  10, 0),
('manual', 'seed:banana',              'Banana',                        89,  1.1,  22.8, 2.6,  0.3,  0.1,  1,    358,  5,   27, 0),
('manual', 'seed:apple',               'Apple',                         52,  0.3,  13.8, 2.4,  0.2,  0.0,  1,    107,  6,   5,  0),
('manual', 'seed:milk_lowfat',         'Milk, low-fat (2%)',            50,  3.4,  4.9,  0.0,  2.0,  1.2,  44,   150,  120, 11, 0),
('manual', 'seed:yogurt_greek_plain',  'Greek yogurt, plain, low-fat',  63,  10.0, 3.6,  0.0,  0.4,  0.3,  36,   141,  110, 11, 0),
('manual', 'seed:almonds',             'Almonds',                       579, 21.2, 21.6, 12.5, 49.9, 3.8,  1,    733,  269, 270, 0),
('manual', 'seed:spinach_cooked',      'Spinach, cooked',               23,  2.9,  3.6,  2.2,  0.3,  0.0,  70,   466,  99,  87,  0),
('manual', 'seed:broccoli_cooked',     'Broccoli, cooked',              35,  2.4,  7.2,  3.3,  0.4,  0.1,  41,   293,  40,  21,  0),
('manual', 'seed:salmon_cooked',       'Salmon, cooked',                208, 20.4, 0.0,  0.0,  13.4, 3.1,  59,   384,  9,   27,  0),
('manual', 'seed:bread_whole_wheat',   'Whole wheat bread',             247, 13.0, 41.0, 7.0,  3.4,  0.7,  400,  248,  107, 65,  4),
('manual', 'seed:oats_cooked',         'Oats, cooked (oatmeal)',        71,  2.5,  12.0, 1.7,  1.5,  0.3,  4,    70,   9,   27,  0),
('manual', 'seed:paneer',              'Paneer (Indian cottage cheese)',265, 18.3, 1.2,  0.0,  20.8, 13.8, 22,   138,  208, 15,  0),
('manual', 'seed:potato_boiled',       'Potato, boiled',                87,  1.9,  20.1, 1.8,  0.1,  0.0,  5,    379,  8,   22,  0),
('manual', 'seed:sweet_potato_baked',  'Sweet potato, baked',           90,  2.0,  20.7, 3.3,  0.2,  0.1,  36,   475,  38,  27,  0),
('manual', 'seed:tofu_firm',           'Tofu, firm',                    144, 15.7, 2.8,  2.3,  8.7,  1.3,  12,   148,  350, 30,  0),
('manual', 'seed:chickpeas_cooked',    'Chickpeas, cooked',             164, 8.9,  27.4, 7.6,  2.6,  0.3,  7,    291,  49,  48,  0),
('manual', 'seed:olive_oil',           'Olive oil',                     884, 0.0,  0.0,  0.0,  100.0,13.8, 2,    1,    1,   0,   0),
('manual', 'seed:avocado',             'Avocado',                       160, 2.0,  8.5,  6.7,  14.7, 2.1,  7,    485,  12,  29,  0),
('manual', 'seed:beef_ground_lean',    'Ground beef, 90% lean, cooked', 217, 26.1, 0.0,  0.0,  11.8, 4.6,  75,   318,  18,  21,  0),
('manual', 'seed:bread_white',         'White bread',                   265, 9.0,  49.0, 2.7,  3.2,  0.7,  490,  115,  151, 23,  5),
('manual', 'seed:cheddar_cheese',      'Cheddar cheese',                403, 24.9, 1.3,  0.0,  33.1, 21.0, 621,  98,   721, 28,  0),
('manual', 'seed:orange',              'Orange',                        47,  0.9,  11.8, 2.4,  0.1,  0.0,  0,    181,  40,  10,  0),
('manual', 'seed:cucumber',            'Cucumber',                      15,  0.65, 3.6,  0.5,  0.1,  0.0,  2,    147,  16,  13,  0),
('manual', 'seed:tomato',              'Tomato',                        18,  0.9,  3.9,  1.2,  0.2,  0.0,  5,    237,  10,  11,  0),
('manual', 'seed:peanut_butter',       'Peanut butter',                 588, 25.1, 20.0, 6.0,  50.4, 10.3, 17,   649,  43,  168, 9),
('manual', 'seed:instant_noodles',     'Instant noodles (with seasoning)', 436, 9.0, 61.0, 2.4,  17.0, 8.0,  1731, 130,  38,  20,  1),
('manual', 'seed:potato_chips',        'Potato chips',                  536, 7.0,  53.0, 4.4,  34.6, 10.9, 525,  1275, 24,  63,  0),
('manual', 'seed:soy_sauce',           'Soy sauce',                     53,  8.1,  4.9,  0.8,  0.6,  0.1,  5586, 435,  33,  47,  0);

-- Servings: one "100g" reference serving (useful for precise entry) plus a
-- natural default serving (what search/log_food resolves to by default).
INSERT INTO servings (food_id, description, grams, is_default)
SELECT id, '100g', 100, 0 FROM foods WHERE source = 'manual' AND external_id LIKE 'seed:%';

INSERT INTO servings (food_id, description, grams, is_default) VALUES
((SELECT id FROM foods WHERE external_id = 'seed:rice_white_cooked'),  '1 cup cooked (158g)', 158, 1),
((SELECT id FROM foods WHERE external_id = 'seed:rice_brown_cooked'),  '1 cup cooked (195g)', 195, 1),
((SELECT id FROM foods WHERE external_id = 'seed:roti_wheat'),         '1 medium roti (40g)', 40,  1),
((SELECT id FROM foods WHERE external_id = 'seed:dal_cooked'),         '1 cup cooked (198g)', 198, 1),
((SELECT id FROM foods WHERE external_id = 'seed:chicken_breast'),     '1 breast (172g)',     172, 1),
((SELECT id FROM foods WHERE external_id = 'seed:egg_boiled'),         '1 large egg (50g)',   50,  1),
((SELECT id FROM foods WHERE external_id = 'seed:banana'),             '1 medium (118g)',     118, 1),
((SELECT id FROM foods WHERE external_id = 'seed:apple'),              '1 medium (182g)',     182, 1),
((SELECT id FROM foods WHERE external_id = 'seed:milk_lowfat'),        '1 cup (244g)',        244, 1),
((SELECT id FROM foods WHERE external_id = 'seed:yogurt_greek_plain'), '1 cup (245g)',        245, 1),
((SELECT id FROM foods WHERE external_id = 'seed:almonds'),            '1 oz / 23 almonds (28g)', 28, 1),
((SELECT id FROM foods WHERE external_id = 'seed:spinach_cooked'),     '1 cup cooked (180g)', 180, 1),
((SELECT id FROM foods WHERE external_id = 'seed:broccoli_cooked'),    '1 cup (156g)',        156, 1),
((SELECT id FROM foods WHERE external_id = 'seed:salmon_cooked'),      '1 fillet (154g)',     154, 1),
((SELECT id FROM foods WHERE external_id = 'seed:bread_whole_wheat'),  '1 slice (28g)',       28,  1),
((SELECT id FROM foods WHERE external_id = 'seed:oats_cooked'),        '1 cup cooked (234g)', 234, 1),
((SELECT id FROM foods WHERE external_id = 'seed:paneer'),             '100g cube',           100, 1),
((SELECT id FROM foods WHERE external_id = 'seed:potato_boiled'),      '1 medium (167g)',     167, 1),
((SELECT id FROM foods WHERE external_id = 'seed:sweet_potato_baked'), '1 medium (114g)',     114, 1),
((SELECT id FROM foods WHERE external_id = 'seed:tofu_firm'),          '1/2 cup (126g)',      126, 1),
((SELECT id FROM foods WHERE external_id = 'seed:chickpeas_cooked'),   '1 cup (164g)',        164, 1),
((SELECT id FROM foods WHERE external_id = 'seed:olive_oil'),          '1 tbsp (14g)',        14,  1),
((SELECT id FROM foods WHERE external_id = 'seed:avocado'),            '1/2 avocado (100g)',  100, 1),
((SELECT id FROM foods WHERE external_id = 'seed:beef_ground_lean'),   '100g cooked',         100, 1),
((SELECT id FROM foods WHERE external_id = 'seed:bread_white'),        '1 slice (25g)',       25,  1),
((SELECT id FROM foods WHERE external_id = 'seed:cheddar_cheese'),     '1 oz (28g)',          28,  1),
((SELECT id FROM foods WHERE external_id = 'seed:orange'),             '1 medium (131g)',     131, 1),
((SELECT id FROM foods WHERE external_id = 'seed:cucumber'),           '1 cup sliced (104g)', 104, 1),
((SELECT id FROM foods WHERE external_id = 'seed:tomato'),             '1 medium (123g)',     123, 1),
((SELECT id FROM foods WHERE external_id = 'seed:peanut_butter'),      '2 tbsp (32g)',        32,  1),
((SELECT id FROM foods WHERE external_id = 'seed:instant_noodles'),    '1 package (85g dry)', 85,  1),
((SELECT id FROM foods WHERE external_id = 'seed:potato_chips'),       '1 oz (28g)',          28,  1),
((SELECT id FROM foods WHERE external_id = 'seed:soy_sauce'),          '1 tbsp (16g)',        16,  1);
