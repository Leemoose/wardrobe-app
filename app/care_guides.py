"""
Curated care guide library for wardrobe items.

Each guide is a dict:
- id: unique slug
- title: display name
- materials: list of material tags this guide applies to ([] = any material)
- categories: list of category names this guide applies to ([] = any category)
- summary: one-line description
- sections: list of {heading, steps: [str]}
- supplies: list of recommended supplies
- tasks: list of {task, label, every_wears?, every_days?} - trackable
  maintenance tasks with recommended intervals

Matching specificity (computed in the care router):
  material + category match  >  material-only match  >  category-only fallback

Category names are matched case-insensitively. Guides with materials
require the item to have at least one listed material tag.
"""

GUIDES = [
    # ------------------------------------------------------------------
    # Material + category specific
    # ------------------------------------------------------------------
    {
        "id": "leather-shoes",
        "title": "Leather Shoe Care",
        "materials": ["leather"],
        "categories": ["shoes"],
        "summary": "Brushing, cleaning, conditioning, and waterproofing leather footwear.",
        "sections": [
            {
                "heading": "After every wear",
                "steps": [
                    "Brush off dust and dirt with a horsehair brush, especially along the welt and seams.",
                    "Insert cedar shoe trees to absorb moisture and hold the shape while they rest.",
                    "Let them rest at least 24 hours between wears so the leather can dry fully.",
                ],
            },
            {
                "heading": "Cleaning",
                "steps": [
                    "Wipe with a slightly damp cloth to lift surface grime.",
                    "For scuffs, use a small amount of leather cleaner or saddle soap on a soft cloth, working in circles.",
                    "Wipe away residue with a clean damp cloth and let air dry away from heat.",
                ],
            },
            {
                "heading": "White leather notes",
                "steps": [
                    "Clean white leather promptly - stains set fast. A magic eraser works on rubber soles and midsoles only, not the leather itself.",
                    "Use a white-specific cream polish or leather cleaner; tinted products will discolor.",
                    "A 1:1 mix of water and gentle dish soap on a soft cloth handles most marks; follow with a dry cloth.",
                ],
            },
            {
                "heading": "Conditioning & polishing",
                "steps": [
                    "Apply leather conditioner every 2-3 months to prevent drying and cracking - a little goes a long way.",
                    "For dress shoes, follow with cream polish matched to the color, then buff with a horsehair brush.",
                ],
            },
            {
                "heading": "Waterproofing",
                "steps": [
                    "Apply a waterproofing spray made for smooth leather every 1-2 months in wet seasons.",
                    "Spray evenly from about 6 inches away and let dry fully (ideally overnight) before wearing.",
                ],
            },
            {
                "heading": "Storage",
                "steps": [
                    "Store with shoe trees in a cool, dry spot out of direct sunlight.",
                    "Use dust bags or boxes for pairs you wear rarely.",
                ],
            },
        ],
        "supplies": [
            "Horsehair brush",
            "Cedar shoe trees",
            "Leather cleaner or saddle soap",
            "Leather conditioner",
            "Waterproofing spray (smooth leather)",
            "Cream polish (color-matched or neutral/white)",
        ],
        "tasks": [
            {"task": "brush", "label": "Brush clean", "every_wears": 3},
            {"task": "condition", "label": "Condition leather", "every_days": 90},
            {"task": "waterproof", "label": "Waterproof spray", "every_days": 60},
            {"task": "deep_clean", "label": "Deep clean / polish", "every_days": 120},
        ],
    },
    {
        "id": "suede-shoes",
        "title": "Suede & Nubuck Shoe Care",
        "materials": ["suede"],
        "categories": ["shoes"],
        "summary": "Protecting and reviving suede footwear - prevention is everything.",
        "sections": [
            {
                "heading": "Protection first",
                "steps": [
                    "Apply a suede protector spray before the first wear and reapply monthly.",
                    "Avoid rain and snow - water stains suede. Check the forecast before wearing.",
                ],
            },
            {
                "heading": "Routine care",
                "steps": [
                    "Brush with a suede brush after each wear, going with the nap in one direction.",
                    "Use a suede eraser (or clean pencil eraser) on scuffs and dry stains.",
                ],
            },
            {
                "heading": "Stains",
                "steps": [
                    "Blot wet stains immediately with a dry cloth - never rub.",
                    "For oil stains, apply cornstarch overnight, then brush out.",
                    "Water marks: lightly dampen the whole panel evenly with a spray bottle, then brush as it dries.",
                ],
            },
            {
                "heading": "Storage",
                "steps": [
                    "Store with shoe trees, away from sunlight which fades suede.",
                    "Never store in plastic - suede needs airflow.",
                ],
            },
        ],
        "supplies": [
            "Suede brush (brass/nylon)",
            "Suede eraser",
            "Suede protector spray",
            "Cedar shoe trees",
        ],
        "tasks": [
            {"task": "brush", "label": "Brush nap", "every_wears": 2},
            {"task": "waterproof", "label": "Protector spray", "every_days": 30},
        ],
    },
    {
        "id": "canvas-shoes",
        "title": "Canvas Sneaker Care",
        "materials": ["canvas"],
        "categories": ["shoes"],
        "summary": "Keeping canvas sneakers clean and fresh.",
        "sections": [
            {
                "heading": "Spot cleaning",
                "steps": [
                    "Mix mild detergent with warm water; scrub with a soft brush or old toothbrush.",
                    "Rubber soles and toe caps: a magic eraser removes most scuffs.",
                    "Wipe with a damp cloth and air dry - stuff with paper towels to hold shape.",
                ],
            },
            {
                "heading": "Deep cleaning",
                "steps": [
                    "Remove laces and insoles; wash laces separately in soapy water.",
                    "Hand wash is safest. If machine washing: cold water, gentle cycle, in a mesh bag, air dry only.",
                    "Never put canvas shoes in the dryer - heat warps the sole glue.",
                ],
            },
            {
                "heading": "Whitening",
                "steps": [
                    "For white canvas: paste of baking soda and a little hydrogen peroxide, scrub, sit 30 min, rinse.",
                    "Dry out of direct sun to avoid yellowing.",
                ],
            },
        ],
        "supplies": [
            "Mild detergent",
            "Soft brush / toothbrush",
            "Magic eraser",
            "Baking soda + hydrogen peroxide (whites)",
        ],
        "tasks": [
            {"task": "spot_clean", "label": "Spot clean", "every_wears": 5},
            {"task": "deep_clean", "label": "Deep clean", "every_days": 60},
        ],
    },
    # ------------------------------------------------------------------
    # Material-specific (any category)
    # ------------------------------------------------------------------
    {
        "id": "leather-goods",
        "title": "Leather Goods Care",
        "materials": ["leather"],
        "categories": [],
        "summary": "General care for leather jackets, bags, belts, and accessories.",
        "sections": [
            {
                "heading": "Routine",
                "steps": [
                    "Wipe down with a dry or slightly damp soft cloth after use.",
                    "Keep away from prolonged direct sunlight and heat sources, which dry and fade leather.",
                ],
            },
            {
                "heading": "Conditioning",
                "steps": [
                    "Condition every 3-6 months with a leather conditioner; test on a hidden spot first.",
                    "Jackets: pay attention to elbows, cuffs, and collar where leather flexes most.",
                ],
            },
            {
                "heading": "Storage",
                "steps": [
                    "Jackets: wide, padded hangers; never fold long-term (creases become permanent).",
                    "Bags: stuff with paper to hold shape, store in a dust bag.",
                    "Leather needs airflow - avoid plastic covers.",
                ],
            },
        ],
        "supplies": ["Leather conditioner", "Soft cloths", "Padded hangers / dust bags"],
        "tasks": [
            {"task": "condition", "label": "Condition leather", "every_days": 120},
            {"task": "wipe_down", "label": "Wipe down", "every_wears": 5},
        ],
    },
    {
        "id": "wool-care",
        "title": "Wool Care",
        "materials": ["wool"],
        "categories": [],
        "summary": "Washing, de-pilling, and storing wool garments.",
        "sections": [
            {
                "heading": "Washing",
                "steps": [
                    "Wash rarely - wool is naturally odor-resistant. Air out after wearing instead.",
                    "Hand wash in cold water with wool detergent (e.g. Woolite), or machine wool/delicate cycle in a mesh bag.",
                    "Never wring. Press water out in a towel, then dry FLAT - hanging stretches wet wool.",
                    "Never tumble dry - wool shrinks dramatically with heat and agitation.",
                ],
            },
            {
                "heading": "De-pilling",
                "steps": [
                    "Remove pills with a fabric shaver or sweater comb - normal for wool, not a defect.",
                ],
            },
            {
                "heading": "Wool trousers",
                "steps": [
                    "Dry clean only when actually dirty (2-4x per season), not after every wear.",
                    "Between wears: brush with a garment brush and hang on trouser hangers by the cuff.",
                    "Steam out wrinkles rather than ironing; if ironing, use a pressing cloth on wool setting.",
                ],
            },
            {
                "heading": "Storage",
                "steps": [
                    "Fold sweaters - never hang (shoulder bumps and stretching).",
                    "Off-season: clean first, then store in breathable bags with cedar blocks (moths target wool).",
                ],
            },
        ],
        "supplies": [
            "Wool detergent",
            "Mesh laundry bag",
            "Fabric shaver / sweater comb",
            "Garment brush",
            "Cedar blocks",
        ],
        "tasks": [
            {"task": "wash", "label": "Wash / clean", "every_wears": 6},
            {"task": "depill", "label": "De-pill", "every_days": 45},
            {"task": "brush", "label": "Brush", "every_wears": 3},
        ],
    },
    {
        "id": "cashmere-care",
        "title": "Cashmere Care",
        "materials": ["cashmere"],
        "categories": [],
        "summary": "Gentle handling for cashmere - it rewards care with decades of wear.",
        "sections": [
            {
                "heading": "Washing",
                "steps": [
                    "Hand wash in cool water with cashmere shampoo or baby shampoo - dry cleaning solvents actually degrade cashmere over time.",
                    "Soak 15 minutes, gently squeeze suds through, rinse cool. Never wring or twist.",
                    "Roll in a towel to press out water, reshape, and dry flat away from sun and heat.",
                ],
            },
            {
                "heading": "Pilling",
                "steps": [
                    "Light pilling on new cashmere is normal and decreases with washing.",
                    "Use a cashmere comb gently; avoid electric shavers on fine knits.",
                ],
            },
            {
                "heading": "Storage",
                "steps": [
                    "Always fold, never hang.",
                    "Store clean with cedar - moths love cashmere even more than wool.",
                ],
            },
        ],
        "supplies": ["Cashmere shampoo", "Cashmere comb", "Cedar blocks"],
        "tasks": [
            {"task": "wash", "label": "Hand wash", "every_wears": 5},
            {"task": "depill", "label": "Comb pills", "every_days": 60},
        ],
    },
    {
        "id": "denim-care",
        "title": "Denim Care",
        "materials": ["denim"],
        "categories": [],
        "summary": "Washing less, preserving fit and fade.",
        "sections": [
            {
                "heading": "Washing",
                "steps": [
                    "Wash as rarely as possible - every 8-10 wears preserves color and fit.",
                    "Spot clean small marks with a damp cloth instead of full washes.",
                    "When washing: turn inside out, cold water, gentle cycle, dark-safe detergent.",
                    "Air dry - the dryer fades denim and breaks down stretch fibers.",
                ],
            },
            {
                "heading": "Between washes",
                "steps": [
                    "Air out overnight after wearing.",
                    "For odors without washing: hang in a steamy bathroom, or a light spritz of 1:1 vodka/water.",
                ],
            },
        ],
        "supplies": ["Dark-safe detergent"],
        "tasks": [
            {"task": "wash", "label": "Wash (inside out, cold)", "every_wears": 9},
        ],
    },
    {
        "id": "silk-care",
        "title": "Silk Care",
        "materials": ["silk"],
        "categories": [],
        "summary": "Delicate handling for silk garments.",
        "sections": [
            {
                "heading": "Washing",
                "steps": [
                    "Check the label - some silk is dry clean only, especially structured pieces.",
                    "Hand wash in cold water with silk detergent, no more than 3-5 minutes of soaking.",
                    "Never wring. Roll in a towel and hang or lay flat to dry, away from sun.",
                ],
            },
            {
                "heading": "Ironing & stains",
                "steps": [
                    "Iron inside out on lowest silk setting while slightly damp, or steam.",
                    "Blot stains immediately with cold water - never rub, and never use hot water (sets protein stains).",
                ],
            },
        ],
        "supplies": ["Silk/delicate detergent", "Steamer"],
        "tasks": [
            {"task": "wash", "label": "Wash / dry clean", "every_wears": 3},
        ],
    },
    {
        "id": "linen-care",
        "title": "Linen Care",
        "materials": ["linen"],
        "categories": [],
        "summary": "Easy-care summer fabric that gets better with age.",
        "sections": [
            {
                "heading": "Washing",
                "steps": [
                    "Machine wash cold or lukewarm on gentle - linen gets softer with each wash.",
                    "Air dry or tumble low; remove while slightly damp to minimize wrinkles.",
                ],
            },
            {
                "heading": "Wrinkles",
                "steps": [
                    "Embrace some wrinkle - it's the character of linen.",
                    "For a crisp look, iron while damp on high steam.",
                ],
            },
        ],
        "supplies": ["Mild detergent"],
        "tasks": [
            {"task": "wash", "label": "Wash", "every_wears": 2},
        ],
    },
    {
        "id": "cotton-care",
        "title": "Cotton Care",
        "materials": ["cotton"],
        "categories": [],
        "summary": "Everyday care that prevents shrinking and fading.",
        "sections": [
            {
                "heading": "Washing",
                "steps": [
                    "Wash cold to prevent shrinking and fading; separate darks and lights.",
                    "Nice cotton trousers/chinos: turn inside out, cold gentle cycle or hand wash.",
                    "Air dry or tumble low - high heat is what shrinks cotton.",
                ],
            },
            {
                "heading": "Pressing",
                "steps": [
                    "Iron while slightly damp on cotton setting for crisp results.",
                    "Chinos and dress trousers: press a center crease with a pressing cloth if desired.",
                ],
            },
        ],
        "supplies": ["Detergent", "Iron / steamer"],
        "tasks": [
            {"task": "wash", "label": "Wash", "every_wears": 3},
        ],
    },
    {
        "id": "synthetic-care",
        "title": "Synthetic & Performance Fabric Care",
        "materials": ["synthetic"],
        "categories": [],
        "summary": "Polyester, nylon, and technical fabrics.",
        "sections": [
            {
                "heading": "Washing",
                "steps": [
                    "Wash cold on gentle; use sport detergent for workout gear to clear odor buildup.",
                    "Skip fabric softener - it coats fibers and ruins moisture-wicking.",
                    "Air dry or tumble low - high heat melts and warps synthetic fibers.",
                ],
            },
            {
                "heading": "Technical outerwear",
                "steps": [
                    "Wash with technical cleaner (e.g. Nikwax Tech Wash), not regular detergent.",
                    "Reproof DWR coating with wash-in or spray-on treatment when water stops beading.",
                ],
            },
        ],
        "supplies": ["Sport/technical detergent", "DWR reproofing treatment"],
        "tasks": [
            {"task": "wash", "label": "Wash", "every_wears": 2},
            {"task": "waterproof", "label": "Reproof DWR (technical shells)", "every_days": 180},
        ],
    },
    {
        "id": "down-care",
        "title": "Down & Puffer Care",
        "materials": ["down"],
        "categories": [],
        "summary": "Keeping down insulation lofty and effective.",
        "sections": [
            {
                "heading": "Washing",
                "steps": [
                    "Wash 1-2x per season max, with down-specific detergent in a front-loader.",
                    "Tumble dry LOW with 3-4 clean tennis balls to break up clumps - this step is essential.",
                    "Drying takes several cycles; down must be completely dry or it mildews.",
                ],
            },
            {
                "heading": "Storage",
                "steps": [
                    "Store uncompressed on a hanger or loosely in a large breathable bag.",
                    "Never store compressed long-term - it permanently kills the loft.",
                ],
            },
        ],
        "supplies": ["Down detergent", "Tennis/dryer balls"],
        "tasks": [
            {"task": "wash", "label": "Wash + tumble with balls", "every_days": 180},
        ],
    },
    {
        "id": "velvet-corduroy-care",
        "title": "Velvet & Corduroy Care",
        "materials": ["velvet", "corduroy"],
        "categories": [],
        "summary": "Protecting pile fabrics from crushing.",
        "sections": [
            {
                "heading": "Care",
                "steps": [
                    "Velvet: dry clean structured pieces; steam only, never iron directly (crushes pile).",
                    "Corduroy: wash inside out cold, air dry, brush the wales with a soft brush while damp.",
                    "Hang both - folding creates permanent crush lines.",
                ],
            },
        ],
        "supplies": ["Steamer", "Soft garment brush"],
        "tasks": [
            {"task": "wash", "label": "Wash / dry clean", "every_wears": 5},
        ],
    },
    # ------------------------------------------------------------------
    # Category fallbacks (no material required)
    # ------------------------------------------------------------------
    {
        "id": "shoes-general",
        "title": "Shoe Care Basics",
        "materials": [],
        "categories": ["shoes"],
        "summary": "Universal footwear habits that extend the life of any pair.",
        "sections": [
            {
                "heading": "Habits",
                "steps": [
                    "Rotate pairs - a day of rest lets moisture evaporate and doubles lifespan.",
                    "Use a shoe horn to protect heel counters.",
                    "Untie laces before removing; never crush the heel.",
                ],
            },
            {
                "heading": "Cleaning & freshness",
                "steps": [
                    "Wipe or brush off dirt after wearing before it grinds in.",
                    "Replace insoles when compressed or odorous; cedar trees or baking soda control smell.",
                ],
            },
            {
                "heading": "Repairs",
                "steps": [
                    "Resole quality shoes at a cobbler when the sole thins - far cheaper than replacing.",
                    "Fix small issues (loose stitching, worn heel taps) early.",
                ],
            },
        ],
        "supplies": ["Shoe horn", "Shoe trees", "Basic brush"],
        "tasks": [
            {"task": "clean", "label": "Clean / wipe down", "every_wears": 4},
        ],
    },
    {
        "id": "tops-general",
        "title": "Tops & Shirts Basics",
        "materials": [],
        "categories": ["tops", "shirts", "t-shirts"],
        "summary": "Default care for shirts and tops.",
        "sections": [
            {
                "heading": "Washing",
                "steps": [
                    "Follow the care label first; when in doubt, cold gentle cycle.",
                    "Turn printed/dark tees inside out to protect graphics and color.",
                    "Treat collar and underarm stains before washing (dish soap or stain stick works).",
                    "Air dry or low heat - dryers cause most shrinking and wear.",
                ],
            },
            {
                "heading": "Storage",
                "steps": [
                    "Hang dress shirts on shaped hangers; fold tees and knits.",
                ],
            },
        ],
        "supplies": ["Stain treatment", "Proper hangers"],
        "tasks": [
            {"task": "wash", "label": "Wash", "every_wears": 2},
        ],
    },
    {
        "id": "bottoms-general",
        "title": "Pants & Bottoms Basics",
        "materials": [],
        "categories": ["bottoms", "pants", "trousers", "shorts"],
        "summary": "Default care for trousers, pants, and shorts.",
        "sections": [
            {
                "heading": "Washing",
                "steps": [
                    "Most pants are overwashed - every 3-5 wears is plenty unless visibly dirty.",
                    "Turn inside out, wash cold, air dry to preserve color and shape.",
                    "Dress trousers: dry clean sparingly; steam and brush between cleanings.",
                ],
            },
            {
                "heading": "Storage",
                "steps": [
                    "Hang dress trousers by the cuff on clamp hangers, or fold along the crease over a bar.",
                    "Casual pants can be folded.",
                ],
            },
        ],
        "supplies": ["Trouser hangers", "Garment brush", "Steamer"],
        "tasks": [
            {"task": "wash", "label": "Wash / clean", "every_wears": 4},
        ],
    },
    {
        "id": "outerwear-general",
        "title": "Outerwear Basics",
        "materials": [],
        "categories": ["outerwear", "jackets", "coats"],
        "summary": "Default care for jackets and coats.",
        "sections": [
            {
                "heading": "Routine",
                "steps": [
                    "Brush off dirt and lint regularly with a garment brush.",
                    "Air out after wearing before returning to the closet.",
                    "Clean 1-2x per season (check label for dry clean vs. wash).",
                ],
            },
            {
                "heading": "Storage",
                "steps": [
                    "Sturdy, broad hangers - wire hangers deform shoulders.",
                    "Empty pockets before hanging (weight distorts shape).",
                    "Off-season: clean first, store in breathable garment bags.",
                ],
            },
        ],
        "supplies": ["Garment brush", "Broad hangers", "Garment bags"],
        "tasks": [
            {"task": "clean", "label": "Clean (seasonal)", "every_days": 120},
            {"task": "brush", "label": "Brush off", "every_wears": 4},
        ],
    },
    {
        "id": "accessories-general",
        "title": "Accessories Basics",
        "materials": [],
        "categories": ["accessories", "hats", "scarves", "belts", "bags", "watches", "jewelry"],
        "summary": "Default care for hats, scarves, belts, bags, and jewelry.",
        "sections": [
            {
                "heading": "General",
                "steps": [
                    "Wipe or brush after use; deal with marks promptly.",
                    "Hats: spot clean; never machine wash structured hats. Store on a shelf, not a hook.",
                    "Scarves: follow fabric-specific care (wool/silk/cotton rules apply).",
                    "Belts: hang or roll; condition leather belts a few times a year.",
                    "Watches & jewelry: wipe with a microfiber cloth after wear; store dry.",
                ],
            },
        ],
        "supplies": ["Microfiber cloths", "Soft brush"],
        "tasks": [
            {"task": "clean", "label": "Clean / wipe", "every_days": 90},
        ],
    },
]


def get_guide(guide_id: str):
    """Return a single guide by id, or None."""
    for g in GUIDES:
        if g["id"] == guide_id:
            return g
    return None


def match_guides(materials: list, category: str) -> list:
    """
    Return guides applicable to an item, sorted by specificity:
    material+category > material-only > category-fallback.

    materials: item's material tags (lowercased list)
    category: item's category name
    """
    materials = [m.lower() for m in (materials or [])]
    cat = (category or "").lower()

    scored = []
    for g in GUIDES:
        g_mats = [m.lower() for m in g["materials"]]
        g_cats = [c.lower() for c in g["categories"]]

        mat_match = bool(g_mats) and any(m in g_mats for m in materials)
        cat_match = bool(g_cats) and cat in g_cats

        if g_mats and g_cats:
            # Guide requires both material and category
            if mat_match and cat_match:
                scored.append((0, g))
        elif g_mats:
            # Material-only guide
            if mat_match:
                scored.append((1, g))
        elif g_cats:
            # Category fallback
            if cat_match:
                scored.append((2, g))

    scored.sort(key=lambda t: t[0])
    return [g for _, g in scored]
