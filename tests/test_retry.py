from __future__ import annotations

import unittest
from unittest.mock import patch

from uploader.retry import retry_upload


class RetryUploadTests(unittest.TestCase):
    @patch("uploader.retry.time.sleep")
    def test_retries_then_succeeds(self, mock_sleep) -> None:
        attempts = []

        def run():
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError("temporary failure")
            return "ok"

        self.assertEqual(retry_upload(run), "ok")
        self.assertEqual(len(attempts), 3)
        self.assertEqual(
            mock_sleep.call_args_list, [unittest.mock.call(1), unittest.mock.call(2)]
        )

    @patch("uploader.retry.time.sleep")
    def test_gives_up_after_three_attempts(self, mock_sleep) -> None:
        attempts = []

        def run():
            attempts.append(1)
            raise RuntimeError("temporary failure")

        with self.assertRaisesRegex(RuntimeError, "temporary failure"):
            retry_upload(run)

        self.assertEqual(len(attempts), 3)
        self.assertEqual(
            mock_sleep.call_args_list, [unittest.mock.call(1), unittest.mock.call(2)]
        )


if __name__ == "__main__":
    unittest.main()
