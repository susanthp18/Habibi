"""The user configuration route accepts the Azure voice map it stores."""

from api.routes.user import UserConfigurationRequestResponseSchema


def test_user_configuration_response_accepts_voice_map():
    config = UserConfigurationRequestResponseSchema.model_validate({
        "tts": {"voice_map": {"en-IN": "en-IN-NeerjaNeural"}},
    })

    assert config.tts["voice_map"] == {"en-IN": "en-IN-NeerjaNeural"}


def test_user_configuration_response_accepts_empty_voice_map():
    config = UserConfigurationRequestResponseSchema.model_validate({
        "tts": {"voice_map": {}},
    })

    assert config.tts["voice_map"] == {}
