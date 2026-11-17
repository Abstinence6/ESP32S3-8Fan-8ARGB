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

    def test_closed_handshake_does_not_block_serial_owner(self):
        owner = SerialOwnerServer("COM7", port=0)
        port = owner.listener.getsockname()[1]
        try:
            peer = socket.create_connection(("127.0.0.1", port), timeout=1)
            peer.sendall(b"FANARGB-1 COM7")
            peer.shutdown(socket.SHUT_WR)
            started = time.monotonic()
            owner.poll(FakeSerial())
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertFalse(owner.has_client)
            peer.close()
        finally:
            owner.close()

    def test_coalesced_ack_and_first_telemetry_preserved(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        def respond():
            peer, _ = listener.accept()
            with peer:
                peer.recv(128)
                peer.sendall(b"OK\nCH 1 FAN=75%\n")

        thread = threading.Thread(target=respond)
        thread.start()
        try:
            client = SerialProxyClient("COM7", port=port)
            try:
                self.assertGreater(client.in_waiting, 0)
                self.assertEqual(client.read(3), b"CH ")
                self.assertEqual(client.read(256), b"1 FAN=75%\n")
            finally:
                client.close()
        finally:
            thread.join(timeout=2)
            listener.close()

    def test_fragmented_handshake_does_not_block_agent(self):
        owner = SerialOwnerServer("COM7", port=0)
        port = owner.listener.getsockname()[1]
        peer = socket.create_connection(("127.0.0.1", port), timeout=1)
        fake = FakeSerial()
        try:
            peer.sendall(b"FANARGB-1 ")
            started = time.monotonic()
            owner.poll(fake)
            owner.poll(fake)
            self.assertLess(time.monotonic() - started, 0.05)
            self.assertFalse(owner.has_client)
            peer.sendall(b"COM7\n")
            for _ in range(100):
                owner.poll(fake)
                if owner.has_client:
                    break
                time.sleep(0.002)
            peer.settimeout(1)
            self.assertEqual(peer.recv(8), b"OK\n")
            self.assertTrue(owner.has_client)
        finally:
            peer.close()
            owner.close()

    def test_coalesced_handshake_and_first_command(self):
        owner = SerialOwnerServer("COM7", port=0)
        port = owner.listener.getsockname()[1]
        peer = socket.create_connection(("127.0.0.1", port), timeout=1)
        fake = FakeSerial()
        try:
            peer.sendall(b"FANARGB-1 COM7\nSTATUS\n")
            for _ in range(100):
                owner.poll(fake)
                if owner.has_client:
                    break
                time.sleep(0.002)
            self.assertTrue(owner.has_client)
            self.assertEqual(peer.recv(8), b"OK\n")
            self.assertEqual(fake.sent, [b"STATUS\n"])
        finally:
            peer.close()
            owner.close()

    def test_incomplete_handshake_expires_without_stalling(self):
        owner = SerialOwnerServer("COM7", port=0)
        port = owner.listener.getsockname()[1]
        peer = socket.create_connection(("127.0.0.1", port), timeout=1)
        try:
            peer.sendall(b"FANARGB-1 ")
            owner.poll(FakeSerial())
            started = time.monotonic()
            owner.poll(FakeSerial())
            self.assertLess(time.monotonic() - started, 0.05)
            time.sleep(0.23)
            owner.poll(FakeSerial())
            self.assertFalse(owner.has_client)
            self.assertIsNone(owner._pending_client)
        finally:
            peer.close()
            owner.close()

    @staticmethod
    def _serve(owner, stop):
        while not stop.is_set():
            owner.poll(FakeSerial())
            time.sleep(0.002)

if __name__ == '__main__': unittest.main()
