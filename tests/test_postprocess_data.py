import json
from importlib import resources

from tuparles import lexicon, punctuation
from tuparles.data import postprocess


def test_postprocess_json_schema_and_loaded_tables():
    resource = resources.files("tuparles.data").joinpath(postprocess.DATA_FILE)
    with resource.open(encoding="utf-8") as f:
        data = json.load(f)

    assert isinstance(data["schema_version"], int)
    assert {"LEXICON", "SPOKEN_TO_SYMBOL", "PROTECTED_PHRASES"} <= data.keys()
    expected_spoken_to_symbol = [tuple(pair) for pair in data["SPOKEN_TO_SYMBOL"]]
    assert expected_spoken_to_symbol == punctuation.SPOKEN_TO_SYMBOL
    assert lexicon.LEXICON
    assert punctuation.SPOKEN_TO_SYMBOL
    assert punctuation.PROTECTED_PHRASES
