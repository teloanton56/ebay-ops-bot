from app.services.listing_generator import optimize_title, generate_description

def test_title_and_description():
    p={"title":"Support téléphone voiture voiture magnétique noir", "shipping_days":3, "aspects":{"Couleur":["Noir"]}}
    t=optimize_title(p["title"])
    assert len(t) <= 80
    assert t.lower().count("voiture") == 1
    d=generate_description(p)
    assert "Couleur" in d and "3 jour" in d
