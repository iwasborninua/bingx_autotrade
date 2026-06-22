import importlib
import os
import unittest
from unittest.mock import patch


class ConfigAliasTest(unittest.TestCase):
    def test_coinalyze_api_alias_is_accepted(self) -> None:
        with patch.dict(os.environ, {"COINALYZE_API_KEY": "", "COINALYZE_API": "alias-key"}, clear=False):
            import app.config as config

            reloaded = importlib.reload(config)

        self.assertEqual(reloaded.COINALYZE_API_KEY, "alias-key")


if __name__ == "__main__":
    unittest.main()
