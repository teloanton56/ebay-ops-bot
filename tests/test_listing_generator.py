from app.services.listing_generator import generate_description, optimize_title


def test_title_and_description_for_ebay_us():
    product = {
        "title": "Magnetic car phone holder holder black",
        "shipping_days": 3,
        "aspects": {"Color": ["Black"]},
    }
    title = optimize_title(product["title"])
    assert len(title) <= 80
    assert title.lower().count("holder") == 1

    description = generate_description(product)
    assert "Color" in description
    assert "3 day" in description
    assert "dispatch route and stock are rechecked before publication" in description


def test_competitor_title_cannot_replace_verified_cj_identity():
    optimized = optimize_title(
        "Portable USB Desk Fan Rechargeable Quiet Mini",
        market_keywords=[
            "fan",
            "Lasko 16 3-Speed Oscillating Adjustable Height Pedestal S16200 White Camping",
        ],
        variant_name="White USB",
        category_name="Desktop Fans",
    )

    assert optimized.startswith("Portable USB Desk Fan")
    assert "Lasko" not in optimized
    assert "S16200" not in optimized
    assert "Pedestal" not in optimized
    assert len(optimized) <= 80


def test_two_different_fans_keep_different_product_titles_with_same_radar_query():
    desk = optimize_title(
        "Portable USB Desk Fan Rechargeable Quiet Mini",
        market_keywords=["fan"],
        variant_name="White USB",
    )
    neck = optimize_title(
        "Bladeless Neck Fan Wearable Personal Cooling",
        market_keywords=["fan"],
        variant_name="Green 4000mAh",
    )

    assert desk != neck
    assert "Desk" in desk
    assert "Neck" in neck
