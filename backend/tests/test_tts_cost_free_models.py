"""Voice Studio TTS usage is priced by the model the engine reports."""

import usage_meter as um


def test_the_free_fish_model_costs_nothing_and_azure_voices_keep_their_price():
    assert um.tts_cost_inr(chars=1000, model="s2.1-pro-free") == 0
    assert um.tts_cost_inr(chars=1000, model="fish-audio/s2.1-pro-free:free") == 0
    assert um.tts_cost_inr(chars=1000, model="en-IN-NeerjaNeural") > 0
    assert um.tts_cost_inr(chars=1000) > 0
