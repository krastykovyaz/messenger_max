"""Offline tests for scheduling, retries and the no-double-post rules. No network, no browser.

Run: venv/bin/python -m unittest test_family_post -v
"""
import os
import tempfile
import unittest
from datetime import datetime
from unittest import mock

import family_chat_with_pic as f
import extras
import ai_generator


def at(hour, minute=0, day=7):
    return datetime(2026, 11, day, hour, minute, tzinfo=f.MSK)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p_state = mock.patch.object(f, "LAST_POST_FILE", os.path.join(self.tmp.name, "last"))
        self.p_state.start()
        self.p_sleep = mock.patch.object(f.time, "sleep")
        self.sleep = self.p_sleep.start()
        self.p_alert = mock.patch.object(f, "alert")
        self.alert = self.p_alert.start()
        self.p_hb = mock.patch.object(f, "heartbeat")
        self.hb = self.p_hb.start()

    def tearDown(self):
        mock.patch.stopall()
        self.tmp.cleanup()

    def now(self, dt):
        return mock.patch.object(f, "moscow_now", return_value=dt)


class Schedule(Base):
    def test_before_six_waits_until_six(self):
        with self.now(at(5, 30)):
            self.assertEqual(f.seconds_until_post(), 30 * 60)

    def test_inside_catch_up_window_posts_now(self):
        with self.now(at(6, 20)):
            self.assertEqual(f.seconds_until_post(), 0)

    def test_after_window_waits_for_tomorrow(self):
        with self.now(at(9, 0)):
            self.assertEqual(f.seconds_until_post(), 21 * 3600)

    def test_already_posted_today_waits_for_tomorrow(self):
        with self.now(at(6, 5)):
            f.mark_day_done()
            self.assertAlmostEqual(f.seconds_until_post(), 24 * 3600 - 5 * 60)


class PostToday(Base):
    def test_photo_success(self):
        with self.now(at(6)), mock.patch.object(f, "run_once", return_value="photo") as run:
            f.post_today()
        run.assert_called_once()
        self.hb.assert_called_once()
        self.alert.assert_not_called()
        with self.now(at(6, 1)):
            self.assertTrue(f.posted_today())

    def test_text_fallback_alerts(self):
        with self.now(at(6)), mock.patch.object(f, "run_once", return_value="text"):
            f.post_today()
        self.hb.assert_called_once()
        self.assertIn("без картинки", self.alert.call_args[0][0])

    def test_unconfirmed_is_never_retried(self):
        with self.now(at(6)), mock.patch.object(f, "run_once", side_effect=f.SendUnconfirmed("x")) as run:
            f.post_today()
        run.assert_called_once()
        self.hb.assert_not_called()
        self.assertIn("Не уверен", self.alert.call_args[0][0])
        with self.now(at(6, 1)):
            self.assertTrue(f.posted_today())

    def test_retries_then_succeeds(self):
        with self.now(at(6)), mock.patch.object(f, "run_once", side_effect=[RuntimeError("a"), "photo"]) as run:
            f.post_today()
        self.assertEqual(run.call_count, 2)
        self.alert.assert_not_called()

    def test_gives_up_after_attempts_and_alerts_once(self):
        with self.now(at(6)), mock.patch.object(f, "run_once", side_effect=RuntimeError("boom")) as run:
            f.post_today()
        self.assertEqual(run.call_count, f.ATTEMPTS)
        self.alert.assert_called_once()
        self.assertIn("boom", self.alert.call_args[0][0])
        with self.now(at(6, 20)):
            self.assertTrue(f.posted_today())   # no second round in the catch-up window


class RunOnce(Base):
    """Browser and network are mocked; checks fallback order and image clean-up."""

    def run_with(self, pic_effect=None, text_effect=None):
        img = os.path.join(self.tmp.name, "pic.jpg")
        open(img, "w").close()
        pw = mock.MagicMock()
        with mock.patch.object(f, "build_message_with_ai", return_value="msg"), \
                mock.patch.object(f, "pick_photo_topic", return_value="t"), \
                mock.patch.object(f, "download_random_image", return_value=img), \
                mock.patch.object(f, "sync_playwright", return_value=pw), \
                mock.patch.object(f, "open_chat"), \
                mock.patch.object(f, "send_message_with_pic", side_effect=pic_effect) as pic, \
                mock.patch.object(f, "send_message", side_effect=text_effect) as text:
            try:
                return f.run_once(), pic, text, img
            except Exception as e:
                return e, pic, text, img

    def test_photo_path(self):
        res, pic, text, img = self.run_with()
        self.assertEqual(res, "photo")
        text.assert_not_called()
        self.assertFalse(os.path.exists(img))

    def test_photo_error_before_enter_falls_back_to_text(self):
        res, pic, text, img = self.run_with(pic_effect=RuntimeError("no attach button"))
        self.assertEqual(res, "text")
        text.assert_called_once()
        self.assertFalse(os.path.exists(img))

    def test_photo_unconfirmed_does_not_send_text(self):
        res, pic, text, img = self.run_with(pic_effect=f.SendUnconfirmed("?"))
        self.assertIsInstance(res, f.SendUnconfirmed)
        text.assert_not_called()
        self.assertFalse(os.path.exists(img))


class Extras(unittest.TestCase):
    def test_birthday_today_and_soon(self):
        with mock.patch.object(extras, "BIRTHDAYS", {(6, 10): "Тестовый"}), \
                mock.patch.object(extras, "_moscow_now", return_value=datetime(2026, 6, 9, 6)):
            self.assertEqual(extras.birthday_lines(), ["🎂 Завтра день рождения: Тестовый"])

    def test_holiday_in_date_line(self):
        with mock.patch.object(extras, "_moscow_now", return_value=datetime(2026, 5, 9, 6)):
            self.assertIn("День Победы", extras.date_line())


class Ai(unittest.TestCase):
    def test_data_is_kept_verbatim_after_greeting(self):
        g = ai_generator.AIDescriptionGeneratorQwenVL()
        with mock.patch.object(g, "_ollama_generate", return_value="Доброе утро! ☀️"):
            self.assertEqual(g.generate_viral_description("line1\nline2"), "Доброе утро! ☀️\n\nline1\nline2")

    def test_fallback_when_model_is_down(self):
        g = ai_generator.AIDescriptionGeneratorQwenVL()
        with mock.patch.object(g, "_ollama_generate", return_value=""):
            self.assertEqual(g.generate_viral_description("data"), "Доброе утро! data")


if __name__ == "__main__":
    unittest.main()
