import socket
import threading
import time
import unittest
from pc_app.serial_owner import SerialOwnerServer, SerialProxyClient

class FakeSerial:
    def __init__(self):
        self.sent = []
    def write(self, data):
        self.sent.append(data)
        return len(data)

class SerialOwnerTests(unittest.TestCase):
    def test_proxy_handshake_and_raw_binary_stream(self):
        owner = SerialOwnerServer("COM7", port=0)
        port = owner.listener.getsockname()[1]
        fake = FakeSerial()
        stop = threading.Event()
        def serve():
            while not stop.is_set():
                owner.poll(fake)
                time.sleep(0.002)
        thread = threading.Thread(target=serve)
        thread.start()
        try:
            client = SerialProxyClient("COM7", port=port)
            try:
                packet = b'\xa5\x5a\x03\x00\xff\n'
                self.assertEqual(client.write(packet), len(packet))
                for _ in range(100):
                    if fake.sent: break
                    time.sleep(0.005)
                self.assertIn(packet, fake.sent)
                owner.forward(b'OK\n')
                for _ in range(100):
                    if client.in_waiting: break
                    time.sleep(0.005)
                self.assertEqual(client.read(100), b'OK\n')
            finally:
                client.close()
        finally:
            stop.set()
            thread.join(timeout=2)
            owner.close()

    def test_rejects_wrong_com_port(self):
        owner = SerialOwnerServer("COM7", port=0)
        port = owner.listener.getsockname()[1]
        stop = threading.Event()
        thread = threading.Thread(target=lambda: self._serve(owner, stop))
        thread.start()
        try:
            with self.assertRaises(ConnectionError):
                SerialProxyClient("COM8", port=port)
        finally:
            stop.set()
            thread.join(timeout=2)
            owner.close()

    @staticmethod
    def _serve(owner, stop):
        while not stop.is_set():
            owner.poll(FakeSerial())
            time.sleep(0.002)

if __name__ == '__main__': unittest.main()
