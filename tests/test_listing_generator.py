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
