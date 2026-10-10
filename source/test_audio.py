import io
import unittest
import wave
from unittest.mock import patch
import cyberleek_watcher as engine


class AudioTests(unittest.TestCase):
    def test_pcm_chimes_are_valid_nonempty_wavs(self):
        for style in ('info', 'urgent'):
            data = engine._chime_wav(style)
            with wave.open(io.BytesIO(data), 'rb') as audio:
                self.assertEqual(audio.getnchannels(), 1)
                self.assertEqual(audio.getsampwidth(), 2)
                self.assertEqual(audio.getframerate(), 22050)
                self.assertGreater(audio.getnframes(), 22050)
                self.assertTrue(any(audio.readframes(audio.getnframes())))

    def test_muted_alerts_and_forced_test(self):
        with patch.object(engine, '_enable_sound', False), patch.object(engine, 'HAS_WINSOUND', True), patch.object(engine.threading, 'Thread') as worker:
            engine.play_info_chime()
            worker.assert_not_called()
            engine._play_chime('info', force=True)
            worker.assert_called_once_with(target=engine._windows_chime_worker, args=('info', True), daemon=True)
            worker.return_value.start.assert_called_once()

    def test_memory_playback_and_error_fallback(self):
        with patch.object(engine.winsound, 'PlaySound') as play, patch.object(engine, 'log_msg'):
            engine._windows_chime_worker('info', test=True)
            data, flags = play.call_args.args
            self.assertEqual(data[:4], b'RIFF')
            self.assertTrue(flags & engine.winsound.SND_MEMORY)
            self.assertFalse(flags & engine.winsound.SND_ASYNC)
        with patch.object(engine.winsound, 'PlaySound', side_effect=RuntimeError('device error')), patch.object(engine.winsound, 'MessageBeep') as fallback, patch.object(engine, 'log_msg') as log:
            engine._windows_chime_worker('info', test=True)
            fallback.assert_called_once()
            self.assertTrue(any('device error' in str(call) for call in log.call_args_list))
        self.assertFalse(engine._audio_lock.locked())

    def test_concurrent_test_reports_busy(self):
        engine._audio_lock.acquire()
        try:
            with patch.object(engine.winsound, 'PlaySound') as play, patch.object(engine, 'log_msg') as log:
                engine._windows_chime_worker('info', test=True)
                play.assert_not_called()
                self.assertIn('already playing', log.call_args.args[0])
        finally:
            engine._audio_lock.release()


if __name__ == '__main__':
    unittest.main()
