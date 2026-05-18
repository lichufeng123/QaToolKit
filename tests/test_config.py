from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from qatoolkit.shared import config


class ConfigTests(unittest.TestCase):
    def test_local_settings_take_priority_over_environment_and_can_clear_secret(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("qatoolkit.shared.config._project_root", return_value=root), patch.dict(
                "os.environ",
                {
                    "QWEN_MODEL": "env-model",
                    "ZENTAO_TOKEN": "env-token",
                },
                clear=False,
            ):
                config.save_local_settings(
                    {
                        "llm_model": "local-model",
                        "zentao_token": "local-token",
                        "default_api_mode": "full",
                    }
                )
                settings = config.load_settings()

                self.assertEqual(settings.llm_model, "local-model")
                self.assertEqual(settings.zentao_token, "local-token")
                self.assertEqual(settings.default_api_mode, "full")

                config.save_local_settings({}, clear_fields=["zentao_token"])
                settings = config.load_settings()

                self.assertEqual(settings.zentao_token, "env-token")


if __name__ == "__main__":
    unittest.main()
