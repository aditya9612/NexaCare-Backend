from app.utils.twiml_builder import say, twiml_response


def test_say_escapes_xml():
    xml = twiml_response(say('Press 1 & say "hello"'))
    assert "&amp;" in xml or "&" not in xml.split("Say>")[1]
