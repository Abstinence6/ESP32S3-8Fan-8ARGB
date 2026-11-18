import unittest
from pc_app.audio_capture import audio_command, LoopbackAudioCapture, analyze_pcm

class AudioCaptureTests(unittest.TestCase):
    def test_serial_protocol_and_default_opt_out(self):
        self.assertEqual(audio_command((1,25,100,255)), "AUDIO 1 25 100 255")
        for bad in ((1,2,3), (1,-1,3,4), (0,0,0,256), (1.5,2,3,4)):
            with self.assertRaises(ValueError):
                audio_command(bad)
        capture=LoopbackAudioCapture()
        self.assertFalse(capture.running)
        self.assertIsNone(capture.read_latest())

    def test_fft_synthetic_sine_when_numpy_present(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("NumPy optional before GUI dependencies install")
        t=np.arange(2048)/24000.
        pcm=0.5*np.sin(2*np.pi*100*t)
        bass,mid,high,peak=analyze_pcm(pcm,24000,np)
        self.assertGreater(bass,mid)
        self.assertGreater(bass,high)
        self.assertGreater(peak,50)
        self.assertEqual(analyze_pcm(np.zeros(2048),24000,np),(0,0,0,0))

if __name__=="__main__":
    unittest.main()
